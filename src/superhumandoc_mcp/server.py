"""Server factory.

Tool registration happens here, at build time, before `run()` — never at
request time. The `tool-surface` topic's destructive-tool gating depends on
registration being a build-time decision; see `_rfc/README.md`. This wave
registers the always-on read and write tools; the `tool-surface` topic's
gated tools and the `upstream-api` topic's throttle wiring are out of scope
here.
"""

from mcp.server import MCPServer

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.client import DocsClient
from superhumandoc_mcp.config import Config
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.tools.reads import register_read_tools
from superhumandoc_mcp.tools.writes import register_write_tools


def build_server(config: Config) -> MCPServer:
    """Construct the server.

    Registration happens here, at build time, before `run()`. The
    `tool-surface` topic's destructive gating depends on that and on nothing
    dynamic at request time — `config.allow_destructive` decides which tools
    exist, not whether an existing tool refuses. Nothing in this wave sits
    behind that gate yet: `config.allow_destructive` is read once a gated
    tool exists.

    One `ColumnCache` is built here and passed to both registrars, so
    `describe_table`, `get_doc_overview`, and every column-resolving row
    write share a single cache rather than each registrar keeping its own
    copy that could disagree after the first write.
    """
    server = MCPServer("superhumandoc-mcp")
    api = DocsApi(DocsClient(config), config.doc_id)
    cache = ColumnCache(api)
    register_read_tools(server, api, cache)
    register_write_tools(server, api, cache)
    return server
