"""Typed read calls against the API. One method per operation, each
resolving its own bucket, so no caller picks one by hand."""

from pathlib import Path

import httpx2
import pytest

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.buckets import Operation, bucket_for
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
    rows = (await api.list_rows("grid-x", Deadline(), limit=200)).rows
    assert [r["id"] for r in rows] == ["i-1", "i-2"]
    assert seen == [None, "t2"]


async def test_paging_stops_at_the_callers_cap_even_with_a_token_left():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json={"items": [{"id": "i"}] * 10, "nextPageToken": "always-more"}
        )

    api = _api(handler)
    rows = (await api.list_rows("grid-x", Deadline(), limit=25)).rows
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


# --- Helpers for the write calls (Tasks 13 and 16) -------------------------
#
# None of these belong in tests/conftest.py: the write wave's shared-fixtures
# section is explicit that a recording client which "captures what was sent"
# belongs to the one task that needs it, not to the shared module. Each is a
# few lines over one pattern — a small double that records what `request()`
# was called with and hands back a response nobody but the recorder reads.


def _recording_client(seen: list[str]):
    """A double that records only the *path* each request targets. Used for
    `get_mutation_status` alone: it is the one method whose path must not
    carry the doc id, and this is cheaper than reusing `_RecordingClient`
    just to reach into `calls[0]["path"] `via keyword args."""

    class _PathRecorder:
        async def request(self, method, path, **kwargs):
            seen.append(path)
            return httpx2.Response(200, json={"completed": True})

    return _PathRecorder()


async def _body_sent_by(call) -> dict:
    """Run `call` (a coroutine function taking a `DocsApi`) against a client
    that records what it was asked to send, and return that payload — never
    a response, which the recorder fabricates and nothing here reads."""
    client = _RecordingClient()
    api = DocsApi(client, "doc-under-test")
    await call(api)
    return client.calls[0]["json"]


async def _bucket_of(call) -> Bucket:
    client = _RecordingClient()
    api = DocsApi(client, "doc-under-test")
    await call(api)
    return client.calls[0]["bucket"]


async def _replay_used_by(method: str, args: tuple, **kwargs) -> Replay:
    """Call `method` on a fresh `DocsApi` with `args` and `kwargs`, and
    return the `Replay` it declared to the client. Generic over every write
    method so Task 16's parametrized test needs no per-method plumbing."""
    client = _RecordingClient()
    api = DocsApi(client, "doc-under-test")
    await getattr(api, method)(*args, deadline=Deadline(), **kwargs)
    return client.calls[0]["replay"]


async def _replay_used(key_columns: list[str] | None) -> Replay:
    return await _replay_used_by(
        "upsert_rows", ("grid-x", [{"c-name": "x"}]), key_columns=key_columns
    )


_WRITE_CALLS = [
    (lambda api: api.create_page("X", deadline=Deadline()), Operation.CREATE_PAGE),
    (lambda api: api.update_page("page-x", deadline=Deadline()), Operation.UPDATE_PAGE),
    (lambda api: api.delete_page("page-x", Deadline()), Operation.DELETE_PAGE),
    (
        lambda api: api.delete_page_content("page-x", deadline=Deadline()),
        Operation.DELETE_PAGE_CONTENT,
    ),
    (
        lambda api: api.upsert_rows(
            "grid-x", [{"c-name": "x"}], key_columns=["c-name"], deadline=Deadline()
        ),
        Operation.UPSERT_ROWS,
    ),
    (
        lambda api: api.update_row("grid-x", "i-1", {"c-name": "x"}, Deadline()),
        Operation.UPDATE_ROW,
    ),
    (lambda api: api.delete_rows("grid-x", ["i-1"], Deadline()), Operation.DELETE_ROWS),
    (
        lambda api: api.push_button("grid-x", "i-1", "c-go", Deadline()),
        Operation.PUSH_BUTTON,
    ),
]


