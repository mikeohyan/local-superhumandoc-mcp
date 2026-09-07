"""Wave 1's acceptance test: the server starts and registers the read tools.

In-process, via `mcp.Client(server)` — no subprocess, no stdio. See
`docs/reference/mcp-sdk-v2-api-surface.md` for why this is the only in-process
path in `mcp` 2.x (`create_connected_server_and_client_session` is gone).
"""

from pathlib import Path

from mcp import Client

from superhumandoc_mcp.config import Config
from superhumandoc_mcp.server import build_server
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
