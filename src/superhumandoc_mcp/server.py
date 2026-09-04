"""Server factory.

Tool registration happens here, at build time, before `run()` — never at
request time. The `tool-surface` topic's destructive-tool gating depends on
registration being a build-time decision; see `_rfc/README.md`. This wave
registers no tools: the `tool-surface` topic's seventeen tools, the
`config-resolution` topic's `.env` loading, and the `upstream-api` topic's
throttle are all out of scope here. `build_server()` returning a server with
zero tools is the deliverable, not a placeholder for one.
"""

from mcp.server import MCPServer


def build_server() -> MCPServer:
    """Construct the server. Registers no tools yet."""
    return MCPServer("superhumandoc-mcp")
