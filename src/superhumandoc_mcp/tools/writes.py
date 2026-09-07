"""Write tools: thin translations between the model's vocabulary and
`api.py`'s write methods, following the shape `tools/reads.py` sets.

Each tool function is directly testable without a server — it takes a
`DocsApi` as its first argument. `register_write_tools` is the seam that
closes each one over a single `DocsApi` instance and the one shared
`ColumnCache` and puts it on the server, because the object the model calls
cannot itself take those as model-visible parameters.

Every write here polls its mutation to a settled outcome through
`await_mutation` before returning, and reports exactly what that poll found:
`applied` once the API confirms it, `unknown` — never `failed` — if the poll
gives up first. `polling.UNKNOWN` carries the sentence that an unknown write
may already have gone through, written once so no tool re-words it.

`update_row` and `upsert_rows` add a second axis on top of that: a row batch
too large for one request is split by `chunking.py` and sent as several,
each polled to its own outcome, so a partial success is reported as such
rather than collapsed into one verdict for the whole call.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from mcp.server import MCPServer

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.cells import cells_for_write
from superhumandoc_mcp.chunking import plan_chunks, send_chunks
from superhumandoc_mcp.content import canvas_content
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ContentRefused
from superhumandoc_mcp.outcomes import BatchReport
from superhumandoc_mcp.polling import UNKNOWN, MutationOutcome, await_mutation
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.sizing import MAX_REQUEST_BYTES, MAX_ROW_INTERNAL_BYTES
from superhumandoc_mcp.tools.boundary import tool_boundary

MAX_ROWS_PER_UPSERT = 100
"""The row-count cap `upsert_rows` chunks a batch against.

