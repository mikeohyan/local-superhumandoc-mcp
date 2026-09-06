"""The always-on read tools: thin translations between the model's
vocabulary and `api.py`, wrapped by `tool_boundary` and registered by
`register_read_tools`.
"""

from superhumandoc_mcp.api import Listing
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.tools.reads import (
    OVERVIEW_INLINE_COLUMNS_MAX_TABLES,
    describe_table,
    find_rows,
    get_doc_overview,
    get_row,
    outline_page,
)


class _FakeApi:
    """Stands in for `DocsApi`: returns fixed `listPageContent` items without
    any HTTP, so these tests pin only what `outline_page` does with the
    shape it is handed."""

    def __init__(self, items: list[dict]) -> None:
        self._items = items
        self.calls: list[tuple[str, Deadline]] = []

    async def list_page_content(self, page: str, deadline: Deadline) -> list[dict]:
        self.calls.append((page, deadline))
        return self._items


async def test_outline_returns_lines_in_order_with_their_element_ids():
    """The outline preserves the API's own ordering and names every field the
    RFC promises, one entry per line."""
    api = _FakeApi(
        [
            {
                "id": "el-1",
                "itemContent": {
                    "style": "heading1",
                    "lineLevel": 0,
                    "text": "Title",
                },
            },
            {
                "id": "el-2",
                "itemContent": {
                    "style": "paragraph",
                    "lineLevel": 0,
                    "text": "Body",
                },
            },
        ]
    )
    lines = await outline_page(api, "page-x")
    assert lines == [
        {"element_id": "el-1", "style": "heading1", "level": 0, "text": "Title"},
        {"element_id": "el-2", "style": "paragraph", "level": 0, "text": "Body"},
    ]


async def test_style_and_level_are_read_from_item_content_not_the_top_level():
    """Probe P9: `style` and `lineLevel` are nested inside `itemContent`, not
    at the item's top level. A decoy top-level `style` pins that the nested
    one wins rather than being silently shadowed."""
    api = _FakeApi(
        [
            {
                "id": "el-1",
                "style": "WRONG",
                "itemContent": {"style": "paragraph", "lineLevel": 2, "text": "x"},
            }
        ]
    )
    lines = await outline_page(api, "page-x")
    assert lines[0]["style"] == "paragraph"
    assert lines[0]["level"] == 2


async def test_outline_page_asks_for_the_page_it_was_given():
    """The tool's only argument is the page identifier; it must reach the API
    call unchanged."""
    api = _FakeApi([])
    await outline_page(api, "page-x")
    assert api.calls[0][0] == "page-x"


class _FakeSchemaApi:
    """Stands in for `DocsApi` for `describe_table` and `get_doc_overview`:
    returns fixed pages, tables and per-table columns without any HTTP, and
    records the name of every operation it was asked to perform so a test can
    pin exactly how many times each one ran."""

    def __init__(
        self,
        *,
        pages: list[dict] | None = None,
        tables: list[dict] | None = None,
        columns_by_table: dict[str, list[dict]] | None = None,
    ) -> None:
        self._pages = pages if pages is not None else []
        self._tables = tables if tables is not None else []
        self._columns_by_table = columns_by_table or {}
        self.calls: list[str] = []

    async def list_pages(self, deadline: Deadline) -> list[dict]:
        self.calls.append("listPages")
        return self._pages

    async def list_tables(self, deadline: Deadline) -> list[dict]:
        self.calls.append("listTables")
        return self._tables

    async def list_columns(self, table: str, deadline: Deadline) -> list[dict]:
        self.calls.append("listColumns")
        return self._columns_by_table.get(table, [])


def _tables(count: int) -> list[dict]:
    return [{"id": f"t-{i}", "name": f"Table {i}"} for i in range(count)]


def _columns_for(tables: list[dict]) -> dict[str, list[dict]]:
    return {t["id"]: [{"id": f"{t['id']}-c1", "name": "Name"}] for t in tables}


async def test_describe_table_returns_that_tables_columns():
    tables = _tables(1)
    api = _FakeSchemaApi(tables=tables, columns_by_table=_columns_for(tables))
    cache = ColumnCache(api)
    columns = await describe_table(cache, "t-0")
    assert columns == [{"id": "t-0-c1", "name": "Name"}]


