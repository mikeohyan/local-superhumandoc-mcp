"""The always-on page-write tools: create_page, append_to_page, rename_page,
and replace_element. Probe B6 confirmed `contentUpdate` can be scoped to a
single element (docs/reference/api-operational-constants.md), so
replace_element is built.

Each fake here answers `DocsApi` at the transport layer it actually talks to
— `request()` — rather than faking `DocsApi`'s own methods, so the real
body-construction logic in `api.py` (already covered by tests/test_api.py) is
exercised too, and a test that reads a call's `json` sees exactly what a real
write would send.
"""

import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ContentRefused
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.server import build_server
from superhumandoc_mcp.tools.boundary import tool_boundary
from superhumandoc_mcp.tools.writes import (
    append_to_page,
    clear_page_content,
    create_page,
    delete_element,
    delete_page,
    delete_rows,
    overwrite_page,
    push_button,
    rename_page,
    replace_element,
    update_row,
    upsert_rows,
)
from tests.conftest import (
    _CALCULATED_COLUMN,
    _GATED_NAMES,
    _NAME_COLUMN,
    _CONTENT_WRITE_NAMES,
    _config,
    _fixtures,
    _rows,
)


class _Response:
    """The only thing `DocsApi` does with what `request()` returns:
    `.json()`. Standing in for `httpx2.Response` here avoids needing real
    HTTP for a test that is about the tool layer, not the transport."""

    def __init__(self, body: dict) -> None:
        self._body = body

    def json(self) -> dict:
        return self._body


class _RecordingClient:
    """A `DocsClient`-shaped double: records every call `DocsApi` makes and
    answers it through `handler`, so one test can script both a write's 202
    body and the mutation-status polls that follow it."""

    def __init__(self, handler) -> None:
        self.calls: list[dict] = []
        self._handler = handler

    async def request(self, method, path, **kwargs) -> _Response:
        call = {"method": method, "path": path, **kwargs}
        self.calls.append(call)
        return _Response(self._handler(call))


def _default_handler(call: dict) -> dict:
    """The happy path: every write is accepted with a request id, and the
    one poll that follows reports it completed with no warning."""
    if call["path"].startswith("/mutationStatus/"):
        return {"completed": True}
    return {"requestId": "r-1"}


def _api(handler=_default_handler) -> DocsApi:
    return DocsApi(_RecordingClient(handler), "doc-under-test")


def _api_warning(text: str) -> DocsApi:
    def handler(call: dict) -> dict:
        if call["path"].startswith("/mutationStatus/"):
            return {"completed": True, "warning": text}
        return {"requestId": "r-1"}

    return DocsApi(_RecordingClient(handler), "doc-under-test")


def _api_never_completes() -> DocsApi:
    def handler(call: dict) -> dict:
        if call["path"].startswith("/mutationStatus/"):
            return {"completed": False}
        return {"requestId": "r-1"}

    return DocsApi(_RecordingClient(handler), "doc-under-test")


async def _body_sent_by(client: _RecordingClient, thunk) -> dict:
    """Run `thunk` and return the JSON body the page write itself sent — the
    last call that was not a mutation-status poll."""
    await thunk()
    writes = [c for c in client.calls if not c["path"].startswith("/mutationStatus/")]
    return writes[-1]["json"]


async def test_a_write_reports_applied_never_succeeded():
    """`completed: true` is what the API actually says; a stronger word
    than that would claim more than this client knows."""
    clock, _, sleep = _fixtures()
    result = await create_page(
        _api(), "X", content="<p>hi</p>", clock=clock, sleep=sleep
    )
    assert result["outcome"] == "applied"
    assert "succeeded" not in str(result).lower()


async def test_create_page_returns_the_new_page_id():
    """The 202 body carries the created page's id (measured 2026-09-08:
    `{"id": "canvas-jBZGx4yN81", "requestId": ...}`), and it is the page's
    real, permanent id. Without surfacing it a model that has just made a
    page cannot address the page it made: it has to list the document and
    match on the name it asked for, which is ambiguous the moment two pages
    share a name — the validation doc records this document already holding
    two pages both named `b6-20260907T145220Z`."""

    def handler(call: dict) -> dict:
        if call["path"].startswith("/mutationStatus/"):
            return {"completed": True}
        return {"id": "canvas-new01", "requestId": "r-1"}

    clock, _, sleep = _fixtures()
    result = await create_page(
        _api(handler), "X", content="<p>hi</p>", clock=clock, sleep=sleep
    )
    assert result["page_id"] == "canvas-new01"
    assert result["outcome"] == "applied"


