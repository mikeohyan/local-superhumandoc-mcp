"""The always-on read tools: thin translations between the model's
vocabulary and `api.py`, wrapped by `tool_boundary` and registered by
`register_read_tools`.
"""

import asyncio
from contextlib import asynccontextmanager

import pytest
from mcp import Client

from superhumandoc_mcp.api import Listing
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ClientError
from superhumandoc_mcp.gate import ExportGate
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.server import build_server
from superhumandoc_mcp.tools.reads import (
    OVERVIEW_INLINE_COLUMNS_MAX_TABLES,
    PageCache,
    describe_table,
    find_rows,
    get_doc_overview,
    get_row,
    outline_page,
    read_page,
)
from tests.conftest import (
    _Downloads,
    _config,
    _counting_downloader,
    _fixed_downloader,
    _fixtures,
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
                    "content": "Title",
                },
            },
            {
                "id": "el-2",
                "itemContent": {
                    "style": "paragraph",
                    "lineLevel": 0,
                    "content": "Body",
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
                "itemContent": {"style": "paragraph", "lineLevel": 2, "content": "x"},
            }
        ]
    )
    lines = await outline_page(api, "page-x")
    assert lines[0]["style"] == "paragraph"
    assert lines[0]["level"] == 2


async def test_a_line_reads_its_text_from_content_and_there_is_no_text_key():
    """The item shape observed live carries the line's text under
    `itemContent.content`; no `itemContent.text` key exists at all. Reading
    the wrong one is silent — every line comes back with an empty string,
    which is a plausible value for a blank line — so the item here is a
    verbatim copy of one the API actually returned, with a decoy `text`
    alongside it to pin which key wins."""
    api = _FakeApi(
        [
            {
                "id": "cl-RVeKFUvHVD",
                "type": "line",
                "itemContent": {
                    "style": "paragraph",
                    "format": "plainText",
                    "content": "ALPHA one",
                    "text": "WRONG",
                    "lineLevel": 0,
                },
            }
        ]
    )
    lines = await outline_page(api, "page-x")
    assert lines[0]["text"] == "ALPHA one"


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


# --- read_page -----------------------------------------------------------


_PAGE_ID = "canvas-Ah3k1FvQ2-"
_STAMP = "2026-09-07T10:00:00Z"


class _PageApi:
    """Stands in for `DocsApi` for `read_page`: answers `get_page` with a
    fixed `id`/`contentType`/`updatedAt`, and completes exactly one export
    via `begin_export`/`get_export_status` — a single poll that always comes
    back terminal. The poll loop itself is `export.py`'s own concern,
    exercised on its own terms in tests/test_export.py; what these tests pin
    is what `read_page` does around it — the content-type gate, the cache,
    and entering the gate — not the loop's shape.

    `id` is answered because the real `getPage` body carries it and
    `read_page` keys the cache and the gate on it. A double that omitted it
    would let a `read_page` keyed on the caller's raw string pass every test
    here, which is exactly how that shipped.

    `error` turns the single poll terminal-with-a-failure instead, which is
    how a failed render is spelled to `export.py`; `export_formats` records
    what each kickoff was asked for, because nothing else pins the format
    the tool actually sends.

    `export_pages` and `status_pages` record the page each hop was addressed
    to. Both endpoints are page-scoped -- the kickoff is
    `POST /docs/{doc}/pages/{page}/export` and the status `GET` repeats the
    same `{page}` -- so a double that ignored its `page` argument would let a
    `read_page` that resolves the id for its keys and then exports the
    caller's raw string pass every other test here, which is exactly how that
    shipped.
    """

    def __init__(
        self,
        *,
        content_type: str,
        updated_at: str | None = None,
        page_id: str = _PAGE_ID,
        error: str | None = None,
    ) -> None:
        self.content_type = content_type
        self.updated_at = updated_at
        self.page_id = page_id
        self.error = error
        self.export_formats: list[str] = []
        self.export_pages: list[str] = []
        self.status_pages: list[str] = []
        self._next_id = 0

    async def get_page(self, page: str, deadline: Deadline) -> dict:
        return {
            "id": self.page_id,
            "contentType": self.content_type,
            "updatedAt": self.updated_at,
        }

    async def begin_export(self, page: str, output_format: str, deadline: Deadline) -> dict:
        self.export_formats.append(output_format)
        self.export_pages.append(page)
        self._next_id += 1
        return {"id": f"export-{self._next_id}"}

    async def get_export_status(
        self, page: str, request_id: str, deadline: Deadline
    ) -> dict:
        self.status_pages.append(page)
        if self.error is not None:
            return {"error": self.error}
        return {"downloadLink": f"https://example.test/{page}/{request_id}"}