async def test_describe_table_warms_the_cache_the_row_tools_use():
    """Calling `describe_table` must warm the same `ColumnCache` the row
    tools read through, so a later call for the same table costs nothing."""
    tables = _tables(1)
    api = _FakeSchemaApi(tables=tables, columns_by_table=_columns_for(tables))
    cache = ColumnCache(api)
    await describe_table(cache, "t-0")
    await cache.columns("t-0", Deadline())
    assert api.calls.count("listColumns") == 1


async def test_eight_tables_get_their_columns_inline():
    """At or below the threshold, the overview is self-sufficient: a model
    orients without a second call."""
    tables = _tables(OVERVIEW_INLINE_COLUMNS_MAX_TABLES)
    api = _FakeSchemaApi(tables=tables, columns_by_table=_columns_for(tables))
    cache = ColumnCache(api)
    overview = await get_doc_overview(api, cache)
    assert len(overview["tables"]) == OVERVIEW_INLINE_COLUMNS_MAX_TABLES
    assert all("columns" in t for t in overview["tables"])
    assert "columns_omitted" not in overview


async def test_nine_tables_omit_columns_and_say_so():
    """The response must be self-describing: a model that cannot see the
    threshold must still learn what to call next."""
    tables = _tables(OVERVIEW_INLINE_COLUMNS_MAX_TABLES + 1)
    api = _FakeSchemaApi(tables=tables, columns_by_table=_columns_for(tables))
    cache = ColumnCache(api)
    overview = await get_doc_overview(api, cache)
    assert all("columns" not in t for t in overview["tables"])
    assert "describe_table" in overview["columns_omitted"]


async def test_the_overview_costs_one_column_lookup_per_table_at_most():
    tables = _tables(OVERVIEW_INLINE_COLUMNS_MAX_TABLES)
    api = _FakeSchemaApi(tables=tables, columns_by_table=_columns_for(tables))
    cache = ColumnCache(api)
    await get_doc_overview(api, cache)
    assert api.calls.count("listColumns") == OVERVIEW_INLINE_COLUMNS_MAX_TABLES


async def test_the_overview_makes_no_column_lookups_when_columns_are_omitted():
    tables = _tables(OVERVIEW_INLINE_COLUMNS_MAX_TABLES + 1)
    api = _FakeSchemaApi(tables=tables, columns_by_table=_columns_for(tables))
    cache = ColumnCache(api)
    await get_doc_overview(api, cache)
    assert api.calls.count("listColumns") == 0


async def test_get_doc_overview_returns_the_page_tree():
    pages = [{"id": "p-1", "name": "Intro"}]
    api = _FakeSchemaApi(pages=pages, tables=[])
    cache = ColumnCache(api)
    overview = await get_doc_overview(api, cache)
    assert overview["pages"] == pages


_NAME_COLUMN = {"id": "c-euWseAF6J-", "name": "Name"}
_AGE_COLUMN = {"id": "c-age456", "name": "Age"}
_STATUS_COLUMN = {"id": "c-status1", "name": "Status"}


class _FakeRowApi:
    """Stands in for `DocsApi` for `get_row` and `find_rows`: returns fixed
    rows and columns without any HTTP, and records what `list_rows` was
    called with so a test can pin what a listing pass asked for."""

    def __init__(
        self,
        *,
        rows: dict[str, dict] | None = None,
        columns: list[dict] | None = None,
        listed: list[dict] | None = None,
        complete: bool = True,
        stopped_because: str | None = None,
    ) -> None:
        self._rows = rows or {}
        self._columns = columns or []
        self._listed = listed if listed is not None else list(self._rows.values())
        self._complete = complete
        self._stopped_because = stopped_because
        self.list_rows_calls: list[dict] = []

    async def get_row(self, table: str, row_id: str, deadline: Deadline) -> dict:
        return self._rows[row_id]

    async def list_columns(self, table: str, deadline: Deadline) -> list[dict]:
        return self._columns

    async def list_rows(
        self,
        table: str,
        deadline: Deadline,
        *,
        limit: int,
        params: dict | None = None,
    ) -> Listing:
        self.list_rows_calls.append({"limit": limit, "params": params})
        return Listing(self._listed, self._complete, self._stopped_because)


