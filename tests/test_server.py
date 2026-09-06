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


async def test_lists_the_always_on_read_tools() -> None:
    server = build_server(_config())
    async with Client(server) as client:
        result = await client.list_tools()
        assert {tool.name for tool in result.tools} == {"outline_page"}


async def test_still_lists_the_read_tools_with_config() -> None:
    async with Client(build_server(_config())) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert "outline_page" in names


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
