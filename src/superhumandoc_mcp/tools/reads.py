"""Read tools: thin translations between the model's vocabulary and `api.py`.

Each tool function is directly testable without a server — it takes a
`DocsApi` as its first argument. `register_read_tools` is the seam that closes
each one over a single `DocsApi` instance and puts it on the server, because
the object the model calls cannot itself take an `api` argument.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from mcp.server import MCPServer

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.downloads import Downloader
from superhumandoc_mcp.errors import ClientError
from superhumandoc_mcp.export import export_page
from superhumandoc_mcp.gate import ExportGate
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.tools.boundary import tool_boundary

# The only contentType read_page can export. Every other type is refused
# before any export is attempted, because contentType is readable up front
# -- the tool-surface topic requires that refusal name the type found rather
# than let a caller discover it from a failed export. Only `syncPage` has
# been observed failing an export (docs/reference/api-operational-constants.md
# §3.2 item 1 records `embed` as untested), so the refusal is stated as this
# tool's own precondition rather than as a claim about the API.
_EXPORTABLE_CONTENT_TYPE = "canvas"

# The export supports markdown too, and the two differ -- markdown drops
# page-level attachments where HTML retains them -- but the tool-surface
# topic names one format, so this is fixed rather than model-visible.
_READ_PAGE_OUTPUT_FORMAT = "html"

# Recorded in docs/reference/api-operational-constants.md. At or below this
# many tables, get_doc_overview also returns each table's column schema
# inline; above it, columns are omitted and the response says so.
OVERVIEW_INLINE_COLUMNS_MAX_TABLES = 8

_OUTLINE_PAGE_DESCRIPTION = (
    "Return a page's outline: an ordered list of "
    "{element_id, style, level, text}, one entry per line of the page. A "
    "page outline is a projection of the page, not its full content. It is "
    "cheap, works with a read-only token, and is the only source of the "
    "stable element IDs that anchored editing needs."
)

_DESCRIBE_TABLE_DESCRIPTION = (
    "Return one table's column schema, keyed the same way as its rows. Reads "
    "from the same cache the row tools use, so calling this warms rather "
    "than duplicates that work."
)

_GET_DOC_OVERVIEW_DESCRIPTION = (
    "Return the document's page tree and table list, in one call, so a "
    f"model can orient in one turn. At or below {OVERVIEW_INLINE_COLUMNS_MAX_TABLES} "
    "tables each table's column schema is included inline; above that "
    "threshold columns are omitted and the response says so, directing the "
    "caller to describe_table for any table it needs the schema of."
)

_GET_ROW_DESCRIPTION = (
    "Return one row by its ID, with its cells keyed by column name. Rows are "
    "addressed by ID, never by name: the API accepts a name but affects an "
    "arbitrary row on collision. The returned row always carries `row_id`, "
    "because every write addresses a row by that value."
)

_FIND_ROWS_DESCRIPTION = (
    "List a table's rows, up to `limit`, with cells keyed by column name and "
    "each row carrying its row ID. Server-side filtering supports at most "
    "one column, exact-value match only; every other condition is applied "
    "client-side after paging."
)

_READ_PAGE_DESCRIPTION = (
    "Return a page's content rendered as HTML. Expensive: this runs an "
    "asynchronous export rather than a plain read, so call outline_page "
    "instead when only the text and its structure are needed. The result "
    "is a projection of the page, not the page itself — images, tables, "
    "buttons, controls, callouts and dividers may be missing or flattened "
    "in the rendered output, so this must not be treated as an "
    "authoritative account of everything the page contains. Requires "
    "`contentType == \"canvas\"`: any other type is refused, naming the "
    "type found, before any export is attempted — a sync page is known to "
    "fail the export, and no other type has been tried. Rendered content is "
    "cached against the page's `updatedAt`, so re-reading an unchanged page "
    "is cheap; a page that reports no `updatedAt` is not cached at all and "
    "pays for a full export every time. Its output must not be sent "
    "back to create_page, append_to_page, replace_element, or any other "
    "write on this surface — writing a read back out is exactly the loop "
    "that compounds content loss on every pass."
)


async def outline_page(api: DocsApi, page_id_or_name: str) -> list[dict]:
    """Return the page's lines as an ordered list of `{element_id, style,
    level, text}`.

    Probe P9: `style` and `lineLevel` are nested inside each item's
    `itemContent`, not at the item's top level. Reading them flat yields
    silent `None`s that look like valid data, so they are read from there.

    The line's text is `itemContent.content`, not `itemContent.text` — there
    is no `text` key anywhere in the item. The outward key stays `text`
    because that is the word a model reads; only the source moves.
    """
    items = await api.list_page_content(page_id_or_name, Deadline())
    lines = []
    for item in items:
        content = item.get("itemContent", {})
        lines.append(
            {
                "element_id": item.get("id"),
                "style": content.get("style"),
                "level": content.get("lineLevel"),
                "text": content.get("content", ""),
            }
        )
    return lines


async def describe_table(cache: ColumnCache, table_id_or_name: str) -> list[dict]:
    """Return one table's column schema, reading through the shared
    `ColumnCache` so this call warms it rather than duplicating a fetch the
    row tools (or `get_doc_overview`) may already have made or will make."""
    return await cache.columns(table_id_or_name, Deadline())


async def get_doc_overview(api: DocsApi, cache: ColumnCache) -> dict:
    """Return the page tree and the table list.

    At or below `OVERVIEW_INLINE_COLUMNS_MAX_TABLES` tables, each table's
    column schema is fetched (through the shared cache, so it costs at most
    one `listColumns` per table) and returned inline. Above that threshold,
    columns are omitted entirely rather than fetched and discarded, and the
    response names `describe_table` explicitly — a model cannot see the
    threshold, so the response itself must say what to call next.
    """
    deadline = Deadline()
    pages = await api.list_pages(deadline)
    tables = await api.list_tables(deadline)

    if len(tables) <= OVERVIEW_INLINE_COLUMNS_MAX_TABLES:
        tables_out = []
        for table in tables:
            columns = await cache.columns(table["id"], deadline)
            tables_out.append({**table, "columns": columns})
        return {"pages": pages, "tables": tables_out}

    return {
        "pages": pages,
        "tables": tables,
        "columns_omitted": (
            f"This document has more than {OVERVIEW_INLINE_COLUMNS_MAX_TABLES} "
            "tables, so column schemas were omitted from this overview. Call "
            "describe_table with a table's ID or name to get its columns."
        ),
    }


def _cells_by_name(values: dict, columns: list[dict]) -> dict:
    """Resolve a row's `values` (keyed by column ID — real keys look like
    `c-euWseAF6J-`, docs/reference/api-operational-constants.md §6) against a
    table's column schema.

    A column ID that the schema does not know about — a stale cache entry, or
    a column the schema listing simply omitted — is not dropped: the cell is
    kept under its raw ID rather than silently losing data.
    """
    name_by_id = {column["id"]: column["name"] for column in columns}
    return {
        name_by_id.get(column_id, column_id): value
        for column_id, value in values.items()
    }


async def get_row(
    api: DocsApi, cache: ColumnCache, table_id_or_name: str, row_id: str
) -> dict:
    """Return one row with its cells keyed by column name, resolved through
    the shared `ColumnCache`.

    The row always carries `row_id`: rows are addressed by ID, never by
    name — the API accepts a name but affects an arbitrary row on
    collision — and every later write needs this value to name the row it
    changes.
    """
    deadline = Deadline()
    row = await api.get_row(table_id_or_name, row_id, deadline)
    columns = await cache.columns(table_id_or_name, deadline)
    return {
        "row_id": row.get("id", row_id),
        "cells": _cells_by_name(row.get("values", {}), columns),
    }


async def find_rows(
    api: DocsApi,
    cache: ColumnCache,
    table_id_or_name: str,
    *,
    filters: dict[str, object] | None = None,
    sort: str | None = None,
    limit: int = 200,
) -> dict:
    """List a table's rows, up to `limit`, with cells keyed by column name and
    each row carrying its row ID — the same resolution `get_row` performs,
    applied to every row a listing pass returns.

    Server-side filtering supports exactly one column, exact-value match
    only. When `filters` is given, only its first entry is offered to the API
    as a query condition; every entry in `filters` — including that first
    one — is still checked here after paging, so correctness never depends
    on whether the server actually applied it. `sort`, if given, is passed
    through to the API unchanged.

    Ladders through `DocsApi.list_rows`'s 504 handling, set by the
    `request-sizing` topic,
    which has shipped tested only against a mock: no 504 has ever been
    observed from this client against the real API.

    Returns `{"rows", "complete", "note"}` rather than a bare list. The tool
    pages up to the caller's cap, so a short result is ambiguous on its own —
    it could be a small table or a listing the deadline cut short, and the
    `request-sizing` topic requires the difference be said aloud rather than
    left to be inferred.
    The shape does not vary with the outcome: a caller that has to test for
    the presence of a key to learn whether it saw the whole table will
    eventually forget to.
    """
    deadline = Deadline()
    columns = await cache.columns(table_id_or_name, deadline)
    id_by_name = {column["name"]: column["id"] for column in columns}

    params: dict[str, object] = {}
    if filters:
        column, value = next(iter(filters.items()))
        column_id = id_by_name.get(column, column)
        params["query"] = f'{column_id}:"{value}"'
    if sort:
        params["sortBy"] = sort

    listing = await api.list_rows(
        table_id_or_name, deadline, limit=limit, params=params or None
    )
    resolved = [
        {
            "row_id": row.get("id"),
            "cells": _cells_by_name(row.get("values", {}), columns),
        }
        for row in listing.rows
    ]

    if filters:
        resolved = [
            row
            for row in resolved
            if all(row["cells"].get(key) == value for key, value in filters.items())
        ]

    note = None
    if not listing.complete:
        note = (
            f"Incomplete: stopped at {listing.stopped_because} after reading "
            f"{len(listing.rows)} rows, short of the requested {limit}. This "
            "is part of the table, not all of it. Ask for fewer rows, or "
            "narrow the filter, to see the rest."
        )
    return {"rows": resolved, "complete": listing.complete, "note": note}


class PageCache:
    """Caches a page's rendered HTML against `(page_id, updatedAt)` — both
    parts, never `updatedAt` alone. Two pages sharing a timestamp is
    ordinary after a bulk edit or a duplicated template; keying on the
    timestamp alone would serve one page's render for the other, which is
    silent wrong-page content.

    `page_id` is the canonical id from the `getPage` body, not whatever
    string the caller used to name the page — see `read_page`, which
    resolves it. Two entries for one page, one under its id and one under a
    name, is the same wrong-page content by a different route, because a
    name can later be moved to a different page.

    One slot per page, replaced whenever the timestamp changes. Both parts
    still have to match for a `get` to hit, so a stale timestamp misses
    exactly as it would with an entry of its own — nothing is lost, since a
    superseded `updatedAt` is never asked for again, and the dict then
    plateaus at the document's page count the way `ExportGate._per_page`
    does. Keeping every timestamp instead would grow a full HTML render per
    edit-then-read, for the life of the process.

    A missing or null `updatedAt` is not a cache key at all: `get` always
    misses and `set` is a no-op, because a render that cannot be
    invalidated is worse than paying for another export.
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[str, str]] = {}

    def __len__(self) -> int:
        """How many pages are held. Public so the bound this class claims is
        something a test can assert rather than something a docstring
        asserts — that is precisely how the unbounded version shipped."""
        return len(self._entries)

    def get(self, page_id: str, updated_at: str | None) -> str | None:
        if updated_at is None:
            return None
        entry = self._entries.get(page_id)
        if entry is None or entry[0] != updated_at:
            return None
        return entry[1]

    def set(self, page_id: str, updated_at: str | None, html: str) -> None:
        if updated_at is None:
            return
        self._entries[page_id] = (updated_at, html)


async def read_page(
    api: DocsApi,
    downloader: Downloader,
    gate: ExportGate,
    cache: PageCache,
    page_id_or_name: str,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict:
    """Return `{"html": ...}`, the page rendered through the export flow.

    `get_page` is read first, cheaply, because `contentType` is knowable in
    advance: a page that is not `canvas` is refused immediately, naming the
    content type found, rather than discovered only after a kickoff, a poll
    and a failed export. The same read's `updatedAt` is the cache key's
    other half, so an unchanged page never pays for a second export.

    That read also answers the page's canonical `id`, and the cache key and
    the gate key are both resolved to it rather than to whatever string the
    caller used. A page is addressed as `pageIdOrName`, so a caller that
    names one is doing the ordinary thing, and two callers naming one page
    differently must still meet: keyed on the raw argument they take
    different per-page gate slots and export at once, contending for the one
    blob the gate exists to serialise, and they leave the cache holding two
    entries for one page — which serves the wrong page's HTML as soon as a
    name is moved to a different page that shares an `updatedAt`. This is
    the pre-write guard's bug from the other side: `tools/guard.py` matches
    a page reference on its name as well as its id; here the name is
    resolved to the id.

    The export itself runs inside `gate.for_page(...)`: exports of one page
    are serialised because the blob they render into is keyed by page and
    document, not by request id, so two concurrent exports of the same page
    would contend for one blob rather than run independently.
    """
    deadline = Deadline(clock=clock)
    page = await api.get_page(page_id_or_name, deadline)
    content_type = page.get("contentType")
    if content_type != _EXPORTABLE_CONTENT_TYPE:
        # An absent field and a field holding a type this tool refuses are
        # different findings, and this sentence reaches the model verbatim.
        # "has contentType None" reads as a verdict about the page.
        found = (
            f"has contentType {content_type!r}"
            if content_type is not None
            else "did not report a contentType"
        )
        raise ClientError(
            f"page {page_id_or_name!r} {found}, so it cannot be exported — "
            "only canvas pages can be read this way."
        )

    updated_at = page.get("updatedAt")
    page_id = page.get("id") or page_id_or_name
    cached = cache.get(page_id, updated_at)
    if cached is not None:
        return {"html": cached}

    async with gate.for_page(page_id, deadline):
        # Looked up again now the gate is held, because the wait is exactly
        # when another reader of this page finishes and caches its render.
        # `updated_at` was read before the gate and is the same key it was
        # then, so a hit here is this page's current content. Without this
        # second look the waiting reader re-exports what it was waiting for
        # — and can fail doing it, since it acquires with less budget left
        # and its export ceiling is clamped to what remains, so it reports
        # a missed export deadline while the HTML sits in the cache.
        cached = cache.get(page_id, updated_at)
        if cached is not None:
            return {"html": cached}
        html = await export_page(
            api,
            downloader,
            page_id_or_name,
            _READ_PAGE_OUTPUT_FORMAT,
            deadline,
            clock=clock,
            sleep=sleep,
        )
        # Inside the gate, so the render is visible to the next reader the
        # moment the slot it is waiting for is released.
        cache.set(page_id, updated_at, html)
    return {"html": html}


def register_read_tools(
    server: MCPServer,
    api: DocsApi,
    columns: ColumnCache,
    downloader: Downloader,
    gate: ExportGate,
    pages: PageCache,
) -> None:
    """Register the always-on read tools on `server`, closing over `api`.

    The registered tool cannot take `api` as a model-visible parameter, so
    each one here is a thin wrapper that closes over the single `DocsApi`
    instance passed in and delegates to the directly-testable function above.
    `columns` is constructed once in `build_server` and passed in, rather
    than built here, so the write tools this server also registers resolve
    columns through the same `ColumnCache` — two copies would disagree after
    the first write, which is exactly the case `schema_cache.py` warns
    about. `downloader`, `gate` and `pages` are constructed the same way, in
    `build_server`, for the same reason: `read_page` is the only tool that
    uses them, but a `ColumnCache`-per-call mistake and an `ExportGate`-per-
    call mistake are the same bug, and `server.py`'s docstring says why one
    of each must serve the whole server.

    Parameter names distinguish the two caches on purpose: `columns` for the
    `ColumnCache` this function shares with `register_write_tools`, `pages`
    for the page-content `PageCache` `read_page` alone uses. A signature
    with two params both called `cache` is exactly the kind of ambiguity
    that gets one passed where the other belongs.
    """

    @server.tool(name="outline_page", description=_OUTLINE_PAGE_DESCRIPTION)
    @tool_boundary
    async def outline_page_tool(page_id_or_name: str) -> list[dict]:
        return await outline_page(api, page_id_or_name)

    @server.tool(name="describe_table", description=_DESCRIBE_TABLE_DESCRIPTION)
    @tool_boundary
    async def describe_table_tool(table_id_or_name: str) -> list[dict]:
        return await describe_table(columns, table_id_or_name)

    @server.tool(
        name="get_doc_overview", description=_GET_DOC_OVERVIEW_DESCRIPTION
    )
    @tool_boundary
    async def get_doc_overview_tool() -> dict:
        return await get_doc_overview(api, columns)

    @server.tool(name="get_row", description=_GET_ROW_DESCRIPTION)
    @tool_boundary
    async def get_row_tool(table_id_or_name: str, row_id: str) -> dict:
        return await get_row(api, columns, table_id_or_name, row_id)

    @server.tool(name="find_rows", description=_FIND_ROWS_DESCRIPTION)
    @tool_boundary
    async def find_rows_tool(
        table_id_or_name: str,
        filters: dict[str, object] | None = None,
        sort: str | None = None,
        limit: int = 200,
    ) -> dict:
        return await find_rows(
            api, columns, table_id_or_name, filters=filters, sort=sort, limit=limit
        )

    @server.tool(name="read_page", description=_READ_PAGE_DESCRIPTION)
    @tool_boundary
    async def read_page_tool(page_id_or_name: str) -> dict:
        return await read_page(api, downloader, gate, pages, page_id_or_name)