class _BlockingPageApi(_PageApi):
    """A `_PageApi` whose export parks until `release` is set, so a second
    reader is guaranteed to be waiting on the gate while the first is still
    inside it. Starting two tasks and hoping would pass whether or not the
    second one re-checked the cache."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.inside = asyncio.Event()
        self.release = asyncio.Event()

    async def begin_export(self, page: str, output_format: str, deadline: Deadline) -> dict:
        self.inside.set()
        await self.release.wait()
        return await super().begin_export(page, output_format, deadline)


async def _settle() -> None:
    """Let every runnable task reach its next real suspension point.

    The fake `sleep` from `_fixtures` advances a counter and never yields, so
    a test that needs one task to be *blocked on the gate* rather than merely
    created has to hand the loop back explicitly.
    """
    for _ in range(20):
        await asyncio.sleep(0)


class _RecordingGate:
    """Stands in for `ExportGate`: records the page id `for_page` is entered
    with, rather than actually serialising anything, so a test can pin that
    `read_page` enters the gate rather than merely accepting one and never
    using it."""

    def __init__(self) -> None:
        self.entered: list[str] = []

    @asynccontextmanager
    async def for_page(self, page_id: str, deadline: Deadline):
        self.entered.append(page_id)
        yield


async def test_read_page_returns_the_page_as_html():
    clock, _, sleep = _fixtures()
    result = await read_page(
        _PageApi(content_type="canvas"),
        _fixed_downloader("<h1>Hi</h1>"),
        ExportGate(),
        PageCache(),
        "page-x",
        clock=clock,
        sleep=sleep,
    )
    assert result["html"] == "<h1>Hi</h1>"


@pytest.mark.parametrize("content_type", ["syncPage", "embed"])
async def test_a_page_that_cannot_be_exported_is_refused_by_its_type(content_type):
    """The type is readable in advance, so this costs one cheap read rather
    than a kickoff, a poll and a 400. The message names the type, because
    "export failed" gives a model nothing to do differently."""
    clock, _, sleep = _fixtures()
    with pytest.raises(ClientError) as caught:
        await read_page(
            _PageApi(content_type=content_type),
            _fixed_downloader("x"),
            ExportGate(),
            PageCache(),
            "page-x",
            clock=clock,
            sleep=sleep,
        )
    assert content_type in str(caught.value)


async def test_an_unchanged_page_is_not_exported_twice():
    """Export is the most expensive thing on this surface. The cache is keyed
    on the page and its updatedAt, so a second read of an unchanged page costs
    one cheap page read."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas", updated_at="2026-09-07T10:00:00Z")
    cache, downloader = PageCache(), _counting_downloader("<p>x</p>")
    for _ in range(2):
        await read_page(
            api, downloader, ExportGate(), cache, "page-x", clock=clock, sleep=sleep
        )
    assert downloader.calls == 1


