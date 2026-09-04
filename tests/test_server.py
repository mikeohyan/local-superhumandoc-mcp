"""Wave 1's acceptance test: the server starts and lists zero tools.

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


async def test_lists_zero_tools() -> None:
    server = build_server(_config())
    async with Client(server) as client:
        result = await client.list_tools()
        assert result.tools == []


async def test_still_lists_zero_tools_with_config() -> None:
    async with Client(build_server(_config())) as client:
        assert (await client.list_tools()).tools == []


async def test_zero_tools_even_when_destructive_is_enabled() -> None:
    """The gate is real, but nothing sits behind it yet — the seventeen tools
    belong to the tool-surface topic, not this wave."""
    async with Client(build_server(_config(allow_destructive=True))) as client:
        assert (await client.list_tools()).tools == []
