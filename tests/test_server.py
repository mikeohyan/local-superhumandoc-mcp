"""Wave 1's acceptance test: the server starts and registers the read tools.

In-process, via `mcp.Client(server)` — no subprocess, no stdio. See
`docs/reference/mcp-sdk-v2-api-surface.md` for why this is the only in-process
path in `mcp` 2.x (`create_connected_server_and_client_session` is gone).
"""

from pathlib import Path

from mcp import Client

from superhumandoc_mcp.api import Listing
from superhumandoc_mcp.config import Config
from superhumandoc_mcp.gate import ExportGate
from superhumandoc_mcp.server import build_server
from superhumandoc_mcp.tools.reads import PageCache
from tests.conftest import _GATED_NAMES, _tool_names


def _config(allow_destructive: bool = False) -> Config:
    return Config(
        api_key="token",
        doc_id="doc",
        allow_destructive=allow_destructive,
        log_level="INFO",
        env_file=Path("/tmp/.env"),
        sources={},
    )


async def test_lists_exactly_the_always_on_tools() -> None:
    """Deliberately an exact set rather than a subset. This is the whole tool
    surface a model sees, so it should fail when a tool appears by accident
    as loudly as when an intended one goes missing. Widen it when a task
    registers a tool, never to make it pass."""
    server = build_server(_config())
    async with Client(server) as client:
        result = await client.list_tools()
        assert {tool.name for tool in result.tools} == {
            "outline_page",
            "describe_table",
            "get_doc_overview",
            "get_row",
            "find_rows",
            "create_page",
            "append_to_page",
            "rename_page",
            "replace_element",
            "update_row",
            "upsert_rows",
            "read_page",
        }


async def test_every_registered_tool_describes_itself() -> None:
    """The decided surface requires specific things of these descriptions —
    that a read is a projection, that filtering is one column and exact-value
    only. None of that can be true of a tool with no description at all, and
    a model choosing between tools sees nothing else."""
    async with Client(build_server(_config())) as client:
        for tool in (await client.list_tools()).tools:
            assert tool.description, f"{tool.name} has no description"


async def test_gated_tools_are_absent_when_the_flag_is_unset() -> None:
    """Unregistered, not merely refusing: with the flag off, the model
    cannot see a gated tool's name at all, so no per-call permission
    decision ever arises for it."""
    names = await _tool_names(build_server(_config(allow_destructive=False)))
    assert not (_GATED_NAMES & names)


async def test_the_flag_adds_exactly_the_gated_tools_and_nothing_else() -> None:
    """Supersedes test_the_destructive_gate_adds_no_tools_in_this_wave, which
    pinned the opposite fact before any gated tool existed. An exact-set
    difference, not a superset check, so a seventh tool riding in on this
    flag by accident would fail this the same way an unintended always-on
    tool fails test_lists_exactly_the_always_on_tools."""
    off = await _tool_names(build_server(_config(allow_destructive=False)))
    on = await _tool_names(build_server(_config(allow_destructive=True)))
    assert on - off == _GATED_NAMES


async def test_one_export_gate_serves_the_whole_server(monkeypatch):
    """A gate built per call, or per tool, enforces nothing: two concurrent
    calls would each hold their own and both proceed, which is precisely the
    collision the per-page limit exists to prevent. Counting constructions
    tests that directly, without reaching into the tool manager's private
    registry to fish a closure out of a decorated wrapper.

    Counting is only half of it, and this no longer stands alone:
    `test_the_collaborators_built_here_are_the_ones_read_page_uses` below
    pins that the gate built here is the one the tool actually enters, which
    a construction count cannot see. This is kept because it fails on the
    construction alone, with no stubs and no tool call in the way."""
    built = []

    class _Counted(ExportGate):
        def __init__(self, *args, **kwargs):
            built.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("superhumandoc_mcp.server.ExportGate", _Counted)
    build_server(_config())
    assert len(built) == 1


# --- every tool, through the MCP boundary --------------------------------
#
# Everything above this line inspects the tool *listing*. Nothing above it
# ever calls a tool, which is how a wrapper annotated `-> list[dict]` over a
# delegate returning a dict shipped: the SDK validates a tool's return value
# against the wrapper's `__annotations__` with pydantic, and a mismatch is
# raised as `UnexpectedToolError` and redacted to "Error executing tool
# <name>". Every direct-call test in this repository passes while the tool is
# unusable through a client, because the annotation is only consulted on the
# path a client takes.


