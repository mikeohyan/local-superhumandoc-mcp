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

_GET_ROW_DESCRIPTION = (
    "Return one row by its ID, with its cells keyed by column name. Rows are "
    "addressed by ID, never by name: the API accepts a name but affects an "
    "arbitrary row on collision. The returned row always carries `row_id`, "
    "because every write addresses a row by that value."
)

_FIND_ROWS_DESCRIPTION = (
    "List a table's rows, up to `limit`, with cells keyed by column name and "
    "each row carrying its row ID. Server-side filtering supports at most "
    "one column, exact-value match only; every other condition is applied "
    "client-side after paging."
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


def _cells_by_name(values: dict, columns: list[dict]) -> dict:
    """Resolve a row's `values` (keyed by column ID — real keys look like
    `c-euWseAF6J-`, docs/reference/api-operational-constants.md §6) against a
    table's column schema.

    A column ID that the schema does not know about — a stale cache entry, or
    a column the schema listing simply omitted — is not dropped: the cell is
    kept under its raw ID rather than silently losing data.
    """
    name_by_id = {column["id"]: column["name"] for column in columns}
    return {
        name_by_id.get(column_id, column_id): value
        for column_id, value in values.items()
    }


async def get_row(
    api: DocsApi, cache: ColumnCache, table_id_or_name: str, row_id: str
) -> dict:
    """Return one row with its cells keyed by column name, resolved through
    the shared `ColumnCache`.

    The row always carries `row_id`: rows are addressed by ID, never by
    name — the API accepts a name but affects an arbitrary row on
    collision — and every later write needs this value to name the row it
    changes.
    """
    deadline = Deadline()
    row = await api.get_row(table_id_or_name, row_id, deadline)
    columns = await cache.columns(table_id_or_name, deadline)
    return {
        "row_id": row.get("id", row_id),
        "cells": _cells_by_name(row.get("values", {}), columns),
    }


async def find_rows(
    api: DocsApi,
    cache: ColumnCache,
    table_id_or_name: str,
    *,
    filters: dict[str, object] | None = None,
    sort: str | None = None,
    limit: int = 200,
) -> dict:
    """List a table's rows, up to `limit`, with cells keyed by column name and
    each row carrying its row ID — the same resolution `get_row` performs,
    applied to every row a listing pass returns.

    Server-side filtering supports exactly one column, exact-value match
    only. When `filters` is given, only its first entry is offered to the API
    as a query condition; every entry in `filters` — including that first
    one — is still checked here after paging, so correctness never depends
    on whether the server actually applied it. `sort`, if given, is passed
    through to the API unchanged.

    Ladders through `DocsApi.list_rows`'s 504 handling (RFC 0011 rule 9),
    which has shipped tested only against a mock: no 504 has ever been
    observed from this client against the real API.

    Returns `{"rows", "complete", "note"}` rather than a bare list. The tool
    pages up to the caller's cap, so a short result is ambiguous on its own —
    it could be a small table or a listing the deadline cut short, and rule 9
    requires the difference be said aloud rather than left to be inferred.
    The shape does not vary with the outcome: a caller that has to test for
    the presence of a key to learn whether it saw the whole table will
    eventually forget to.
    """
    deadline = Deadline()
    columns = await cache.columns(table_id_or_name, deadline)
    id_by_name = {column["name"]: column["id"] for column in columns}

    params: dict[str, object] = {}
    if filters:
        column, value = next(iter(filters.items()))
        column_id = id_by_name.get(column, column)
        params["query"] = f'{column_id}:"{value}"'
    if sort:
        params["sortBy"] = sort

    listing = await api.list_rows(
        table_id_or_name, deadline, limit=limit, params=params or None
    )
    resolved = [
        {
            "row_id": row.get("id"),
            "cells": _cells_by_name(row.get("values", {}), columns),
        }
        for row in listing.rows
    ]

    if filters:
        resolved = [
            row
            for row in resolved
            if all(row["cells"].get(key) == value for key, value in filters.items())
        ]

    note = None
    if not listing.complete:
        note = (
            f"Incomplete: stopped at {listing.stopped_because} after reading "
            f"{len(listing.rows)} rows, short of the requested {limit}. This "
            "is part of the table, not all of it. Ask for fewer rows, or "
            "narrow the filter, to see the rest."
        )
    return {"rows": resolved, "complete": listing.complete, "note": note}


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

    @server.tool(name="get_row", description=_GET_ROW_DESCRIPTION)
    @tool_boundary
    async def get_row_tool(table_id_or_name: str, row_id: str) -> dict:
        return await get_row(api, cache, table_id_or_name, row_id)

    @server.tool(name="find_rows", description=_FIND_ROWS_DESCRIPTION)
    @tool_boundary
    async def find_rows_tool(
        table_id_or_name: str,
        filters: dict[str, object] | None = None,
        sort: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        return await find_rows(
            api, cache, table_id_or_name, filters=filters, sort=sort, limit=limit
        )