async def test_cells_come_back_keyed_by_column_name():
    """The row endpoint keys `values` by column ID (real keys look like
    `c-euWseAF6J-`, docs/reference/api-operational-constants.md §6), which is
    not a key a model would recognise. get_row resolves it through the shared
    ColumnCache."""
    api = _FakeRowApi(
        rows={
            "i-1": {
                "id": "i-1",
                "values": {"c-euWseAF6J-": "Ada", "c-age456": 36},
            }
        },
        columns=[_NAME_COLUMN, _AGE_COLUMN],
    )
    cache = ColumnCache(api)
    row = await get_row(api, cache, "grid-x", "i-1")
    assert row["cells"] == {"Name": "Ada", "Age": 36}


async def test_the_row_id_is_always_returned_with_the_row():
    """Every later write addresses a row by this value."""
    api = _FakeRowApi(rows={"i-1": {"id": "i-1", "values": {}}}, columns=[])
    cache = ColumnCache(api)
    row = await get_row(api, cache, "grid-x", "i-1")
    assert row["row_id"] == "i-1"


async def test_a_column_id_the_schema_does_not_know_is_surfaced_not_dropped():
    """The schema may be stale or simply not carry an entry for some ID.
    Losing a cell silently is worse than surfacing it under a key a model
    does not recognise."""
    api = _FakeRowApi(
        rows={"i-1": {"id": "i-1", "values": {"c-unknown999": "mystery"}}},
        columns=[_NAME_COLUMN],
    )
    cache = ColumnCache(api)
    row = await get_row(api, cache, "grid-x", "i-1")
    assert row["cells"] == {"c-unknown999": "mystery"}


async def test_find_rows_returns_cells_keyed_by_name_and_the_row_id():
    api = _FakeRowApi(
        columns=[_NAME_COLUMN, _AGE_COLUMN],
        listed=[{"id": "i-1", "values": {"c-euWseAF6J-": "Ada", "c-age456": 36}}],
    )
    cache = ColumnCache(api)
    rows = (await find_rows(api, cache, "grid-x"))["rows"]
    assert rows == [{"row_id": "i-1", "cells": {"Name": "Ada", "Age": 36}}]


async def test_client_side_filtering_is_applied_after_paging():
    """Server-side filtering is one column and exact-value only; every
    filter — including the one condition offered to the server — is still
    checked here, so correctness never depends on the server having applied
    it."""
    api = _FakeRowApi(
        columns=[_NAME_COLUMN, _STATUS_COLUMN],
        listed=[
            {"id": "i-1", "values": {"c-status1": "open"}},
            {"id": "i-2", "values": {"c-status1": "closed"}},
        ],
    )
    cache = ColumnCache(api)
    rows = (await find_rows(
        api, cache, "grid-x", filters={"Status": "open"}, limit=200
    ))["rows"]
    assert len(rows) == 1
    assert all(r["cells"]["Status"] == "open" for r in rows)


async def test_find_rows_defaults_the_limit_to_two_hundred():
    api = _FakeRowApi(columns=[], listed=[])
    cache = ColumnCache(api)
    await find_rows(api, cache, "grid-x")
    assert api.list_rows_calls[0]["limit"] == 200


async def test_a_complete_listing_says_so_and_carries_no_note():
    """The shape does not vary with the outcome. A caller that has to test for
    a key's presence to learn whether it saw the whole table will eventually
    forget to."""
    api = _FakeRowApi(
        columns=[_NAME_COLUMN],
        listed=[{"id": "i-1", "values": {"c-euWseAF6J-": "Ada"}}],
    )
    result = await find_rows(api, ColumnCache(api), "grid-x")
    assert result["complete"] is True
    assert result["note"] is None


async def test_a_listing_the_deadline_cut_short_keeps_its_rows_and_says_so():
    """The `request-sizing` topic: rows from the pass the deadline cut short
    are kept and
    reported, and the tool says how far it got. find_rows pages up to the
    caller's cap, so returning fewer than that silently would present part of
    a table as the whole of it."""
    api = _FakeRowApi(
        columns=[_NAME_COLUMN],
        listed=[{"id": "i-1", "values": {"c-euWseAF6J-": "Ada"}}],
        complete=False,
        stopped_because="the tool call's deadline",
    )
    result = await find_rows(api, ColumnCache(api), "grid-x", limit=200)
    assert len(result["rows"]) == 1
    assert result["complete"] is False
    assert "deadline" in result["note"]
    assert "not all of it" in result["note"]
