"""Read tools: thin translations between the model's vocabulary and `api.py`.

Each tool function is directly testable without a server — it takes a
`DocsApi` as its first argument. `register_read_tools` is the seam that closes
each one over a single `DocsApi` instance and puts it on the server, because
the object the model calls cannot itself take an `api` argument.
"""

from mcp.server import MCPServer

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.tools.boundary import tool_boundary

_OUTLINE_PAGE_DESCRIPTION = (
    "Return a page's outline: an ordered list of "
    "{element_id, style, level, text}, one entry per line of the page. A "
    "page outline is a projection of the page, not its full content. It is "
    "cheap, works with a read-only token, and is the only source of the "
    "stable element IDs that anchored editing needs."
)


async def outline_page(api: DocsApi, page_id_or_name: str) -> list[dict]:
    """Return the page's lines as an ordered list of `{element_id, style,
    level, text}`.

    Probe P9: `style` and `lineLevel` are nested inside each item's
    `itemContent`, not at the item's top level. Reading them flat yields
    silent `None`s that look like valid data, so they are read from there.
    """
    items = await api.list_page_content(page_id_or_name, Deadline())
    lines = []
    for item in items:
        content = item.get("itemContent", {})
        lines.append(
            {
                "element_id": item.get("id"),
                "style": content.get("style"),
                "level": content.get("lineLevel"),
                "text": content.get("text", ""),
            }
        )
    return lines


def register_read_tools(server: MCPServer, api: DocsApi) -> None:
    """Register the always-on read tools on `server`, closing over `api`.

    The registered tool cannot take `api` as a model-visible parameter, so
    each one here is a thin wrapper that closes over the single `DocsApi`
    instance passed in and delegates to the directly-testable function above.
    """

    @server.tool(name="outline_page", description=_OUTLINE_PAGE_DESCRIPTION)
    @tool_boundary
    async def outline_page_tool(page_id_or_name: str) -> list[dict]:
        return await outline_page(api, page_id_or_name)