No published limit exists — a user report of "several hundred rows" working
in one call is the only evidence
(docs/reference/api-operational-constants.md §1.2) — but the `request-sizing`
topic picked one number to split a batch against rather than leaving the
count unbounded. Not defined in `sizing.py`, which carries only the two byte
caps `plan_chunks` also takes: this one is specific to which operation
`upsert_rows` calls, the same way `MAX_ROW_IDS_PER_DELETE` belongs to
`delete_rows` rather than to the shared sizing module.
"""

# The only two positions append_to_page accepts. Additive by construction —
# there is no third value that would let this tool replace or remove
# anything, which is the point: a caller reaching for that needs
# replace_element or the gated overwrite_page instead.
_APPEND_POSITIONS = {"append", "prepend"}

_CREATE_PAGE_DESCRIPTION = (
    "Create a new page named `name`, optionally nested under "
    "`parent_page_id`, with `subtitle` and an initial HTML `content` body "
    "for its canvas. `content` must be text the caller composed — output "
    "this server returned from a read, such as outline_page's lines, must "
    "not be pasted back in here; sending a read back out as a write is "
    "exactly what degrades a document over repeated edits. Reports the "
    "write's outcome as `applied` once the mutation is confirmed, or "
    "`unknown` — never `failed` — if confirmation could not be obtained "
    "before the call's deadline; an unknown outcome may already have gone "
    "through. A read immediately afterward may still show the old state: "
    "the document snapshot can lag behind the API's own acknowledgement of "
    "the write."
)

_APPEND_TO_PAGE_DESCRIPTION = (
    "Append HTML `content` to an existing page's canvas — or, with "
    "`position=\"prepend\"`, add it before the existing content. Additive "
    "only: append and prepend are the only positions this tool accepts, so "
    "there is no way to replace or remove anything through it. `content` "
    "must not be text read back from this server, outline_page's output "
    "included — round-tripping a read through a write is the loop that "
    "compounds content loss on every pass, so write only content you "
    "composed yourself. Reports `applied` once confirmed, or `unknown` — "
    "never `failed` — if the poll gives up first; an unknown outcome may "
    "already have applied, and an immediate read-back may still lag behind "
    "it."
)

_RENAME_PAGE_DESCRIPTION = (
    "Rename a page to `name`. Carries only the name, never `content`, so a "
    "rename cannot touch or clear the page body. As with every write here, "
    "`name` must not be text this server returned from a read, fed back "
    "verbatim — choose the name yourself, the same way create_page and "
    "append_to_page require caller-composed content. Reports `applied` "
    "once the rename is confirmed, or `unknown` — never `failed` — if the "
    "poll gives up first; an unknown outcome may already have applied."
)

_REPLACE_ELEMENT_DESCRIPTION = (
    "Replace exactly one element, named by `element_id`, with new HTML "
    "`content`; every other element on the page is left untouched, and "
    "there is deliberately no way to spell \"replace the whole page\" "
    "through this tool. `element_id` may come from outline_page, but "
    "`content` must not: text this server returned from a read must never "
    "be sent back here as the replacement, since writing a read back out "
    "is the loop that compounds content loss on every pass. Reports "
    "`applied` once confirmed, or `unknown` — never `failed` — if the poll "
    "gives up first; an unknown outcome may already have applied, and an "
    "immediate read-back may still lag behind it."
)

_UPDATE_ROW_DESCRIPTION = (
    "Update one row's cells, addressed by `row_id` — never by name. The API "
    "accepts a name here too but affects an arbitrary row on collision, "
    "which is a silent wrong-row write; get an ID from get_row or find_rows, "
    "which both return `row_id` for exactly this purpose. `cells` is keyed "
    "by column name, resolved against this table's schema: a calculated or "
    "button column, or a name the schema does not know, is refused before "
    "anything is sent. As with every write here, cell values must not be "
    "text this server returned from a read, fed back verbatim — a value "
    "read from get_row must never be sent back here as the update, since "
    "writing a read back out is the loop that compounds content loss on "
    "every pass. Reports `applied` once confirmed, or `unknown` — never "
    "`failed` — if the poll gives up first; an unknown outcome may already "
    "have applied."
)

_UPSERT_ROWS_DESCRIPTION = (
    "Insert or update up to many rows in one call. A batch larger than this "
    "API's per-request caps is split into several requests and sent in "
    "order automatically — the caller never pre-splits. Pass `key_columns`, "
    "the column name(s) that uniquely identify a row, to upsert on those "
    "columns instead of always inserting, and — just as important — to make "
    "the call replay-safe: with `key_columns` set, a request lost mid-flight "
    "can be retried without duplicating rows; without them this API has no "
    "idempotency keys, every row is a plain insert, and retrying to resolve "
    "an unknown outcome risks writing it twice. As with every write here, a "
    "row's values must not be cells this server returned from a read, fed "
    "back verbatim — data read from get_row or find_rows must never be sent "
    "back here as a write, since that round trip is what compounds content "
    "loss on every pass. Returns one entry per row given, in the order "
    "given, each carrying `index`, `outcome` (`applied`, `unknown`, "
    "`refused`, or `not_attempted`) and `warning`; plus `chunks`, how many "
    "requests the batch was split into, and `resume_from`, the index of the "
    "first row never attempted — re-call with `rows` sliced from there to "
    "resume a batch a deadline cut short. An unknown outcome may already "
    "have applied; a refused row was rejected by the API and nothing later "
    "depends on it."
)


async def _outcome(
    api: DocsApi,
    response: dict,
    deadline: Deadline,
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]],
) -> MutationOutcome:
    """Turn a write's 202 body into a `MutationOutcome`.

    Assumption 6 of the write wave: some 202s carry no `requestId` at all —
    `docs/reference/api-operational-constants.md` records which operations
    do this — and nothing can be polled without one. Left unhandled that is
    a `KeyError`, which `tool_boundary` deliberately does not translate, so
    a model would see "Error executing tool" for a write that may have
    succeeded. Reported as unknown instead, same as a poll that gives up.

    Returns `polling.py`'s own outcome type rather than a dict, so a chunked
    write's `send` callback can hand it straight to `send_chunks`, which is
    written against `MutationOutcome` — `_report` below is the dict-shaped
    wrapper for the single-mutation tools.
    """
    request_id = response.get("requestId")
    if request_id is None:
        return MutationOutcome(False, None, UNKNOWN)
    return await await_mutation(api, request_id, deadline, clock=clock, sleep=sleep)


async def _report(
    api: DocsApi,
    response: dict,
    deadline: Deadline,
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]],
) -> dict:
    """Turn a write's 202 body into the outcome a model sees, for a tool
    that makes exactly one mutation. `upsert_rows` makes several and reports
    per row instead; see `_outcome`, which this is built on."""
    outcome = await _outcome(api, response, deadline, clock=clock, sleep=sleep)
    return {
        "outcome": "applied" if outcome.applied else "unknown",
        "detail": outcome.detail,
        "warning": outcome.warning,
    }


def _cells_by_id(cells: dict, columns: list[dict]) -> dict:
    """`cells_for_write`'s `[{column, value}, ...]` reshaped into the
    `{column_id: value}` mapping `DocsApi.update_row` and `DocsApi.upsert_rows`
    both take. The list shape is `cells.py`'s own contract, exercised in
    tests/test_cells.py; this is the one place in this module that reshapes
    it for the two API methods that want a mapping instead.
    """
    return {cell["column"]: cell["value"] for cell in cells_for_write(cells, columns)}


async def create_page(
    api: DocsApi,
    name: str,
    content: str | None = None,
    *,
    subtitle: str | None = None,
    parent_page_id: str | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict:
    """Create a page, optionally seeding its canvas with `content`.

    `content` goes through `canvas_content`, which refuses `<img>` tags,
    markdown image syntax, and an oversized body before anything is sent —
    the same validation every page-content write in this module shares.
    """
    deadline = Deadline(clock=clock)
    canvas = canvas_content(content) if content is not None else None
    response = await api.create_page(
        name,
        subtitle=subtitle,
        parent_page_id=parent_page_id,
        canvas=canvas,
        deadline=deadline,
    )
    return await _report(api, response, deadline, clock=clock, sleep=sleep)


async def append_to_page(
    api: DocsApi,
    page_id_or_name: str,
    content: str,
    *,
    position: str = "append",
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict:
    """Add `content` to a page's canvas at `position`.

    `position` is refused outside `{"append", "prepend"}` before any
    request is sent: this tool is additive by construction, and "replace"
    is deliberately not a spellable position here — that is
    `replace_element`'s job, or the gated `overwrite_page`'s.
    """
    if position not in _APPEND_POSITIONS:
        raise ContentRefused(
            f"position must be 'append' or 'prepend', not {position!r}. "
            "append_to_page is additive only — it offers no way to "
            "replace or remove content. Use replace_element for an "
            "anchored replacement, or the gated overwrite_page if the "
            "whole page truly needs to change."
        )
    deadline = Deadline(clock=clock)
    canvas = canvas_content(content)
    response = await api.update_page(
        page_id_or_name, canvas=canvas, insertion_mode=position, deadline=deadline
    )
    return await _report(api, response, deadline, clock=clock, sleep=sleep)


async def rename_page(
    api: DocsApi,
    page_id_or_name: str,
    name: str,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict:
    """Rename a page, sending a name and no `canvas` at all.

    `api.update_page` only nests `contentUpdate` when `canvas` is given, so
    leaving it unset here is what keeps this call from carrying an empty
    body that would clear the page.
    """
    deadline = Deadline(clock=clock)
    response = await api.update_page(page_id_or_name, name=name, deadline=deadline)
    return await _report(api, response, deadline, clock=clock, sleep=sleep)


async def replace_element(
    api: DocsApi,
    page_id_or_name: str,
    element_id: str,
    content: str,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict:
    """Replace one element's content, scoped by `element_id`.

    Built because probe B6 measured that a `replace` carrying an
    `elementId` changes only the named element and leaves every element ID
    on the page valid afterward (`docs/reference/api-operational-constants.md`).
    `element_id` has no default, so there is no way to call this with
    `insertion_mode="replace"` and no scope — that would be a whole-page
    wipe, which is exactly what this tool exists to make impossible to
    reach by accident.
    """
    deadline = Deadline(clock=clock)
    canvas = canvas_content(content)
    response = await api.update_page(
        page_id_or_name,
        canvas=canvas,
        insertion_mode="replace",
        element_id=element_id,
        deadline=deadline,
    )
    return await _report(api, response, deadline, clock=clock, sleep=sleep)


async def update_row(
    api: DocsApi,
    cache: ColumnCache,
    table_id_or_name: str,
    row_id: str,
    cells: dict,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict:
    """Update one row, addressed by `row_id`, never by name.

    The degenerate case of chunking: one row, nothing to halve, so this
    function calls `api.update_row` directly rather than going through
    `chunking.py`. A size refusal on a single oversized row has nothing left
    to split it into and simply propagates, the same as `_is_size_refusal`
    treats a singleton chunk in `send_chunks`.

    `cells` is keyed by column name and resolved through the shared
    `ColumnCache` by `_cells_by_id`, which refuses a calculated column, a
    button column, or an unknown name before this spends a request.
    """
    deadline = Deadline(clock=clock)
    columns = await cache.columns(table_id_or_name, deadline)
    response = await api.update_row(
        table_id_or_name, row_id, _cells_by_id(cells, columns), deadline
    )
    return await _report(api, response, deadline, clock=clock, sleep=sleep)


async def upsert_rows(
    api: DocsApi,
    cache: ColumnCache,
    table_id_or_name: str,
    rows: list[dict],
    *,
    key_columns: list[str] | None = None,
    deadline: Deadline | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict:
    """Insert or update `rows`, splitting a batch over `MAX_ROWS_PER_UPSERT`
    (or the byte caps `sizing.py` defines) into chunks `chunking.py` sends
    in order, and reporting one outcome per row.

    Every row is resolved to column IDs by `cells_for_write`, through
    `_cells_by_id`, against the *whole* batch before the first chunk is ever
    sent — a bad column name on row 90 must be refused before rows 1 through
    89 go out, not discovered only after. `plan_chunks` and `send_chunks`
    then own everything about the split itself: which cap binds, how a size
    refusal is halved and retried, and how a chunk that could not even be
    started becomes a suffix of `not_attempted` rows.

    The wider report this returns — `rows` carrying `index` alongside
    `BatchReport`'s own `outcome`/`warning`, plus `chunks` and
    `resume_from` — is composed here rather than by widening
    `BatchReport.as_dict`, which stays exactly what `outcomes.py`'s own
    tests pin: one row's outcome and warning, nothing else. `chunks` is a
    fact only this function has (`BatchReport` is never told how many
    chunks were planned), and `resume_from` already exists as
    `BatchReport.resume_from()`, so nothing here duplicates logic that
    object already owns.

    `deadline` is accepted directly, unlike every other tool in this module,
    so a caller — a test, in practice — can size the budget without also
    replacing `clock`; the registered tool never exposes it and always
    builds one from `clock` like the rest.
    """
    deadline = deadline if deadline is not None else Deadline(clock=clock)
    columns = await cache.columns(table_id_or_name, deadline)
    formatted_rows = [_cells_by_id(row, columns) for row in rows]

    async def send(indices: list[int]) -> MutationOutcome:
        response = await api.upsert_rows(
            table_id_or_name,
            [formatted_rows[i] for i in indices],
            key_columns=key_columns,
            deadline=deadline,
        )
        return await _outcome(api, response, deadline, clock=clock, sleep=sleep)

    chunks = plan_chunks(
        formatted_rows,
        max_rows=MAX_ROWS_PER_UPSERT,
        max_row_bytes=MAX_ROW_INTERNAL_BYTES,
        max_request_bytes=MAX_REQUEST_BYTES,
    )
    report = BatchReport.for_rows(rows)
    await send_chunks(chunks, formatted_rows, send, deadline, report=report)

    report_dict = report.as_dict()
    return {
        "rows": [
            {"index": index, **row} for index, row in enumerate(report_dict["rows"])
        ],
        "chunks": len(chunks),
        "resume_from": report.resume_from(),
    }


def register_write_tools(server: MCPServer, api: DocsApi, cache: ColumnCache) -> None:
    """Register the always-on write tools on `server`, closing over `api`
    the same way `register_read_tools` closes over it for reads.

    `cache` is the one `ColumnCache` `build_server` constructs, shared with
    `register_read_tools`: `update_row` and `upsert_rows` below resolve
    every column name against it, the same cache `describe_table` and
    `get_row` read through, so a name resolved by a read and a name resolved
    by a write never disagree.
    """

    @server.tool(name="create_page", description=_CREATE_PAGE_DESCRIPTION)
    @tool_boundary
    async def create_page_tool(
        name: str,
        content: str | None = None,
        subtitle: str | None = None,
        parent_page_id: str | None = None,
    ) -> dict:
        return await create_page(
            api, name, content, subtitle=subtitle, parent_page_id=parent_page_id
        )

    @server.tool(name="append_to_page", description=_APPEND_TO_PAGE_DESCRIPTION)
    @tool_boundary
    async def append_to_page_tool(
        page_id_or_name: str, content: str, position: str = "append"
    ) -> dict:
        return await append_to_page(api, page_id_or_name, content, position=position)

    @server.tool(name="rename_page", description=_RENAME_PAGE_DESCRIPTION)
    @tool_boundary
    async def rename_page_tool(page_id_or_name: str, name: str) -> dict:
        return await rename_page(api, page_id_or_name, name)

    @server.tool(name="replace_element", description=_REPLACE_ELEMENT_DESCRIPTION)
    @tool_boundary
    async def replace_element_tool(
        page_id_or_name: str, element_id: str, content: str
    ) -> dict:
        return await replace_element(api, page_id_or_name, element_id, content)

    @server.tool(name="update_row", description=_UPDATE_ROW_DESCRIPTION)
    @tool_boundary
    async def update_row_tool(table_id_or_name: str, row_id: str, cells: dict) -> dict:
        return await update_row(api, cache, table_id_or_name, row_id, cells)

    @server.tool(name="upsert_rows", description=_UPSERT_ROWS_DESCRIPTION)
    @tool_boundary
    async def upsert_rows_tool(
        table_id_or_name: str,
        rows: list[dict],
        key_columns: list[str] | None = None,
    ) -> dict:
        return await upsert_rows(
            api, cache, table_id_or_name, rows, key_columns=key_columns
        )
