"""Wave 1's acceptance test: the server starts and registers the read tools.

In-process, via `mcp.Client(server)` — no subprocess, no stdio. See
`docs/reference/mcp-sdk-v2-api-surface.md` for why this is the only in-process
path in `mcp` 2.x (`create_connected_server_and_client_session` is gone).
"""

from pathlib import Path

from mcp import Client

from superhumandoc_mcp.config import Config
from superhumandoc_mcp.server import build_server


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
        }


async def test_every_registered_tool_describes_itself() -> None:
    """The decided surface requires specific things of these descriptions —
    that a read is a projection, that filtering is one column and exact-value
    only. None of that can be true of a tool with no description at all, and
    a model choosing between tools sees nothing else."""
    async with Client(build_server(_config())) as client:
        for tool in (await client.list_tools()).tools:
            assert tool.description, f"{tool.name} has no description"


async def test_the_destructive_gate_adds_no_tools_in_this_wave() -> None:
    """The gate is real, but nothing sits behind it yet: the registered tool
    set must be identical with the flag on and off. This is the invariant
    worth pinning now, because it will start failing the moment a gated tool
    is added — which is exactly when someone should look."""
    async with Client(build_server(_config(allow_destructive=False))) as off_client:
        off_names = {tool.name for tool in (await off_client.list_tools()).tools}
    async with Client(build_server(_config(allow_destructive=True))) as on_client:
        on_names = {tool.name for tool in (await on_client.list_tools()).tools}
    assert on_names == off_names
