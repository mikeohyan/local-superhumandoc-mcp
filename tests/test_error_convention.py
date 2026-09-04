"""The error convention `superhumandoc_mcp` will rely on once it has tools.

`build_server()` registers nothing yet, so this exercises a throwaway server
built locally, not `superhumandoc_mcp.server.build_server`. What is under test
is the SDK's own behaviour — a `ToolError` message reaches the client verbatim
in `content`, and any other exception is redacted to `Error executing tool
<name>` — which the `packaging` topic's tool layer depends on. See
`docs/reference/mcp-sdk-v2-api-surface.md` for the verified evidence and
`_rfc/README.md` for how to find the `packaging` topic's current RFC.

Asserted on `CallToolResult.is_error` / `.content`, never on a raised
exception: `Client(server, raise_exceptions=True)` does not re-raise a
tool-body exception, so a test written to expect one fails for the wrong
reason.
"""

from mcp import Client
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError


def _build_throwaway_server() -> MCPServer:
    server = MCPServer("error-convention-throwaway")

    @server.tool()
    def fail_anticipated() -> str:
        raise ToolError("a specific, anticipated failure message")

    @server.tool()
    def fail_unanticipated() -> str:
        raise RuntimeError("some internal bug detail that should be redacted")

    return server


async def test_tool_error_message_reaches_the_client() -> None:
    server = _build_throwaway_server()
    async with Client(server) as client:
        result = await client.call_tool("fail_anticipated", {})
        assert result.is_error is True
        assert "a specific, anticipated failure message" in result.content[0].text


async def test_bare_exception_is_redacted() -> None:
    server = _build_throwaway_server()
    async with Client(server) as client:
        result = await client.call_tool("fail_unanticipated", {})
        assert result.is_error is True
        assert "internal bug detail" not in result.content[0].text
        assert "Error executing tool fail_unanticipated" in result.content[0].text
