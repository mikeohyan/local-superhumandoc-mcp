"""Server factory.

Tool registration happens here, at build time, before `run()` — never at
request time. The `tool-surface` topic's destructive-tool gating depends on
registration being a build-time decision; see `_rfc/README.md`. This wave
registers no tools: the `tool-surface` topic's seventeen tools and the
`upstream-api` topic's throttle are out of scope here. `build_server()`
returning a server with zero tools is the deliverable, not a placeholder for
one.
"""

from mcp.server import MCPServer

from superhumandoc_mcp.config import Config


def build_server(config: Config) -> MCPServer:
    """Construct the server.

    Registration happens here, at build time, before `run()`. The
    `tool-surface` topic's destructive gating depends on that and on nothing
    dynamic at request time — `config.allow_destructive` decides which tools
    exist, not whether an existing tool refuses. No tools are registered yet.
    """
    server = MCPServer("superhumandoc-mcp")
    _ = config.allow_destructive  # the gate the tool-surface wave will read
    return server
