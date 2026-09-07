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
    """`n` distinct small rows, each identifiable by its index."""
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
_WRITE_TOOL_NAMES = {
    "create_page",
    "append_to_page",
    "replace_element",
    "rename_page",
    "upsert_rows",
    "update_row",
} | _GATED_NAMES


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