# --- Task 13: typed write calls against the API -----------------------------


async def test_the_mutation_status_path_is_not_doc_scoped():
    """Every other method interpolates a doc id. This one must not — a public
    client got this wrong and polled a path that does not exist."""
    seen: list[str] = []
    api = DocsApi(_recording_client(seen), "doc-under-test")
    await api.get_mutation_status("req-1", Deadline())
    assert seen[-1].endswith("/mutationStatus/req-1")
    assert "doc-under-test" not in seen[-1]


async def test_a_status_poll_declares_itself_replay_safe():
    """An idempotent GET. Re-reading a status never replays what it watches."""
    assert await _replay_used_by("get_mutation_status", ("r",)) is Replay.SAFE


async def test_a_page_write_sends_canvas_content_as_html():
    """`canvasContent.format` is `html` on every page-content write per the
    write wave's Global Constraints. The pinned `coda-openapi.yaml` nests
    `canvasContent` inside `contentUpdate` on `PageUpdate` — the plan's own
    sketch checked a flat `body["canvasContent"]`, which does not match the
    spec `PageContentUpdate` requires, so the assertion below follows the
    spec instead."""
    body = await _body_sent_by(
        lambda api: api.update_page(
            "page-x",
            canvas={"format": "html", "content": "<p>hi</p>"},
            deadline=Deadline(),
        )
    )
    assert body["contentUpdate"]["canvasContent"]["format"] == "html"


async def test_a_page_write_is_additive_unless_told_otherwise():
    """`append` is the only mode that cannot destroy existing content, so it
    is the default. A method that defaulted to `replace` would turn every
    caller that forgot the argument into a whole-page wipe."""
    body = await _body_sent_by(
        lambda api: api.update_page(
            "page-x",
            canvas={"format": "html", "content": "<p>hi</p>"},
            deadline=Deadline(),
        )
    )
    assert body["contentUpdate"]["insertionMode"] == "append"
    assert "elementId" not in body["contentUpdate"]


async def test_an_element_scoped_replace_names_the_element_it_replaces():
    """Measured 2026-09-07: with `elementId` set, only the named element
    changes. Without it, `replace` rewrites the whole page — the API tells
    the two apart by the field's absence, not by a flag, so sending a null
    or an empty string would be a whole-page wipe wearing a narrower name."""
    body = await _body_sent_by(
        lambda api: api.update_page(
            "page-x",
            canvas={"format": "html", "content": "<p>new</p>"},
            insertion_mode="replace",
            element_id="cl-GQI0miY3Cs",
            deadline=Deadline(),
        )
    )
    assert body["contentUpdate"]["insertionMode"] == "replace"
    assert body["contentUpdate"]["elementId"] == "cl-GQI0miY3Cs"


async def test_every_write_is_charged_to_its_mapped_bucket():
    for call, operation in _WRITE_CALLS:
        assert await _bucket_of(call) is bucket_for(operation)