async def test_create_page_reports_a_missing_id_as_none_rather_than_omitting_it():
    """Same convention as `warning`: the key is always there, valued None
    when the API did not say. A caller that has to test for a missing key
    reads a shape that changes with the weather."""

    def handler(call: dict) -> dict:
        if call["path"].startswith("/mutationStatus/"):
            return {"completed": True}
        return {"requestId": "r-1"}

    clock, _, sleep = _fixtures()
    result = await create_page(
        _api(handler), "X", content="<p>hi</p>", clock=clock, sleep=sleep
    )
    assert "page_id" in result
    assert result["page_id"] is None


async def test_create_page_still_reports_the_id_when_the_poll_gives_up():
    """An unknown outcome is exactly when the id matters most: the page may
    well exist, and this is the only handle on it the caller will ever get.
    Dropping the id here would leave a model unable to check, or to clean
    up, precisely when it most needs to."""

    def handler(call: dict) -> dict:
        if call["path"].startswith("/mutationStatus/"):
            return {"completed": False}
        return {"id": "canvas-new01", "requestId": "r-1"}

    clock, _, sleep = _fixtures()
    result = await create_page(
        _api(handler), "X", content="<p>hi</p>", clock=clock, sleep=sleep
    )
    assert result["outcome"] == "unknown"
    assert result["page_id"] == "canvas-new01"


async def test_no_other_write_tool_grew_a_page_id():
    """`page_id` is `create_page`'s alone. A rename or an append did not
    create anything, so a page id in their report would invite a reader to
    think something new exists."""
    clock, _, sleep = _fixtures()
    result = await rename_page(_api(), "p-1", "New", clock=clock, sleep=sleep)
    assert "page_id" not in result


async def test_a_warning_reaches_the_caller_verbatim():
    """`warning` is read with `.get` and surfaced unchanged — reworded or
    dropped, a caller could not tell what the API actually reported."""
    clock, _, sleep = _fixtures()
    result = await create_page(
        _api_warning("Some content was not imported."),
        "X",
        content="<p>hi</p>",
        clock=clock,
        sleep=sleep,
    )
    assert result["warning"] == "Some content was not imported."


async def test_a_poll_that_gives_up_says_unknown_and_may_already_have_applied():
    """Never 'failed'. And never 'unknown' alone, which invites a retry by
    hand that duplicates a write, since this API has no idempotency keys."""
    clock, _, sleep = _fixtures()
    result = await create_page(
        _api_never_completes(), "X", content="<p>hi</p>", clock=clock, sleep=sleep
    )
    assert result["outcome"] == "unknown"
    assert "may already have been applied" in result["detail"]
    assert "failed" not in str(result).lower()


async def test_rename_page_changes_the_name_and_not_the_content():
    """It sends a name and no canvasContent at all — a rename that carried
    an empty body would clear the page."""
    clock, _, sleep = _fixtures()
    client = _RecordingClient(_default_handler)
    api = DocsApi(client, "doc-under-test")
    body = await _body_sent_by(
        client, lambda: rename_page(api, "page-x", "New", clock=clock, sleep=sleep)
    )
    assert body["name"] == "New"
    assert "canvasContent" not in body


async def test_append_offers_no_way_to_replace():
    """Additive by construction: the only positions it accepts are append
    and prepend."""
    with pytest.raises(ContentRefused):
        await append_to_page(_api(), "page-x", "<p>x</p>", position="replace")


async def test_replace_element_requires_an_element_id():
    """Written because Task 12's probe confirmed the mechanism; had it not,
    replace_element would not exist and this test would not be written.

    There is deliberately no way to spell 'replace the whole page' here —
    `element_id` has no default, so omitting it is a `TypeError`, not a
    whole-page write."""
    with pytest.raises(TypeError):
        await replace_element(_api(), "page-x", content="<p>x</p>")


async def test_every_write_tool_says_its_output_must_not_be_fed_back():
    """The only enforcement of 'a read is never a write source' that exists.
    `content` is a free string, so no code can tell where a caller got it —
    the description is the whole mechanism, and an untested description is
    an unenforced rule."""
    async with Client(build_server(_config())) as client:
        for tool in (await client.list_tools()).tools:
            if tool.name in _CONTENT_WRITE_NAMES:
                assert "must not" in tool.description.lower()
                assert "read" in tool.description.lower()