async def test_a_changed_page_is_exported_again():
    """Serving a stale render after an edit is worse than the cost the cache
    saves -- it would report the document as it was and give no sign of it."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas", updated_at="2026-09-07T10:00:00Z")
    cache, downloader = PageCache(), _counting_downloader("<p>x</p>")
    await read_page(
        api, downloader, ExportGate(), cache, "page-x", clock=clock, sleep=sleep
    )
    api.updated_at = "2026-09-07T11:00:00Z"
    await read_page(
        api, downloader, ExportGate(), cache, "page-x", clock=clock, sleep=sleep
    )
    assert downloader.calls == 2


async def test_two_pages_sharing_a_timestamp_do_not_share_a_render():
    """The cache key is the page *and* the timestamp. Keyed on the timestamp
    alone -- a fair reading of "cached against updatedAt" -- this returns page
    A's HTML for page B, which is silent wrong-page content and the worst thing
    this tool could do. Two pages sharing an updatedAt is ordinary after a bulk
    edit or a duplicated template. The two pages differ by their canonical
    id, which is what the key is built from -- the names they are read by
    are incidental and would not distinguish them if the key were the
    caller's string."""
    clock, _, sleep = _fixtures()
    stamp = "2026-09-07T10:00:00Z"
    cache = PageCache()
    a = await read_page(
        _PageApi(content_type="canvas", updated_at=stamp, page_id="canvas-aaa"),
        _fixed_downloader("<p>A</p>"),
        ExportGate(),
        cache,
        "page-a",
        clock=clock,
        sleep=sleep,
    )
    b = await read_page(
        _PageApi(content_type="canvas", updated_at=stamp, page_id="canvas-bbb"),
        _fixed_downloader("<p>B</p>"),
        ExportGate(),
        cache,
        "page-b",
        clock=clock,
        sleep=sleep,
    )
    assert (a["html"], b["html"]) == ("<p>A</p>", "<p>B</p>")


async def test_a_page_with_no_timestamp_is_not_cached():
    """A render that cannot be invalidated is worse than one that costs
    something. With no updatedAt there is nothing to compare against, so the
    only safe answer is to export again."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas", updated_at=None)
    cache, downloader = PageCache(), _counting_downloader("<p>x</p>")
    for _ in range(2):
        await read_page(
            api, downloader, ExportGate(), cache, "page-x", clock=clock, sleep=sleep
        )
    assert downloader.calls == 2


async def test_the_export_runs_inside_the_gate():
    """`read_page` takes a gate because per-page serialisation is a correctness
    constraint, not pacing -- two concurrent exports of one page contend for a
    single blob. A read_page that accepted the gate and forgot to enter it would
    pass every other test here."""
    clock, _, sleep = _fixtures()
    gate = _RecordingGate()
    await read_page(
        _PageApi(content_type="canvas"),
        _fixed_downloader("x"),
        gate,
        PageCache(),
        "page-x",
        clock=clock,
        sleep=sleep,
    )
    assert gate.entered == [_PAGE_ID]


async def test_the_gate_and_the_cache_are_keyed_on_the_canonical_page_id():
    """A page is addressed as `pageIdOrName`, so a caller that names a page is
    doing the ordinary thing — and two callers naming one page differently
    must still meet. Keyed on the caller's raw string, a read by id and a
    read by name take *different* per-page gate slots and both export at
    once, contending for the one `DOC_EXPORT_RENDERING/{pageId}/{docId}` blob
    the gate exists to protect, and they leave two cache entries for one
    page. `getPage` answers the canonical id, so both keys resolve to it.
    This is the same fix the pre-write guard already shipped, from the other
    side: there a page reference was matched on its name as well as its id,
    here the name is resolved to the id."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas", updated_at=_STAMP)
    gate, cache = _RecordingGate(), PageCache()
    downloader = _counting_downloader("<p>x</p>")
    for named in (_PAGE_ID, "Q3 Plan"):
        await read_page(
            api, downloader, gate, cache, named, clock=clock, sleep=sleep
        )
    assert gate.entered == [_PAGE_ID]
    assert downloader.calls == 1
    assert len(cache) == 1


