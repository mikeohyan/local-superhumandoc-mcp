"""Read tools: thin translations between the model's vocabulary and `api.py`.

Each tool function is directly testable without a server — it takes a
`DocsApi` as its first argument. `register_read_tools` is the seam that closes
each one over a single `DocsApi` instance and puts it on the server, because
the object the model calls cannot itself take an `api` argument.
"""

from mcp.server import MCPServer

from superhumandoc_mcp.api import DocsApi
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.schema_cache import ColumnCache
from superhumandoc_mcp.tools.boundary import tool_boundary

# Recorded in docs/reference/api-operational-constants.md. At or below this
# many tables, get_doc_overview also returns each table's column schema
# inline; above it, columns are omitted and the response says so.
OVERVIEW_INLINE_COLUMNS_MAX_TABLES = 8

_OUTLINE_PAGE_DESCRIPTION = (
    "Return a page's outline: an ordered list of "
    "{element_id, style, level, text}, one entry per line of the page. A "
    "page outline is a projection of the page, not its full content. It is "
    "cheap, works with a read-only token, and is the only source of the "
    "stable element IDs that anchored editing needs."
)

_DESCRIBE_TABLE_DESCRIPTION = (
    "Return one table's column schema, keyed the same way as its rows. Reads "
    "from the same cache the row tools use, so calling this warms rather "
    "than duplicates that work."
)

_GET_DOC_OVERVIEW_DESCRIPTION = (
    "Return the document's page tree and table list, in one call, so a "
    f"model can orient in one turn. At or below {OVERVIEW_INLINE_COLUMNS_MAX_TABLES} "
    "tables each table's column schema is included inline; above that "
    "threshold columns are omitted and the response says so, directing the "
    "caller to describe_table for any table it needs the schema of."
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


async def describe_table(cache: ColumnCache, table_id_or_name: str) -> list[dict]:
    """Return one table's column schema, reading through the shared
    `ColumnCache` so this call warms it rather than duplicating a fetch the
    row tools (or `get_doc_overview`) may already have made or will make."""
    return await cache.columns(table_id_or_name, Deadline())


async def get_doc_overview(api: DocsApi, cache: ColumnCache) -> dict:
    """Return the page tree and the table list.

    At or below `OVERVIEW_INLINE_COLUMNS_MAX_TABLES` tables, each table's
    column schema is fetched (through the shared cache, so it costs at most
    one `listColumns` per table) and returned inline. Above that threshold,
    columns are omitted entirely rather than fetched and discarded, and the
    response names `describe_table` explicitly — a model cannot see the
    threshold, so the response itself must say what to call next.
    """
    deadline = Deadline()
    pages = await api.list_pages(deadline)
    tables = await api.list_tables(deadline)

    if len(tables) <= OVERVIEW_INLINE_COLUMNS_MAX_TABLES:
        tables_out = []
        for table in tables:
            columns = await cache.columns(table["id"], deadline)
            tables_out.append({**table, "columns": columns})
        return {"pages": pages, "tables": tables_out}

    return {
        "pages": pages,
        "tables": tables,
        "columns_omitted": (
            f"This document has more than {OVERVIEW_INLINE_COLUMNS_MAX_TABLES} "
            "tables, so column schemas were omitted from this overview. Call "
            "describe_table with a table's ID or name to get its columns."
        ),
    }


def register_read_tools(server: MCPServer, api: DocsApi) -> None:
    """Register the always-on read tools on `server`, closing over `api`.

    The registered tool cannot take `api` as a model-visible parameter, so
    each one here is a thin wrapper that closes over the single `DocsApi`
    instance passed in and delegates to the directly-testable function above.
    One `ColumnCache` is created here and shared between `describe_table` and
    `get_doc_overview`, so the two tools warm each other rather than each
    keeping its own copy.
    """
    cache = ColumnCache(api)

    @server.tool(name="outline_page", description=_OUTLINE_PAGE_DESCRIPTION)
    @tool_boundary
    async def outline_page_tool(page_id_or_name: str) -> list[dict]:
        return await outline_page(api, page_id_or_name)

    @server.tool(name="describe_table", description=_DESCRIBE_TABLE_DESCRIPTION)
    @tool_boundary
    async def describe_table_tool(table_id_or_name: str) -> list[dict]:
        return await describe_table(cache, table_id_or_name)

    @server.tool(
        name="get_doc_overview", description=_GET_DOC_OVERVIEW_DESCRIPTION
    )
    @tool_boundary
    async def get_doc_overview_tool() -> dict:
        return await get_doc_overview(api, cache)
