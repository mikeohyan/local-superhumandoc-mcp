"""One typed method per read operation. Buckets are resolved here, from the
single map in `buckets.py`, so no call site ever picks one by hand.

`LIST_PAGE_SIZE` is requested and never trusted: the API silently clamps it,
so every paged method follows `nextPageToken` until it is absent or the
caller's cap is reached, and never assumes a page held as many items as were
asked for. `listPageContent` is the one exception to the size parameter's
name — it takes `pageContentLimit`, capped at `PAGE_CONTENT_LIST_LIMIT`,
not `limit`.
"""

from superhumandoc_mcp.buckets import Operation, bucket_for
from superhumandoc_mcp.client import DocsClient
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import Replay

LIST_PAGE_SIZE = 200
PAGE_CONTENT_LIST_LIMIT = 500


class DocsApi:
    """One method per API operation. Buckets are resolved here, never by
    callers. `doc_id` is taken explicitly rather than reached out of the
    client, which keeps its configuration private."""

    def __init__(self, client: DocsClient, doc_id: str) -> None:
        self._client = client
        self._doc_id = doc_id

    async def _paged(
        self,
        path: str,
        operation: Operation,
        deadline: Deadline,
        *,
        limit: int | None = None,
        size_param: str = "limit",
        page_size: int = LIST_PAGE_SIZE,
        params: dict[str, object] | None = None,
    ) -> list[dict]:
        """Follow `nextPageToken` until it is absent or `limit` is reached.

        `limit=None` means the caller has no cap of its own: paging runs to
        exhaustion rather than stopping after one page's worth.
        """
        collected: list[dict] = []
        token: str | None = None
        while limit is None or len(collected) < limit:
            query: dict[str, object] = dict(params or {})
            query[size_param] = (
                page_size if limit is None else min(page_size, limit - len(collected))
            )
            if token:
                query["pageToken"] = token
            response = await self._client.request(
                "GET",
                path,
                operation=operation.value,
                bucket=bucket_for(operation),
                deadline=deadline,
                replay=Replay.SAFE,
                params=query,
            )
            body = response.json()
            collected.extend(body.get("items", []))
            token = body.get("nextPageToken")
            if not token:
                break
        return collected if limit is None else collected[:limit]

    async def list_pages(self, deadline: Deadline) -> list[dict]:
        return await self._paged(
            f"/docs/{self._doc_id}/pages", Operation.LIST_PAGES, deadline
        )

    async def list_tables(self, deadline: Deadline) -> list[dict]:
        return await self._paged(
            f"/docs/{self._doc_id}/tables", Operation.LIST_TABLES, deadline
        )

    async def list_columns(self, table: str, deadline: Deadline) -> list[dict]:
        return await self._paged(
            f"/docs/{self._doc_id}/tables/{table}/columns",
            Operation.LIST_COLUMNS,
            deadline,
        )

    async def list_page_content(self, page: str, deadline: Deadline) -> list[dict]:
        return await self._paged(
            f"/docs/{self._doc_id}/pages/{page}/content",
            Operation.LIST_PAGE_CONTENT,
            deadline,
            size_param="pageContentLimit",
            page_size=PAGE_CONTENT_LIST_LIMIT,
        )

    async def list_rows(
        self,
        table: str,
        deadline: Deadline,
        *,
        limit: int,
        params: dict[str, object] | None = None,
    ) -> list[dict]:
        return await self._paged(
            f"/docs/{self._doc_id}/tables/{table}/rows",
            Operation.LIST_ROWS,
            deadline,
            limit=limit,
            params=params,
        )

    async def get_row(self, table: str, row_id: str, deadline: Deadline) -> dict:
        response = await self._client.request(
            "GET",
            f"/docs/{self._doc_id}/tables/{table}/rows/{row_id}",
            operation=Operation.GET_ROW.value,
            bucket=bucket_for(Operation.GET_ROW),
            deadline=deadline,
            replay=Replay.SAFE,
        )
        return response.json()
