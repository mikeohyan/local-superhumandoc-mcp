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

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ContentRefused
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.server import build_server
from superhumandoc_mcp.tools.writes import (
    append_to_page,
    create_page,
    rename_page,
    replace_element,
    update_row,
    upsert_rows,
)
from tests.conftest import (
    _CALCULATED_COLUMN,
    _NAME_COLUMN,
    _WRITE_TOOL_NAMES,
    _config,
    _fixtures,
    _rows,
    _tool_names,
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
            if tool.name in _WRITE_TOOL_NAMES:
                assert "must not" in tool.description.lower()
                assert "read" in tool.description.lower()


async def test_read_page_is_still_not_registered():
    """The last always-on tool with no implementation. Its absence is
    declared, and this pins that it stays declared rather than half-built."""
    names = await _tool_names(build_server(_config()))
    assert "read_page" not in names


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