# --- update_row and upsert_rows -----------------------------------------
#
# These sit over the chunker (`chunking.py`, exercised on its own terms in
# tests/test_chunking.py) rather than over the transport, so the fake here
# answers at the interface `DocsApi` itself exposes — `list_columns`,
# `update_row`, `upsert_rows`, `get_mutation_status` — instead of
# `request()`. `api.py`'s own body construction for these methods is
# covered by tests/test_api.py; what these tests pin is what tools/writes.py
# does with `DocsApi`'s methods: which row gets addressed, how a batch is
# chunked and reported, and that a warning stays scoped to its own chunk.

_ROW_COLUMN = {"id": "c-name", "name": "c-name", "format": {"type": "text"}}
"""Matches `tests/conftest._rows`'s key exactly, in both directions: it is
the column *name* `cells_for_write` resolves against, and the column *id*
the formatted cell is sent under. `_NAME_COLUMN` (name `"Name"`, id
`"c-name"`) is not reusable here — `_rows()` keys its dicts `"c-name"`,
which is a name only this column has."""


class _RowApi:
    """A `DocsApi`-shaped fake for the row-write tools.

    Records each write by the keyword arguments `tools/writes.py` passed,
    not by a wire body — that translation is `api.py`'s job and is already
    pinned in tests/test_api.py. `get_mutation_status` completes every
    request on its very first poll, so a chunk's clock cost in these tests
    is exactly one `MUTATION_INITIAL_SLEEP_S`, and `warn_on_request_id` lets
    exactly one chunk's poll answer with a warning, in the order chunks are
    sent.
    """

    def __init__(
        self,
        *,
        columns: list[dict] | None = None,
        warn_on_request_id: str | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self._columns = columns if columns is not None else [_ROW_COLUMN]
        self._warn_on_request_id = warn_on_request_id
        self._next_id = 0

    def _new_request_id(self) -> str:
        self._next_id += 1
        return f"r-{self._next_id}"

    async def list_columns(self, table: str, deadline: Deadline) -> list[dict]:
        return self._columns

    async def update_row(
        self, table: str, row_id: str, cells: dict, deadline: Deadline
    ) -> dict:
        self.calls.append(
            {"op": "update_row", "table": table, "row_id": row_id, "cells": cells}
        )
        return {"requestId": self._new_request_id()}

    async def upsert_rows(
        self, table: str, rows: list[dict], *, key_columns, deadline: Deadline
    ) -> dict:
        self.calls.append(
            {
                "op": "upsert_rows",
                "table": table,
                "rows": rows,
                "key_columns": key_columns,
            }
        )
        return {"requestId": self._new_request_id()}

    async def get_mutation_status(self, request_id: str, deadline: Deadline) -> dict:
        if request_id == self._warn_on_request_id:
            return {"completed": True, "warning": "Some rows were not imported."}
        return {"completed": True}


async def test_update_row_addresses_the_row_by_id_never_by_name():
    """The API accepts a name and affects an arbitrary row on collision —
    the tool must always send the ID it was given, never a name, which is
    what a silent wrong-row write would come from."""
    api = _RowApi(columns=[_NAME_COLUMN])
    cache = ColumnCache(api)
    clock, _, sleep = _fixtures()
    await update_row(
        api, cache, "grid-x", "i-1", {"Name": "Ada"}, clock=clock, sleep=sleep
    )
    assert api.calls[-1]["row_id"] == "i-1"


async def test_update_row_resolves_cell_names_to_column_ids():
    """Cells are addressed by column name at this tool's boundary, the same
    as every other write, but the API's `row.cells` expects column IDs —
    `cells_for_write`'s translation, wired through here rather than
    bypassed."""
    api = _RowApi(columns=[_NAME_COLUMN])
    cache = ColumnCache(api)
    clock, _, sleep = _fixtures()
    await update_row(
        api, cache, "grid-x", "i-1", {"Name": "Ada"}, clock=clock, sleep=sleep
    )
    assert api.calls[-1]["cells"] == {_NAME_COLUMN["id"]: "Ada"}


async def test_update_row_refuses_a_calculated_column_before_sending():
    """`cells_for_write` runs before `api.update_row` is ever called — a
    refusal here must mean nothing was sent, not that the API discarded the
    value after accepting it."""
    api = _RowApi(columns=[_CALCULATED_COLUMN])
    cache = ColumnCache(api)
    clock, _, sleep = _fixtures()
    with pytest.raises(ContentRefused):
        await update_row(
            api, cache, "grid-x", "i-1", {"Total": 5}, clock=clock, sleep=sleep
        )
    assert api.calls == []


async def test_upsert_reports_every_row_it_was_given():
    """From `_rfc/plans/0013-plan.md`'s Task 22: the report has one entry
    per row the caller sent, whatever became of each one."""
    api = _RowApi()
    cache = ColumnCache(api)
    clock, _, sleep = _fixtures()
    report = await upsert_rows(api, cache, "grid-x", _rows(3), clock=clock, sleep=sleep)
    assert len(report["rows"]) == 3


async def test_a_batch_over_the_count_cap_is_split_not_refused():
    """`MAX_ROWS_PER_UPSERT` governs a split, never a refusal — the
    `request-sizing` topic's chunker sends 250 rows as three chunks rather
    than bouncing the call back to the caller to split by hand."""
    api = _RowApi()
    cache = ColumnCache(api)
    clock, _, sleep = _fixtures()
    report = await upsert_rows(
        api, cache, "grid-x", _rows(250), clock=clock, sleep=sleep
    )
    assert report["chunks"] == 3
    assert all(r["outcome"] != "refused" for r in report["rows"])


async def test_rows_the_deadline_never_reached_are_a_named_suffix():
    """Diverges from the plan's own snippet, which builds `Deadline(total_s=
    35.0)` with no `clock=`: that Deadline would run on real wall-clock time
    while `sleep` here advances a fake one — the exact two-budgets-on-one-
    clock bug `tests/conftest.py`'s `_fixtures` docstring warns against. This
    test pins the same behaviour the plan's does, on the one clock every
    other test in this module already uses."""
    api = _RowApi()
    cache = ColumnCache(api)
    clock, _, sleep = _fixtures()
    report = await upsert_rows(
        api,
        cache,
        "grid-x",
        _rows(250),
        deadline=Deadline(total_s=35.0, clock=clock),
        clock=clock,
        sleep=sleep,
    )
    not_attempted = [
        r["index"] for r in report["rows"] if r["outcome"] == "not_attempted"
    ]
    assert not_attempted
    assert not_attempted == list(range(min(not_attempted), 250))
    assert report["resume_from"] == min(not_attempted)


async def test_a_warning_on_one_chunk_is_not_attributed_to_the_others():
    """A warning on the first chunk's poll must land only on the rows that
    chunk carried, never bleed onto rows a later, warning-free chunk sent."""
    api = _RowApi(warn_on_request_id="r-1")
    cache = ColumnCache(api)
    clock, _, sleep = _fixtures()
    report = await upsert_rows(
        api, cache, "grid-x", _rows(250), clock=clock, sleep=sleep
    )
    rows = report["rows"]
    assert rows[0]["warning"] is not None
    assert rows[249]["warning"] is None


async def test_upsert_passes_key_columns_through_for_replay_safety():
    """`DocsApi.upsert_rows` picks `Replay.SAFE` only when `key_columns` is
    given; the tool must forward exactly what the caller passed rather than
    silently dropping it, since that choice is what makes a retry after a
    lost response safe instead of duplicating rows."""
    api = _RowApi()
    cache = ColumnCache(api)
    clock, _, sleep = _fixtures()
    await upsert_rows(
        api,
        cache,
        "grid-x",
        _rows(1),
        key_columns=["c-name"],
        clock=clock,
        sleep=sleep,
    )
    assert api.calls[-1]["key_columns"] == ["c-name"]


async def test_an_unknown_column_in_upsert_is_refused_before_any_chunk_is_sent():
    """The whole batch is resolved by `cells_for_write` up front: a bad
    column on the last row must not be discovered only after the rows ahead
    of it have already gone out as an earlier chunk."""
    api = _RowApi()
    cache = ColumnCache(api)
    clock, _, sleep = _fixtures()
    rows = _rows(3) + [{"Nonexistent": "x"}]
    with pytest.raises(ContentRefused):
        await upsert_rows(api, cache, "grid-x", rows, clock=clock, sleep=sleep)
    assert api.calls == []


# --- the gated tools -----------------------------------------------------
#
# delete_page, clear_page_content, overwrite_page and delete_element all run
# the pre-write guard (tools/guard.py's objects_owned_by_page) before
# touching the page; delete_rows and push_button address a table's rows
# directly and carry no such check. `_GatedApi` answers every method any of
# the six calls — the three listings the guard reads, plus each tool's own
# write and the mutation-status poll that follows it — so one fake fixture
# serves this whole section the way `_RowApi` serves update_row/upsert_rows
# above.


class _GatedApi:
    """A `DocsApi`-shaped fake for the six gated tools and the guard that
    runs in front of four of them.

    `owns` seeds what the guard's three listings — list_tables/list_controls
    /list_formulas — return; every write is recorded by the keyword
    arguments the tool passed and answered with a request id, and
    `get_mutation_status` reports every one of them applied on its first
    poll, the same shape `_RowApi` uses above.
    """

    def __init__(self, *, owns: dict[str, list[dict]] | None = None) -> None:
        self.calls: list[dict] = []
        self._owns = owns or {"tables": [], "controls": [], "formulas": []}
        self._next_id = 0

    def _new_request_id(self) -> str:
        self._next_id += 1
        return f"r-{self._next_id}"

    async def list_tables(self, deadline: Deadline) -> list[dict]:
        return self._owns["tables"]

    async def list_controls(self, deadline: Deadline) -> list[dict]:
        return self._owns["controls"]

    async def list_formulas(self, deadline: Deadline) -> list[dict]:
        return self._owns["formulas"]

    async def delete_page(self, page: str, deadline: Deadline) -> dict:
        self.calls.append({"op": "delete_page", "page": page})
        return {"requestId": self._new_request_id()}

    async def delete_page_content(
        self, page: str, *, element_ids: list[str] | None = None, deadline: Deadline
    ) -> dict:
        self.calls.append(
            {"op": "delete_page_content", "page": page, "element_ids": element_ids}
        )
        return {"requestId": self._new_request_id()}

    async def update_page(
        self,
        page: str,
        *,
        name: str | None = None,
        canvas: dict | None = None,
        insertion_mode: str = "append",
        element_id: str | None = None,
        deadline: Deadline,
    ) -> dict:
        self.calls.append(
            {
                "op": "update_page",
                "page": page,
                "canvas": canvas,
                "insertion_mode": insertion_mode,
                "element_id": element_id,
            }
        )
        return {"requestId": self._new_request_id()}

    async def delete_rows(
        self, table: str, row_ids: list[str], deadline: Deadline
    ) -> dict:
        self.calls.append({"op": "delete_rows", "table": table, "row_ids": row_ids})
        return {"requestId": self._new_request_id()}

    async def push_button(
        self, table: str, row_id: str, column: str, deadline: Deadline
    ) -> dict:
        self.calls.append(
            {"op": "push_button", "table": table, "row_id": row_id, "column": column}
        )
        return {"requestId": self._new_request_id()}

    async def get_mutation_status(self, request_id: str, deadline: Deadline) -> dict:
        return {"completed": True}


def _api_with_hidden_table() -> _GatedApi:
    """A table written as page content on `page-x`, invisible to
    `outline_page` — the case the guard is there to catch."""
    return _GatedApi(
        owns={
            "tables": [{"id": "grid-hidden", "parent": {"id": "page-x"}}],
            "controls": [],
            "formulas": [],
        }
    )


async def _call(tool: str, api, page_id: str, *, force: bool = False) -> dict:
    """Invoke one of the four page-guarded tools through `tool_boundary`,
    the same translation `register_gated_write_tools` wraps each one in, so
    a refusal surfaces here as the `ToolError` a model would actually see
    rather than the bare `ContentRefused` the function itself raises."""
    clock, _, sleep = _fixtures()

    async def run() -> dict:
        if tool == "clear_page_content":
            return await clear_page_content(
                api, page_id, force=force, clock=clock, sleep=sleep
            )
        if tool == "delete_page":
            return await delete_page(api, page_id, force=force, clock=clock, sleep=sleep)
        if tool == "overwrite_page":
            return await overwrite_page(
                api, page_id, "<p>new</p>", force=force, clock=clock, sleep=sleep
            )
        if tool == "delete_element":
            return await delete_element(
                api, page_id, "el-1", force=force, clock=clock, sleep=sleep
            )
        raise ValueError(f"not a page-guarded tool: {tool}")

    return await tool_boundary(run)()


@pytest.mark.parametrize(
    "tool", ["clear_page_content", "delete_page", "overwrite_page", "delete_element"]
)
async def test_a_gated_page_write_refuses_and_names_what_it_found(tool):
    """A refusal that just says 'this page has objects on it' gives a caller
    nothing to decide with — the found object's own id must appear."""
    with pytest.raises(ToolError) as caught:
        await _call(tool, _api_with_hidden_table(), "page-x")
    assert "grid-hidden" in str(caught.value)


@pytest.mark.parametrize(
    "tool", ["clear_page_content", "delete_page", "overwrite_page", "delete_element"]
)
async def test_force_overrides_the_refusal(tool):
    """`force=True` skips the guard entirely and lets the write proceed."""
    result = await _call(tool, _api_with_hidden_table(), "page-x", force=True)
    assert result["outcome"] == "applied"


async def test_delete_rows_addresses_rows_by_id_never_by_name():
    """Rows are addressed by ID for deletes exactly as they are for updates
    — the API affects an arbitrary row by name on collision."""
    clock, _, sleep = _fixtures()
    api = _GatedApi()
    await delete_rows(api, "grid-x", ["i-1", "i-2"], clock=clock, sleep=sleep)
    assert api.calls[-1]["row_ids"] == ["i-1", "i-2"]


async def test_delete_rows_splits_a_batch_over_the_id_cap():
    """1200 ids over a 500-id cap is three requests: two full and a
    remainder, the same split shape `upsert_rows` uses for its own cap."""
    clock, _, sleep = _fixtures()
    api = _GatedApi()
    report = await delete_rows(
        api, "grid-x", [f"i-{n}" for n in range(1200)], clock=clock, sleep=sleep
    )
    assert report["chunks"] == 3


async def test_push_button_names_the_row_and_the_column():
    clock, _, sleep = _fixtures()
    api = _GatedApi()
    await push_button(api, "grid-x", "i-1", "c-button", clock=clock, sleep=sleep)
    call = api.calls[-1]
    assert call["table"] == "grid-x"
    assert call["row_id"] == "i-1"
    assert call["column"] == "c-button"


async def test_overwrite_page_sends_html_like_every_other_write():
    """Force=True is enough here: it skips the guard, so this exercises the
    real `DocsApi.update_page` body-construction the same way
    test_a_page_write_sends_canvas_content_as_html does in tests/test_api.py,
    without needing controls/formulas listings this fake doesn't have."""
    clock, _, sleep = _fixtures()
    client = _RecordingClient(_default_handler)
    api = DocsApi(client, "doc-under-test")
    body = await _body_sent_by(
        client,
        lambda: overwrite_page(
            api, "page-x", "<p>new</p>", force=True, clock=clock, sleep=sleep
        ),
    )
    assert body["contentUpdate"]["canvasContent"]["format"] == "html"
    assert body["contentUpdate"]["insertionMode"] == "replace"


async def test_overwrite_page_description_carries_the_read_back_warning():
    """`test_every_write_tool_says_its_output_must_not_be_fed_back` above
    only ever sees the always-on tools, since it builds its server with the
    flag off — it can never reach `overwrite_page`, the one gated tool
    `_CONTENT_WRITE_NAMES` does include. This is what actually pins that
    tool's description against the same rule."""
    async with Client(build_server(_config(allow_destructive=True))) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    description = tools["overwrite_page"].description.lower()
    assert "must not" in description
    assert "read" in description


async def test_the_gated_tool_descriptions_do_not_carry_the_read_back_warning():
    """`_CONTENT_WRITE_NAMES` deliberately excludes five of the six gated
    tools: only `overwrite_page` carries caller-composed content, so only
    its description is required to warn against feeding a read back in.
    Padding the other five with words that do not apply to them would make
    the assertion in test_every_write_tool_says_its_output_must_not_be_fed_back
    trivially true instead of meaningful."""
    async with Client(build_server(_config(allow_destructive=True))) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    for name in _GATED_NAMES - _CONTENT_WRITE_NAMES:
        assert tools[name].description
        assert "must not" not in tools[name].description.lower()
