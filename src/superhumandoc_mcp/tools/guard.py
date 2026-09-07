"""The pre-write guard that runs before a destructive page operation.

A table, control or formula chip written as page content never appears in
`listPageContent` (docs/reference/api-operational-constants.md's endpoint
inventory records this). `outline_page` is built on `listPageContent`, so it
inherits that blind spot: a page that reads as empty to it can still own
objects a destructive page write would silently take out. This module is the
mechanism that closes that gap. It reads the three listings that *can* see
such objects — `listTables`, `listControls`, `listFormulas` — and reports
which of them belong to one page.

The check is possible at all only because `Table`, `Control` and `Formula`
all carry a `parent: PageReference`. Filtering on `tables` alone would leave
two thirds of the rule unenforced.
"""

import time
from collections.abc import Callable

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.deadline import Deadline


async def objects_owned_by_page(
    api: DocsApi,
    page_id_or_name: str,
    *,
    deadline: Deadline | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, list[str]]:
    """The tables, controls and formulas this page owns.

    Always returns all three keys — `tables`, `controls`, `formulas` — each
    an id list, empty when the page owns nothing of that kind. A caller
    never has to test for a missing key the way it would if an empty kind
    were left out of the result.

    `deadline` is accepted directly, the same way `upsert_rows` in
    `tools/writes.py` accepts one, so a gated tool can run this check against
    its own tool-call budget rather than the guard opening a second one. A
    caller with no deadline of its own — a test, in practice — gets one built
    from `clock`.
    """
    deadline = deadline if deadline is not None else Deadline(clock=clock)
    tables = await api.list_tables(deadline)
    controls = await api.list_controls(deadline)
    formulas = await api.list_formulas(deadline)
    return {
        "tables": _owned_by(tables, page_id_or_name),
        "controls": _owned_by(controls, page_id_or_name),
        "formulas": _owned_by(formulas, page_id_or_name),
    }


def _owned_by(objects: list[dict], page_id_or_name: str) -> list[str]:
    """Match the page reference on its id *or* its name.

    Every tool on this surface takes `page_id_or_name`, so a model that names
    a page rather than identifying it is doing the ordinary thing. Matching
    only `parent.id` would then compare an id against a name, find nothing,
    and report a page as owning no objects — a guard that answers "all clear"
    for the exact reason it was consulted, and the failure it exists to
    prevent. A `PageReference` carries both fields (measured 2026-09-07:
    `{id, type, href, browserLink, name}`), so both are checked.
    """
    matched = []
    for obj in objects:
        parent = obj.get("parent") or {}
        if page_id_or_name in (parent.get("id"), parent.get("name")):
            matched.append(obj["id"])
    return matched
