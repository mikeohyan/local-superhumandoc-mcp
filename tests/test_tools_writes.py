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
from superhumandoc_mcp.errors import ContentRefused
from superhumandoc_mcp.server import build_server
from superhumandoc_mcp.tools.writes import (
    append_to_page,
    create_page,
    rename_page,
    replace_element,
)
from tests.conftest import _WRITE_TOOL_NAMES, _config, _fixtures, _tool_names


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