_EXPORTED_HTML = "<h1>stub</h1>"
_STUB_PAGE_ID = "canvas-stub01"
_STUB_COLUMN = {"id": "c-stub01", "name": "Name", "format": {"type": "text"}}


class _StubApi:
    """Answers every `DocsApi` method the registered tools reach.

    Deliberately the smallest shape each call site accepts rather than a
    faithful API double — what is under test here is the boundary between a
    client and a tool, not what any tool does with a realistic body. The
    write methods take `*args, **kwargs` for the same reason: this stands in
    for eleven signatures and pinning each one here would make it a second
    copy of `api.py` to keep in step.
    """

    _ACCEPTED = {"requestId": "request-stub01"}

    async def list_page_content(self, page, deadline):
        return [{"id": "el-1", "itemContent": {"style": "paragraph", "content": "x"}}]

    async def list_pages(self, deadline):
        return [{"id": _STUB_PAGE_ID, "name": "Stub"}]

    async def list_tables(self, deadline):
        return []

    async def list_controls(self, deadline):
        return []

    async def list_formulas(self, deadline):
        return []

    async def list_columns(self, table, deadline):
        return [_STUB_COLUMN]

    async def get_row(self, table, row_id, deadline):
        return {"id": row_id, "values": {_STUB_COLUMN["id"]: "Ada"}}

    async def list_rows(self, table, deadline, *, limit, params=None):
        return Listing([{"id": "i-1", "values": {_STUB_COLUMN["id"]: "Ada"}}], True, None)

    async def get_page(self, page, deadline):
        return {
            "id": _STUB_PAGE_ID,
            "contentType": "canvas",
            "updatedAt": "2026-09-07T10:00:00Z",
        }

    async def begin_export(self, page, output_format, deadline):
        return {"id": "export-stub01"}

    async def get_export_status(self, page, request_id, deadline):
        return {"downloadLink": "https://example.test/export-stub01"}

    async def get_mutation_status(self, request_id, deadline):
        return {"completed": True}

    async def create_page(self, *args, **kwargs):
        return self._ACCEPTED

    async def update_page(self, *args, **kwargs):
        return self._ACCEPTED

    async def delete_page(self, *args, **kwargs):
        return self._ACCEPTED

    async def delete_page_content(self, *args, **kwargs):
        return self._ACCEPTED

    async def update_row(self, *args, **kwargs):
        return self._ACCEPTED

    async def upsert_rows(self, *args, **kwargs):
        return self._ACCEPTED

    async def delete_rows(self, *args, **kwargs):
        return self._ACCEPTED

    async def push_button(self, *args, **kwargs):
        return self._ACCEPTED


class _StubDownloader:
    """Stands in for `downloads.Downloader`: answers the export's download
    hop from memory and counts how many times it was asked."""

    def __init__(self, *args, **kwargs) -> None:
        self.calls = 0

    async def fetch(self, url, deadline):
        self.calls += 1
        return _EXPORTED_HTML


# One call per registered tool, with arguments the stub above can answer.
# Keyed by tool name and compared against `list_tools` as an exact set, so a
# tool registered without an end-to-end call here fails rather than being
# quietly skipped.
_ARGUMENTS_BY_TOOL = {
    "outline_page": {"page_id_or_name": _STUB_PAGE_ID},
    "describe_table": {"table_id_or_name": "grid-stub01"},
    "get_doc_overview": {},
    "get_row": {"table_id_or_name": "grid-stub01", "row_id": "i-1"},
    "find_rows": {"table_id_or_name": "grid-stub01"},
    "read_page": {"page_id_or_name": _STUB_PAGE_ID},
    "create_page": {"name": "Stub"},
    "append_to_page": {"page_id_or_name": _STUB_PAGE_ID, "content": "hello"},
    "rename_page": {"page_id_or_name": _STUB_PAGE_ID, "name": "Renamed"},
    "replace_element": {
        "page_id_or_name": _STUB_PAGE_ID,
        "element_id": "el-1",
        "content": "hello",
    },
    "update_row": {
        "table_id_or_name": "grid-stub01",
        "row_id": "i-1",
        "cells": {"Name": "Ada"},
    },
    "upsert_rows": {"table_id_or_name": "grid-stub01", "rows": [{"Name": "Ada"}]},
    "delete_page": {"page_id_or_name": _STUB_PAGE_ID},
    "clear_page_content": {"page_id_or_name": _STUB_PAGE_ID},
    "overwrite_page": {"page_id_or_name": _STUB_PAGE_ID, "content": "hello"},
    "delete_element": {"page_id_or_name": _STUB_PAGE_ID, "element_id": "el-1"},
    "delete_rows": {"table_id_or_name": "grid-stub01", "row_ids": ["i-1"]},
    "push_button": {
        "table_id_or_name": "grid-stub01",
        "row_id": "i-1",
        "column_id_or_name": "c-go",
    },
}


