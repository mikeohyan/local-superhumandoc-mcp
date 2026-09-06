"""Typed read calls against the API. One method per operation, each
resolving its own bucket, so no caller picks one by hand."""

from pathlib import Path

import httpx2
import pytest

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.buckets import Operation
from superhumandoc_mcp.client import DocsClient
from superhumandoc_mcp.config import Config
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ClientError, Replay, UpstreamRefused
from superhumandoc_mcp.throttle import Bucket


def _config() -> Config:
    return Config(
        api_key="synthetic-token-not-real",
        doc_id="doc-under-test",
        allow_destructive=False,
        log_level="INFO",
        env_file=Path("/synthetic/.env"),
        sources={},
    )


async def _no_sleep(seconds: float) -> None:
    return None


def _client(handler) -> DocsClient:
    return DocsClient(
        _config(),
        transport=httpx2.MockTransport(handler),
        sleep=_no_sleep,
        rand=lambda: 1.0,
    )


def _api(handler) -> DocsApi:
    return DocsApi(_client(handler), "doc-under-test")


class _RecordingClient:
    """A double that records the kwargs `request()` was called with, without
    going through real HTTP. Used only to pin the bucket and replay choice —
    the thing under test is what `DocsApi` passes, not what the transport
    does with it."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request(self, method, path, **kwargs):
        self.calls.append(kwargs)
        return httpx2.Response(200, json={"items": [], "nextPageToken": None})


async def test_paging_follows_the_token_rather_than_the_requested_size():
    """The API silently clamps limit, so the count asked for proves nothing."""
    pages = [
        {"items": [{"id": "i-1"}], "nextPageToken": "t2"},
        {"items": [{"id": "i-2"}], "nextPageToken": None},
    ]
    seen: list[str | None] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.params.get("pageToken"))
        return httpx2.Response(200, json=pages[len(seen) - 1])

    api = _api(handler)
    rows = await api.list_rows("grid-x", Deadline(), limit=200)
    assert [r["id"] for r in rows] == ["i-1", "i-2"]
    assert seen == [None, "t2"]


async def test_paging_stops_at_the_callers_cap_even_with_a_token_left():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json={"items": [{"id": "i"}] * 10, "nextPageToken": "always-more"}
        )

    api = _api(handler)
    rows = await api.list_rows("grid-x", Deadline(), limit=25)
    assert len(rows) == 25


async def test_a_read_is_charged_to_the_read_bucket():
    client = _RecordingClient()
    api = DocsApi(client, "doc-under-test")
    await api.list_tables(Deadline())
    assert client.calls[0]["bucket"] is Bucket.READ


async def test_every_read_declares_itself_replay_safe():
    """Every call this module makes is a GET, and every GET is replay-safe.
    Omitting `replay=Replay.SAFE` silently gives up the one replay a read is
    entitled to after a timeout."""
    client = _RecordingClient()
    api = DocsApi(client, "doc-under-test")
    await api.list_pages(Deadline())
    await api.list_tables(Deadline())
    await api.list_columns("grid-x", Deadline())
    await api.list_page_content("canvas-1", Deadline())
    await api.list_rows("grid-x", Deadline(), limit=10)
    await api.get_row("grid-x", "i-1", Deadline())
    assert all(call["replay"] is Replay.SAFE for call in client.calls)


async def test_list_pages_hits_the_docs_pages_path():
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        return httpx2.Response(200, json={"items": [], "nextPageToken": None})

    api = _api(handler)
    await api.list_pages(Deadline())
    assert seen["path"] == "/apis/v1/docs/doc-under-test/pages"


async def test_list_columns_hits_the_tables_columns_path():
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        return httpx2.Response(200, json={"items": [], "nextPageToken": None})

    api = _api(handler)
    await api.list_columns("grid-x", Deadline())
    assert seen["path"] == "/apis/v1/docs/doc-under-test/tables/grid-x/columns"


async def test_list_page_content_uses_the_distinct_page_content_limit_param():
    """listPageContent takes `pageContentLimit`, capped at 500 — not `limit`,
    which is what every other listing endpoint uses."""
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(dict(request.url.params))
        return httpx2.Response(200, json={"items": [], "nextPageToken": None})

    api = _api(handler)
    await api.list_page_content("canvas-1", Deadline())
    assert "limit" not in seen[0]
    assert seen[0]["pageContentLimit"] == "500"


async def test_get_row_is_a_single_unpaged_request_returning_the_parsed_body():
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/apis/v1/docs/doc-under-test/tables/grid-x/rows/i-1"
        return httpx2.Response(200, json={"id": "i-1", "values": {"Name": "Ada"}})

    api = _api(handler)
    row = await api.get_row("grid-x", "i-1", Deadline())
    assert row == {"id": "i-1", "values": {"Name": "Ada"}}


async def test_get_row_is_not_paged_and_makes_exactly_one_request():
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(200, json={"id": "i-1", "nextPageToken": "should-be-ignored"})

    api = _api(handler)
    await api.get_row("grid-x", "i-1", Deadline())
    assert len(calls) == 1


async def test_the_doc_id_is_taken_from_the_constructor_not_a_private_attribute():
    """DocsClient does not expose the document id publicly. DocsApi is given
    its own doc_id explicitly rather than reaching into client internals."""
    client = _RecordingClient()
    api = DocsApi(client, "explicit-doc-id")
    assert api._doc_id == "explicit-doc-id"


async def test_operations_resolve_the_bucket_the_map_names():
    """No caller picks a bucket by hand; DocsApi resolves it via bucket_for."""
    client = _RecordingClient()
    api = DocsApi(client, "doc-under-test")
    await api.get_row("grid-x", "i-1", Deadline())
    assert client.calls[0]["operation"] == Operation.GET_ROW.value
    assert client.calls[0]["bucket"] is Bucket.READ


def _always_504() -> DocsApi:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(504)

    return _api(handler)


def _always_400(sizes: list[int]) -> DocsApi:
    def handler(request: httpx2.Request) -> httpx2.Response:
        sizes.append(int(request.url.params["limit"]))
        return httpx2.Response(400)

    return _api(handler)


async def test_a_504_halves_the_page_size_and_restarts():
    """A pageToken ignores every parameter sent beside it, so a smaller
    `limit` cannot take effect part-way through a listing — the whole pass
    restarts at the smaller size instead."""
    sizes: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        size = int(request.url.params["limit"])
        sizes.append(size)
        if size > 50:
            return httpx2.Response(504)
        return httpx2.Response(200, json={"items": [], "nextPageToken": None})

    api = _api(handler)
    await api.list_rows("grid-x", Deadline(), limit=200)
    assert sizes == [200, 100, 50]


async def test_the_ladder_stops_at_the_floor_and_surfaces_the_hypothesis():
    """Below the floor there is nothing left to try, and the likely cause is
    the document's own size rather than the request's."""
    with pytest.raises(UpstreamRefused) as caught:
        await _always_504().list_rows("grid-x", Deadline(), limit=200)
    assert "document" in caught.value.detail.lower()


async def test_the_ladder_stops_when_the_deadline_does_not_the_floor():
    expired = Deadline(total_s=0.0)
    with pytest.raises(ClientError):
        await _always_504().list_rows("grid-x", expired, limit=200)


async def test_a_non_504_refusal_is_not_laddered():
    """Only a gateway timeout means 'ask for less'. A 400 means something
    else, and must be surfaced immediately and unchanged."""
    sizes: list[int] = []
    with pytest.raises(UpstreamRefused) as caught:
        await _always_400(sizes).list_rows("grid-x", Deadline(), limit=200)
    assert len(sizes) == 1
    assert caught.value.status == 400
