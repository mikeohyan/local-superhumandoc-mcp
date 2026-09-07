"""Write tools: thin translations between the model's vocabulary and
`api.py`'s write methods, following the shape `tools/reads.py` sets.

Each tool function is directly testable without a server — it takes a
`DocsApi` as its first argument. `register_write_tools` is the seam that
closes each one over a single `DocsApi` instance (and, for the row writes a
later task adds to this same registrar, the one shared `ColumnCache`) and
puts it on the server, because the object the model calls cannot itself take
those as model-visible parameters.

Every write here polls its mutation to a settled outcome through
`await_mutation` before returning, and reports exactly what that poll found:
`applied` once the API confirms it, `unknown` — never `failed` — if the poll
gives up first. `polling.UNKNOWN` carries the sentence that an unknown write
may already have gone through, written once so no tool re-words it.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from mcp.server import MCPServer

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.content import canvas_content
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ContentRefused
from superhumandoc_mcp.polling import UNKNOWN, await_mutation
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.tools.boundary import tool_boundary

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


async def _report(
    api: DocsApi,
    response: dict,
    deadline: Deadline,
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]],
) -> dict:
    """Turn a write's 202 body into the outcome a model sees.

    Assumption 6 of the write wave: some 202s carry no `requestId` at all —
    `docs/reference/api-operational-constants.md` records which operations
    do this — and nothing can be polled without one. Left unhandled that is
    a `KeyError`, which `tool_boundary` deliberately does not translate, so
    a model would see "Error executing tool" for a write that may have
    succeeded. Reported as unknown instead, same as a poll that gives up.
    """
    request_id = response.get("requestId")
    if request_id is None:
        return {"outcome": "unknown", "detail": UNKNOWN, "warning": None}
    outcome = await await_mutation(api, request_id, deadline, clock=clock, sleep=sleep)
    return {
        "outcome": "applied" if outcome.applied else "unknown",
        "detail": outcome.detail,
        "warning": outcome.warning,
    }


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


def register_write_tools(server: MCPServer, api: DocsApi, cache: ColumnCache) -> None:
    """Register the always-on write tools on `server`, closing over `api`
    the same way `register_read_tools` closes over it for reads.

    `cache` is accepted here, even though none of this task's tools resolve
    a column against it, because the row writes a later task adds land in
    this same registrar and must share the one `ColumnCache` `build_server`
    constructs — `schema_cache.py` warns that the first write wave to touch
    it must invalidate it rather than let a read copy and a write copy
    disagree, and that only holds if there is one copy to begin with.
    """
    del cache  # unused until row writes join this registrar

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
