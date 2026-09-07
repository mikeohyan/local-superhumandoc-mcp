"""Helpers shared by the write-wave test modules.

These are plain helpers rather than pytest fixtures: they are imported by name
(`from tests.conftest import FakeClock, _fixtures`) because most of them take
arguments, which a fixture cannot. They live here rather than in one test
module so that eight modules share one definition instead of each drifting its
own copy.

`FakeClock` reproduces the shape already present in `tests/test_deadline.py`,
`tests/test_client_retry.py` and `tests/test_throttle.py`: `now` is a float
*attribute* and the object itself is callable, which is what `Deadline`
expects. It is `clock()`, never `clock.now()`.
"""

from pathlib import Path

from mcp import Client

from superhumandoc_mcp.config import Config
from superhumandoc_mcp.errors import DownloadUnusable


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _fixtures():
    """A clock, the list of sleeps taken, and a sleep that advances the clock.

    Every `Deadline` in a test must be built with this same clock: a Deadline
    on wall-clock time while the code under test runs on a fake one is two
    budgets on one clock, which is the bug this pairing exists to prevent.
    """
    clock = FakeClock()
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(seconds)

    return clock, slept, sleep


def _rows(n: int) -> list[dict]:
    """`n` distinct small rows, each identifiable by its index.

    Keyed by column ID (`"c-name"`), not by column name (`"Name"`, as
    `_NAME_COLUMN["name"]` has it) -- combining these rows with `_NAME_COLUMN`
    in the same bulk write raises `ContentRefused` rather than the mismatch
    you were expecting. This has cost time more than once.
    """
    return [{"c-name": f"row-{i}"} for i in range(n)]


def _of_size(internal_bytes: int) -> dict:
    """One row measuring exactly `internal_bytes` under `row_internal_bytes`.

    The value carries no newlines, so its internal size is its UTF-8 length.
    """
    return {"c-name": "x" * internal_bytes}


def _tiny() -> dict:
    return _of_size(10)


def _small() -> dict:
    return _of_size(50)


def _huge() -> dict:
    return _of_size(200_000)


_NAME_COLUMN = {"id": "c-name", "name": "Name", "format": {"type": "text"}}
_DATE_COLUMN = {"id": "c-when", "name": "When", "format": {"type": "date"}}
_CALCULATED_COLUMN = {
    "id": "c-total",
    "name": "Total",
    "format": {"type": "number"},
    "calculated": True,
}
_BUTTON_COLUMN = {"id": "c-go", "name": "Go", "format": {"type": "button"}}

_GATED_NAMES = {
    "delete_page",
    "clear_page_content",
    "delete_rows",
    "push_button",
    "overwrite_page",
    "delete_element",
}
# The write tools that carry something the caller composed — page content, a
# page name, or cell values. These are the ones the rule "a read is never a
# write source" can actually be stated for, and the only ones whose
# descriptions are required to state it.
#
# The other five write tools name a thing to act on and carry no content at
# all: delete_page, clear_page_content, delete_rows, push_button and
# delete_element. Requiring them to warn against feeding a read back would buy
# a passing assertion and no guarantee — the words would have to be bent to
# fit, and a test satisfied by bent words stops discriminating.
_CONTENT_WRITE_NAMES = {
    "create_page",
    "append_to_page",
    "replace_element",
    "rename_page",
    "update_row",
    "upsert_rows",
    "overwrite_page",
}


def _config(allow_destructive: bool = False) -> Config:
    """The same configuration `tests/test_server.py` builds. Repeated here so
    the write-tool tests do not import from a sibling test module."""
    return Config(
        api_key="token",
        doc_id="doc",
        allow_destructive=allow_destructive,
        log_level="INFO",
        env_file=Path("/tmp/.env"),
        sources={},
    )


async def _tool_names(server) -> set[str]:
    """The names a model would actually see.

    `list_tools` is async and only reachable through a `Client`, so this is a
    coroutine: every call site awaits it. `tests/test_server.py` inlines this
    same three-line shape rather than sharing a helper; it is named here
    because five tests across two tasks need it.
    """
    async with Client(server) as client:
        return {tool.name for tool in (await client.list_tools()).tools}


class _Downloads:
    """Stands in for `downloads.Downloader` wherever a test drives an export.

    Counts fetches, answers each URL from `bodies`, and raises
    `DownloadUnusable` for any URL in `dead` — which is how a stale link is
    spelled to the export loop, since that is the exception the real
    downloader raises when a link has expired. `dead_all` fails every URL, for
    the case where a link never comes good however many times it is re-minted.
    """

    def __init__(
        self,
        bodies: dict[str, str] | None = None,
        *,
        default: str = "",
        dead: set[str] | None = None,
        dead_all: bool = False,
    ) -> None:
        self._bodies = bodies or {}
        self._default = default
        self._dead = dead or set()
        self._dead_all = dead_all
        self.calls = 0

    async def fetch(self, url: str, deadline) -> str:
        self.calls += 1
        if self._dead_all or url in self._dead:
            raise DownloadUnusable(url, "this test double treats it as dead")
        return self._bodies.get(url, self._default)


def _fixed_downloader(body: str) -> _Downloads:
    return _Downloads(default=body)


def _counting_downloader(body: str) -> _Downloads:
    """The same object as `_fixed_downloader`, under the name a test reads
    when the point is `.calls` rather than the body."""
    return _Downloads(default=body)


def _downloader_failing_on(url: str, *, then: str) -> _Downloads:
    return _Downloads(default=then, dead={url})


def _always_failing_downloader() -> _Downloads:
    return _Downloads(dead_all=True)


class _RecordingDownloads(_Downloads):
    """`_Downloads`, plus a record of every URL it was asked to fetch.

    Still answers *any* URL with `default` -- it does not narrow what the
    double accepts, only what a test can observe afterward. This is what lets
    a test assert that the URL handed to `downloader.fetch` was the one the
    poll body actually returned, not merely some URL: a fake shaped to answer
    every URL alike can otherwise agree with code that fetches the wrong one.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.urls: list[str] = []

    async def fetch(self, url: str, deadline) -> str:
        self.urls.append(url)
        return await super().fetch(url, deadline)


def _url_recording_downloader(body: str) -> _RecordingDownloads:
    return _RecordingDownloads(default=body)