async def test_a_read_by_id_and_a_read_by_name_take_the_same_gate_slot():
    """The gate half of the same defect, with the cache taken out of it: a
    page with no `updatedAt` is never cached, so both reads reach the gate
    and the only thing that can make them agree is the key."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas", updated_at=None)
    gate = _RecordingGate()
    for named in (_PAGE_ID, "Q3 Plan"):
        await read_page(
            api, _fixed_downloader("x"), gate, PageCache(), named,
            clock=clock, sleep=sleep,
        )
    assert gate.entered == [_PAGE_ID, _PAGE_ID]


async def test_a_name_moved_to_another_page_does_not_serve_the_first_ones_html():
    """Read page A as "Q3 Plan", rename A away, rename B to "Q3 Plan". If B
    shares A's `updatedAt` — ordinary after a bulk edit or a duplicated
    template — a cache keyed on the caller's string returns A's HTML for B,
    silently. Keyed on the canonical id it cannot."""
    clock, _, sleep = _fixtures()
    cache = PageCache()
    rendered = []
    for page_id, html in (("canvas-aaa", "<p>A</p>"), ("canvas-bbb", "<p>B</p>")):
        result = await read_page(
            _PageApi(content_type="canvas", updated_at=_STAMP, page_id=page_id),
            _fixed_downloader(html),
            ExportGate(),
            cache,
            "Q3 Plan",
            clock=clock,
            sleep=sleep,
        )
        rendered.append(result["html"])
    assert rendered == ["<p>A</p>", "<p>B</p>"]


async def test_the_export_itself_is_requested_against_the_canonical_page_id():
    """Resolving the id for the cache key and the gate key, and then exporting
    the caller's raw string, closes nothing: the render that comes back is
    whatever that string names *now*, and it is stored under the id resolved
    a moment earlier. Both hops are page-scoped -- the kickoff
    `POST /docs/{doc}/pages/{page}/export` and the status `GET` that repeats
    the same `{page}` -- so both have to be addressed to the id, or a rename
    mid-export also sends every poll to the wrong page."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas", updated_at=_STAMP)
    await read_page(
        api, _fixed_downloader("x"), ExportGate(), PageCache(), "Q3 Plan",
        clock=clock, sleep=sleep,
    )
    assert api.export_pages == [_PAGE_ID]
    assert api.status_pages == [_PAGE_ID]


async def test_a_name_moved_between_the_lookup_and_the_export_cannot_be_cached():
    """The window the id keys were meant to close, stated as content rather
    than as a key.

    `getPage("Q3 Plan")` resolves page A; the name is then moved to page B.
    An export addressed to the caller's string renders B, and the result is
    filed under A's id and A's `updatedAt` -- so the next read of A, unchanged,
    is served B's HTML with nothing anywhere to say so. Addressed to the id,
    the export can only render A. The two renders are told apart by the
    download URL, which carries the page the status hop was asked about."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas", updated_at=_STAMP, page_id="canvas-aaa")
    downloader = _Downloads(
        bodies={
            "https://example.test/canvas-aaa/export-1": "<p>A</p>",
            "https://example.test/Q3 Plan/export-1": "<p>B</p>",
        },
        default="<p>some other page entirely</p>",
    )
    cache = PageCache()
    result = await read_page(
        api, downloader, ExportGate(), cache, "Q3 Plan", clock=clock, sleep=sleep
    )
    assert result["html"] == "<p>A</p>"
    assert cache.get("canvas-aaa", _STAMP) == "<p>A</p>"


async def test_a_failed_export_still_names_the_page_the_caller_asked_for():
    """Addressing the export by id must not cost the caller the word it used.
    `export.py` names the page it was handed, which is now an id the model may
    never have seen; a model that asked for "Q3 Plan" has to be able to tell
    that this failure is about the page it asked for."""
    clock, _, sleep = _fixtures()
    with pytest.raises(ClientError) as caught:
        await read_page(
            _PageApi(content_type="canvas", updated_at=_STAMP, error="render blew up"),
            _fixed_downloader("x"),
            ExportGate(),
            PageCache(),
            "Q3 Plan",
            clock=clock,
            sleep=sleep,
        )
    message = str(caught.value)
    assert "render blew up" in message
    assert "Q3 Plan" in message


async def test_a_page_that_reports_no_id_is_not_cached():
    """`page.get("id") or page_id_or_name` is a fair enough gate key -- the
    worst it costs is a serialisation two readers did not need. As a *cache*
    key it is the wrong-page bug again: two pages that both omit `id`, read
    under one name and sharing a stamp, are one entry, and the second read is
    served the first's HTML. A page with no id is not cached at all, the same
    way a page with no `updatedAt` is not."""
    clock, _, sleep = _fixtures()
    cache = PageCache()
    rendered = []
    for html in ("<p>A</p>", "<p>B</p>"):
        result = await read_page(
            _PageApi(content_type="canvas", updated_at=_STAMP, page_id=None),
            _fixed_downloader(html),
            ExportGate(),
            cache,
            "Q3 Plan",
            clock=clock,
            sleep=sleep,
        )
        rendered.append(result["html"])
    assert rendered == ["<p>A</p>", "<p>B</p>"]
    assert len(cache) == 0


def test_an_empty_timestamp_is_not_a_cache_key_either():
    """`updated_at is None` lets `""` through, and an empty string is a key
    that never changes -- so the entry it files can never be invalidated and
    the page is answered from it for the life of the process. The docstring
    says "missing"; falsiness is what that means, and it matches the `or` on
    the id beside it."""
    cache = PageCache()
    cache.set("canvas-aaa", "", "<p>x</p>")
    assert cache.get("canvas-aaa", "") is None
    assert len(cache) == 0


@pytest.mark.parametrize(
    "page_id, updated_at, keyable",
    [
        ("canvas-aaa", _STAMP, True),
        (None, _STAMP, False),
        ("", _STAMP, False),
        ("canvas-aaa", None, False),
        ("canvas-aaa", "", False),
    ],
)
def test_what_counts_as_a_cache_key_is_asked_once_and_answered_the_same_way(
    page_id, updated_at, keyable
):
    """`get` and `set` share one predicate, so this pins it once instead of
    twice. Testing it only through the pair hides half of it: `set` refuses
    an unusable key, so nothing is ever filed under one, so `get`'s own guard
    is unreachable through the pair and can be loosened back to `is None`
    with the suite still green. Sharing the predicate is what makes that
    loosening a single edit, and this is what fails on it."""
    assert PageCache.is_keyable(page_id, updated_at) is keyable


async def test_a_page_reporting_an_empty_timestamp_is_exported_every_time():
    """The same fact where it bites: an empty `updatedAt` cannot be compared
    against a later one, so a render filed under it would be served forever."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas", updated_at="")
    cache, downloader = PageCache(), _counting_downloader("<p>x</p>")
    for _ in range(2):
        await read_page(
            api, downloader, ExportGate(), cache, _PAGE_ID, clock=clock, sleep=sleep
        )
    assert downloader.calls == 2
    assert len(cache) == 0


