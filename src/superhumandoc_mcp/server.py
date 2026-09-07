"""Server factory.

Tool registration happens here, at build time, before `run()` — never at
request time. The `tool-surface` topic's destructive-tool gating depends on
registration being a build-time decision; see `_rfc/README.md`. This wave
registers the always-on read and write tools, plus the six gated tools
behind `config.allow_destructive`; the `upstream-api` topic's throttle
wiring is still out of scope here.
"""

from mcp.server import MCPServer

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.client import DocsClient
from superhumandoc_mcp.config import Config
from superhumandoc_mcp.downloads import Downloader
from superhumandoc_mcp.gate import ExportGate
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.tools.reads import PageCache, register_read_tools
from superhumandoc_mcp.tools.writes import (
    register_gated_write_tools,
    register_write_tools,
)


def build_server(config: Config) -> MCPServer:
    """Construct the server.

    Registration happens here, at build time, before `run()`. The
    `tool-surface` topic's destructive gating depends on that and on nothing
    dynamic at request time — `config.allow_destructive` decides which tools
    exist, not whether an existing tool refuses. When the flag is unset,
    `register_gated_write_tools` is simply never called, so the six gated
    tools are absent from `list_tools` rather than present and refusing —
    the model never sees a name it cannot use, so no per-call permission
    decision arises.

    One `ColumnCache` is built here and passed to both always-on registrars,
    so `describe_table`, `get_doc_overview`, and every column-resolving row
    write share a single cache rather than each registrar keeping its own
    copy that could disagree after the first write. The gated tools take no
    cache: none of the six resolves a column name against one.

    `read_page`'s three collaborators are built here for the same reason,
    each for its own kind of correctness rather than out of mere symmetry.
    One `Downloader` is shared because it owns the tokenless HTTP client
    the download hop uses; there is nothing per-call to isolate by building
    a second one. One `ExportGate` is shared because the limits it enforces
    — one export per page, three across the server — are properties of the
    server's outstanding work, not of any single call; a gate built fresh
    per call or per tool would let two concurrent `read_page` calls each
    hold their own gate and both proceed, which is exactly the same-page
    collision the per-page limit exists to prevent. One page cache is
    shared because a render cached by one call must be visible to the next
    call that asks for the same unchanged page, which a cache rebuilt per
    call could never do.
    """
    server = MCPServer("superhumandoc-mcp")
    api = DocsApi(DocsClient(config), config.doc_id)
    cache = ColumnCache(api)
    downloader = Downloader()
    gate = ExportGate()
    pages = PageCache()
    register_read_tools(server, api, cache, downloader, gate, pages)
    register_write_tools(server, api, cache)
    if config.allow_destructive:
        register_gated_write_tools(server, api)
    return server
