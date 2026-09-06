"""A per-process, per-table cache of column schemas.

The cache never expires and this wave gives it no invalidation path, on
purpose: nothing in this wave writes, so nothing in this wave can make a
cached schema stale. `describe_table` and `get_doc_overview` both read
through the same `ColumnCache`, so whichever tool asks first warms it for
the other rather than paying for the same `listColumns` call twice — and the
row tools of a later wave read through it too.

**Warning for whoever adds the first write in a later wave:** that wave must
invalidate this cache on its own writes, and it cannot key that invalidation
on `updatedAt` alone. The decided evidence records that a mutation reporting
`completed: true` does not mean the next read sees it — the API's own
acknowledgement of a write outruns the document snapshot a subsequent read
returns. A cache that trusts `updatedAt` to notice a change can be shown a
snapshot that has not caught up yet and conclude, wrongly, that nothing
changed.
"""

from superhumandoc_mcp.deadline import Deadline


class ColumnCache:
    """Caches each table's column schema after its first fetch.

    Per-table, not per-document: fetching one table's columns never touches
    another table's cached (or uncached) entry.
    """

    def __init__(self, api) -> None:
        self._api = api
        self._by_table: dict[str, list[dict]] = {}

    async def columns(self, table: str, deadline: Deadline) -> list[dict]:
        if table not in self._by_table:
            self._by_table[table] = await self._api.list_columns(table, deadline)
        return self._by_table[table]