async def test_a_reader_that_waited_on_the_gate_takes_the_render_it_waited_for():
    """The cache is checked again after the gate is acquired, not only before
    it. Both readers miss on the way in; the second one blocks, and by the
    time it acquires, the first has already cached the very render it wants.
    Exporting again is not merely wasteful — the second reader arrives with
    less budget left, its export ceiling is clamped to what remains, and it
    can fail with "did not complete within the export deadline" while the
    HTML it asked for is sitting in the cache. `updatedAt` was read before
    the gate and does not change while the reader waits, so the second look
    uses the same key as the first.

    The join is bounded by `asyncio.wait_for`, the way every re-entry in
    tests/test_gate.py already is. This is the one test in this module that
    puts two tasks through a real `ExportGate`, so a lock that is acquired
    and never released wedges it — and a bare `gather` waits for that
    forever, which is a suite that hangs rather than a suite that fails."""
    clock, _, sleep = _fixtures()
    api = _BlockingPageApi(content_type="canvas", updated_at=_STAMP)
    gate, cache = ExportGate(), PageCache()
    downloader = _counting_downloader("<p>x</p>")

    def start():
        return asyncio.create_task(
            read_page(api, downloader, gate, cache, _PAGE_ID, clock=clock, sleep=sleep)
        )

    first = start()
    await api.inside.wait()
    second = start()
    await _settle()
    api.release.set()
    a, b = await asyncio.wait_for(asyncio.gather(first, second), timeout=5.0)
    assert downloader.calls == 1
    assert a["html"] == b["html"] == "<p>x</p>"


