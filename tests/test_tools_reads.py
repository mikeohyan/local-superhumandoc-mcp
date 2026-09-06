"""The always-on read tools: thin translations between the model's
vocabulary and `api.py`, wrapped by `tool_boundary` and registered by
`register_read_tools`.
"""

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.tools.reads import (
    OVERVIEW_INLINE_COLUMNS_MAX_TABLES,
    describe_table,
    get_doc_overview,
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
