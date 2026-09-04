"""Wave 1's acceptance test: the server starts and lists zero tools.

In-process, via `mcp.Client(server)` — no subprocess, no stdio. See
`docs/reference/mcp-sdk-v2-api-surface.md` for why this is the only in-process
path in `mcp` 2.x (`create_connected_server_and_client_session` is gone).
"""

from mcp import Client

from superhumandoc_mcp.server import build_server


async def test_lists_zero_tools() -> None:
    server = build_server()
    async with Client(server) as client:
        result = await client.list_tools()
        assert result.tools == []