async def test_read_page_exports_html_not_markdown():
    """The two formats are not interchangeable: markdown drops the
    page-level attachments HTML retains
    (docs/reference/api-operational-constants.md §2.5), and the tool's
    description promises HTML. Nothing else in this suite reads the format
    the kickoff is handed, so flipping the constant would ship a fidelity
    regression with everything green."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas")
    await read_page(
        api, _fixed_downloader("x"), ExportGate(), PageCache(), _PAGE_ID,
        clock=clock, sleep=sleep,
    )
    assert api.export_formats == ["html"]


async def test_a_failed_export_reaches_the_caller_as_its_own_message():
    """`export_page` raises `ClientError` on a terminal `error`, and
    `read_page` is the only thing between that and the model. Swallowing it
    into an empty render, or letting some other exception out, both end as
    the SDK's redacted "Error executing tool read_page"."""
    clock, _, sleep = _fixtures()
    with pytest.raises(ClientError) as caught:
        await read_page(
            _PageApi(content_type="canvas", updated_at=_STAMP, error="render blew up"),
            _fixed_downloader("x"),
            ExportGate(),
            PageCache(),
            _PAGE_ID,
            clock=clock,
            sleep=sleep,
        )
    assert "render blew up" in str(caught.value)


async def test_a_failed_render_is_not_cached():
    """Nothing is stored for an export that never produced content, so the
    next read tries again rather than being told forever that a page it
    could render cannot be rendered."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas", updated_at=_STAMP, error="render blew up")
    cache, downloader = PageCache(), _counting_downloader("<p>x</p>")
    with pytest.raises(ClientError):
        await read_page(
            api, downloader, ExportGate(), cache, _PAGE_ID, clock=clock, sleep=sleep
        )
    assert len(cache) == 0
    api.error = None
    result = await read_page(
        api, downloader, ExportGate(), cache, _PAGE_ID, clock=clock, sleep=sleep
    )
    assert result["html"] == "<p>x</p>"


async def test_a_page_read_over_and_over_holds_one_cache_entry():
    """`ExportGate._per_page` plateaus at the document's page count because a
    page is one key. A cache keyed on the page *and* its `updatedAt` does
    not: every edit-then-read adds a permanent entry holding a whole HTML
    render, and nothing ever asks for a superseded timestamp again. One slot
    per page bounds it and loses nothing."""
    clock, _, sleep = _fixtures()
    api = _PageApi(content_type="canvas")
    cache = PageCache()
    for hour in range(6):
        api.updated_at = f"2026-09-07T1{hour}:00:00Z"
        await read_page(
            api, _fixed_downloader(f"<p>{hour}</p>"), ExportGate(), cache, _PAGE_ID,
            clock=clock, sleep=sleep,
        )
    assert len(cache) == 1


def test_a_superseded_timestamp_still_misses():
    """Bounding the cache must not cost the key its meaning: one slot per
    page replaces the entry, it does not stop comparing the timestamp. A
    `get` for the timestamp that was overwritten misses, exactly as it did
    when both stamps had their own entry."""
    cache = PageCache()
    cache.set("canvas-aaa", "t1", "<p>old</p>")
    cache.set("canvas-aaa", "t2", "<p>new</p>")
    assert cache.get("canvas-aaa", "t1") is None
    assert cache.get("canvas-aaa", "t2") == "<p>new</p>"


async def test_a_page_with_no_content_type_is_refused_without_a_verdict_on_its_type():
    """Failing closed is right; reporting an absent field as a definite
    finding is not. "has contentType None" reads as a statement about the
    page, and this string reaches the model verbatim."""
    clock, _, sleep = _fixtures()
    with pytest.raises(ClientError) as caught:
        await read_page(
            _PageApi(content_type=None),
            _fixed_downloader("x"),
            ExportGate(),
            PageCache(),
            _PAGE_ID,
            clock=clock,
            sleep=sleep,
        )
    message = str(caught.value)
    assert "None" not in message
    assert "did not report a contentType" in message


async def test_read_page_says_what_it_is_and_what_must_not_be_done_with_it():
    """The only enforcement the read-is-never-a-write-source rule has on the
    read side. Its sibling on the write side checks for a word tied to the
    clause it protects; checking only "projection" would pass a description
    that never mentions writing the output back at all."""
    async with Client(build_server(_config())) as client:
        tool = next(
            t for t in (await client.list_tools()).tools if t.name == "read_page"
        )
    lowered = tool.description.lower()
    assert "projection" in lowered
    assert "must not" in lowered
    assert "write" in lowered
    for construct in ("image", "table", "button", "control", "callout", "divider"):
        assert construct in lowered