def _stub_collaborators(monkeypatch, downloader_class=_StubDownloader):
    """Replace what `build_server` constructs with in-memory stands-in, and
    take the two opening poll sleeps down to nothing.

    Both sleeps are the modules' own constants, read at call time, so
    zeroing them here keeps this suite on the real clock without any tool
    having to accept a fake one — the registered wrappers deliberately
    expose neither `clock` nor `sleep`, which is precisely the reason a test
    that drives them through a client has to reach the constants instead.
    """
    monkeypatch.setattr("superhumandoc_mcp.server.DocsApi", lambda *a, **k: _StubApi())
    monkeypatch.setattr("superhumandoc_mcp.server.Downloader", downloader_class)
    monkeypatch.setattr("superhumandoc_mcp.export.EXPORT_INITIAL_SLEEP_S", 0.0)
    monkeypatch.setattr("superhumandoc_mcp.polling.MUTATION_INITIAL_SLEEP_S", 0.0)


async def test_every_registered_tool_can_actually_be_called(monkeypatch) -> None:
    """The one test that crosses the MCP boundary for every tool there is.

    A tool is only reachable if its wrapper's parameters and its return
    annotation both survive the SDK's pydantic validation, and neither is
    exercised by calling the delegate directly with hand-passed arguments —
    which is what every other tool test in this repository does. A mismatch
    there does not fail loudly: the model gets "Error executing tool <name>"
    and never learns why, so `is_error` is the assertion and the tool's own
    text is the failure message.

    The argument table is compared against `list_tools` as an exact set, so
    a tool added without a call here fails this rather than slipping past
    it.
    """
    _stub_collaborators(monkeypatch)
    server = build_server(_config(allow_destructive=True))
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert names == set(_ARGUMENTS_BY_TOOL), (
            "every registered tool needs an entry in _ARGUMENTS_BY_TOOL so "
            "that it is called through a client at least once"
        )
        for name, arguments in _ARGUMENTS_BY_TOOL.items():
            result = await client.call_tool(name, arguments)
            assert result.is_error is False, (
                f"{name} failed through the client: {result.content[0].text}"
            )


async def test_the_collaborators_built_here_are_the_ones_read_page_uses(monkeypatch):
    """Constructing one of each is only half of it: the built object also has
    to reach the tool.

    `test_one_export_gate_serves_the_whole_server` above counts
    constructions, which two mutations survive — `read_page_tool` building
    its own `Downloader()`, `ExportGate()` and `PageCache()` inline, and a
    fresh `PageCache()` passed at the `register_read_tools` call site, since
    nothing counted page-cache constructions at all. This calls `read_page`
    through a client and asserts the instances `build_server` made are the
    ones that recorded the work, which kills both: an inline construction in
    `tools/reads.py` resolves that module's own names rather than the ones
    patched here, so the spy sees nothing.
    """
    gates, caches, downloaders = [], [], []

    class _Gate(ExportGate):
        def __init__(self, *args, **kwargs):
            gates.append(self)
            self.entered = []
            super().__init__(*args, **kwargs)

        def for_page(self, page_id, deadline):
            self.entered.append(page_id)
            return super().for_page(page_id, deadline)

    class _Cache(PageCache):
        def __init__(self) -> None:
            caches.append(self)
            self.stored = []
            super().__init__()

        def set(self, page_id, updated_at, html):
            self.stored.append(page_id)
            super().set(page_id, updated_at, html)

    class _Downloads(_StubDownloader):
        def __init__(self, *args, **kwargs) -> None:
            downloaders.append(self)
            super().__init__(*args, **kwargs)

    _stub_collaborators(monkeypatch, downloader_class=_Downloads)
    monkeypatch.setattr("superhumandoc_mcp.server.ExportGate", _Gate)
    monkeypatch.setattr("superhumandoc_mcp.server.PageCache", _Cache)

    async with Client(build_server(_config())) as client:
        result = await client.call_tool("read_page", {"page_id_or_name": _STUB_PAGE_ID})

    assert result.is_error is False, result.content[0].text
    assert (len(gates), len(caches), len(downloaders)) == (1, 1, 1)
    assert gates[0].entered == [_STUB_PAGE_ID]
    assert caches[0].stored == [_STUB_PAGE_ID]
    assert downloaders[0].calls == 1
