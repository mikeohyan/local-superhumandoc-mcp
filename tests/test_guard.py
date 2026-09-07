"""The pre-write guard: what a page owns that its own outline cannot see.

`objects_owned_by_page` is what the six gated tools of tools/writes.py check
before a destructive page operation runs. These tests exercise it directly
against fakes shaped like the three listings it reads — `list_tables`,
`list_controls`, `list_formulas` — because the guard's own contract (all
three kinds, matched on the parent's id or its name) is what breaks silently
if it drifts,
not the write tools built on top of it.
"""

import pytest

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.tools.guard import objects_owned_by_page


class _ListingApi:
    """A fake exposing only the three listings the guard reads. Each keyword
    defaults to no objects of that kind, so a test that cares about only one
    kind does not have to spell out the other two as empty lists."""

    def __init__(
        self,
        *,
        tables: list[dict] | None = None,
        controls: list[dict] | None = None,
        formulas: list[dict] | None = None,
    ) -> None:
        self._tables = tables or []
        self._controls = controls or []
        self._formulas = formulas or []

    async def list_tables(self, deadline: Deadline) -> list[dict]:
        return self._tables

    async def list_controls(self, deadline: Deadline) -> list[dict]:
        return self._controls

    async def list_formulas(self, deadline: Deadline) -> list[dict]:
        return self._formulas


def _owned_by(identifier: str, page_id: str) -> dict:
    return {"id": identifier, "parent": {"id": page_id}}


def _api_with_hidden_table() -> _ListingApi:
    """A table written as page content, invisible to listPageContent — the
    exact case the guard exists for."""
    return _ListingApi(tables=[_owned_by("grid-hidden", "page-x")])


def _api_owning(kind: str, identifier: str) -> _ListingApi:
    return _ListingApi(**{kind: [_owned_by(identifier, "page-x")]})


def _api_owned_by(other_page: str) -> _ListingApi:
    return _ListingApi(tables=[_owned_by("grid-1", other_page)])


async def test_the_guard_finds_objects_the_page_outline_cannot_see():
    """A table written as page content never appears in listPageContent. The
    guard reads listTables, so it sees what the outline misses."""
    found = await objects_owned_by_page(_api_with_hidden_table(), "page-x")
    assert found["tables"] == ["grid-hidden"]


@pytest.mark.parametrize(
    "kind,identifier",
    [("tables", "grid-1"), ("controls", "ctrl-1"), ("formulas", "f-1")],
)
async def test_the_guard_checks_all_three_object_kinds(kind, identifier):
    """All three schemas carry a `parent` reference, which is what makes the
    check possible at all. Checking only tables would leave two thirds of
    the rule unenforced."""
    found = await objects_owned_by_page(_api_owning(kind, identifier), "page-x")
    assert found[kind] == [identifier]


async def test_objects_belonging_to_another_page_are_not_counted():
    """The filter is `parent.id == pageId`, not "this document owns it
    somewhere" — an object on a different page must not trip the guard."""
    found = await objects_owned_by_page(_api_owned_by("other-page"), "page-x")
    assert found == {"tables": [], "controls": [], "formulas": []}


async def test_a_page_named_rather_than_identified_is_still_guarded():
    """Every tool on this surface takes `page_id_or_name`, so a model that
    names a page is doing the ordinary thing — outline_page invites it.

    Matching only the parent's id would compare an id against a name, find
    nothing, and report the page as owning nothing: a guard answering "all
    clear" for the exact reason it was consulted, letting a destructive write
    through onto a page with a table on it. A `PageReference` carries both
    fields, measured 2026-09-07 as `{id, type, href, browserLink, name}`, so
    both are checked. Every other test here identifies the page by id, which
    is why none of them would catch this.
    """
    api = _ListingApi(
        tables=[
            {
                "id": "grid-hidden",
                "parent": {"id": "canvas-VTK4j7fF0-", "name": "Quarterly plan"},
            }
        ]
    )

    assert (await objects_owned_by_page(api, "Quarterly plan"))["tables"] == [
        "grid-hidden"
    ]
    assert (await objects_owned_by_page(api, "canvas-VTK4j7fF0-"))["tables"] == [
        "grid-hidden"
    ]
    assert (await objects_owned_by_page(api, "Some other page"))["tables"] == []