async def test_a_write_returns_the_parsed_body_not_the_response():
    """A 202 carries the requestId the poll loop needs."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(202, json={"id": "page-x", "requestId": "req-1"})

    api = _api(handler)
    body = await api.delete_page("page-x", Deadline())
    assert body["requestId"] == "req-1"


# --- Task 16: replay eligibility travels with the call ----------------------


async def test_a_keyed_upsert_is_replay_safe():
    """With key_columns the operation is idempotent, so a timeout after
    transmission can be retried without duplicating rows."""
    assert await _replay_used(key_columns=["Name"]) is Replay.SAFE


async def test_an_unkeyed_upsert_is_never_replayed():
    """There are no idempotency keys. Replaying this duplicates rows."""
    assert await _replay_used(key_columns=None) is Replay.UNSAFE


@pytest.mark.parametrize(
    "method,args",
    [
        ("create_page", ("X",)),
        ("update_page", ("page-x",)),
        ("delete_page", ("page-x",)),
        ("delete_page_content", ("page-x",)),
        ("update_row", ("grid-x", "i-1", {"c-name": "x"})),
        ("delete_rows", ("grid-x", ["i-1"])),
        ("push_button", ("grid-x", "i-1", "c-go")),
    ],
)
async def test_every_other_write_is_unsafe(method, args):
    assert await _replay_used_by(method, args) is Replay.UNSAFE


@pytest.mark.parametrize(
    "call,expected_path",
    [
        (lambda api: api.list_controls(Deadline()), "/docs/doc-under-test/controls"),
        (lambda api: api.list_formulas(Deadline()), "/docs/doc-under-test/formulas"),
    ],
)
async def test_the_guard_listings_are_document_scoped_reads(call, expected_path):
    """The two listings the pre-write guard reads, and the only two API
    methods no tool calls directly.

    Both endpoints were confirmed live on 2026-09-07 — this file had no
    evidence they existed at all when the guard was written against them, and
    the guard shipped calling methods that were not there. Pinning the paths
    and the bucket here is what makes that a test failure next time rather
    than an AttributeError the first time a destructive write is guarded.
    """
    seen: list[str] = []

    class _PathRecorder:
        async def request(self, method, path, **kwargs):
            seen.append(path)
            self.kwargs = kwargs
            return httpx2.Response(200, json={"items": []})

    recorder = _PathRecorder()
    await call(DocsApi(recorder, "doc-under-test"))

    assert seen == [expected_path]
    assert recorder.kwargs["bucket"] is Bucket.READ
    assert recorder.kwargs["replay"] is Replay.SAFE


# --- The three API calls export needs: get_page, begin_export,
# get_export_status ---


async def test_the_export_status_path_is_page_scoped_not_root():
    """The mutation status path is document-agnostic and lives at the API
    root; this one is neither. Sending an export id to /mutationStatus/ is the
    mistake this pins against, and it would 404 in a way that looks exactly
    like replication lag."""
    seen: list[str] = []

    class _PathRecorder:
        async def request(self, method, path, **kwargs):
            seen.append(path)
            return httpx2.Response(200, json={"status": "inProgress"})

    await DocsApi(_PathRecorder(), "doc-under-test").get_export_status(
        "page-x", "req-1", Deadline()
    )
    assert seen == ["/docs/doc-under-test/pages/page-x/export/req-1"]


async def test_reading_one_page_is_document_scoped():
    """`get_page` is the cheap read `read_page` makes before deciding whether
    to export at all. Nothing else in this wave pins its path, and a wrong one
    would surface as a 404 that reads like a missing page."""
    seen: list[str] = []

    class _PathRecorder:
        async def request(self, method, path, **kwargs):
            seen.append(path)
            self.kwargs = kwargs
            return httpx2.Response(200, json={"contentType": "canvas"})

    recorder = _PathRecorder()
    await DocsApi(recorder, "doc-under-test").get_page("page-x", Deadline())
    assert seen == ["/docs/doc-under-test/pages/page-x"]
    assert recorder.kwargs["bucket"] is Bucket.READ


async def test_the_kickoff_names_the_output_format_it_was_given():
    """The two formats carry different content, so a method that ignored this
    argument would silently return the wrong one rather than failing."""
    body = await _body_sent_by(
        lambda api: api.begin_export("page-x", "html", Deadline())
    )
    assert body == {"outputFormat": "html"}


@pytest.mark.parametrize(
    "method,args,expected",
    [
        ("get_export_status", ("page-x", "r"), Replay.SAFE),
        ("get_page", ("page-x",), Replay.SAFE),
        ("begin_export", ("page-x", "markdown"), Replay.UNSAFE),
    ],
)
async def test_reads_may_be_replayed_and_a_kickoff_may_not(method, args, expected):
    """Starting a second export is not a replay of the first -- it would
    contend for the same blob, which is the collision the per-page
    serialisation exists to prevent."""
    assert await _replay_used_by(method, args) is expected

