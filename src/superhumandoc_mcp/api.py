"""One typed method per read operation. Buckets are resolved here, from the
single map in `buckets.py`, so no call site ever picks one by hand.

`LIST_PAGE_SIZE` is requested and never trusted: the API silently clamps it,
so every paged method follows `nextPageToken` until it is absent or the
caller's cap is reached, and never assumes a page held as many items as were
asked for. `listPageContent` is the one exception to the size parameter's
name — it takes `pageContentLimit`, capped at `PAGE_CONTENT_LIST_LIMIT`,
not `limit`.
"""

from dataclasses import dataclass, field

from superhumandoc_mcp.buckets import Operation, bucket_for
from superhumandoc_mcp.client import DocsClient
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import Replay, UpstreamRefused

LIST_PAGE_SIZE = 200
PAGE_CONTENT_LIST_LIMIT = 500
# The `request-sizing` topic's 504 rule. A 504 on a listing restarts the
# whole pass at half the
# page size rather than resuming: a pageToken ignores every parameter sent
# beside it, so a smaller `limit` cannot take effect part-way through. This
# is the floor that ladder walks down to before giving up.
LIST_PAGE_SIZE_FLOOR = 25


@dataclass(frozen=True)
class Listing:
    """Rows, and whether they are all of them.

    A bare list cannot distinguish a listing that finished from one the
    deadline cut short, and the two must not read alike: returning a short
    result silently would present part of a table as the whole of it.
    """

    rows: list[dict] = field(default_factory=list)
    complete: bool = True
    stopped_because: str | None = None


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
    ) -> Listing:
        """Follow `nextPageToken` until it is absent or `limit` is reached.

        `limit=None` means the caller has no cap of its own: paging runs to
        exhaustion rather than stopping after one page's worth.

        If the deadline runs out after some rows are already in hand, they are
        returned and marked incomplete rather than thrown away with the
        exception. Discarding them would make saying how far it got mean
        nothing. With nothing collected there is nothing to preserve, so the
        request layer's own out-of-time refusal is left to propagate.
        """
        collected: list[dict] = []
        token: str | None = None
        while limit is None or len(collected) < limit:
            if collected and deadline.expired:
                return Listing(collected, False, "the tool call's deadline")
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
        return Listing(collected if limit is None else collected[:limit])

    async def list_pages(self, deadline: Deadline) -> list[dict]:
        listing = await self._paged(
            f"/docs/{self._doc_id}/pages", Operation.LIST_PAGES, deadline
        )
        return listing.rows

    async def list_tables(self, deadline: Deadline) -> list[dict]:
        listing = await self._paged(
            f"/docs/{self._doc_id}/tables", Operation.LIST_TABLES, deadline
        )
        return listing.rows

    async def list_columns(self, table: str, deadline: Deadline) -> list[dict]:
        listing = await self._paged(
            f"/docs/{self._doc_id}/tables/{table}/columns",
            Operation.LIST_COLUMNS,
            deadline,
        )
        return listing.rows

    async def list_page_content(self, page: str, deadline: Deadline) -> list[dict]:
        listing = await self._paged(
            f"/docs/{self._doc_id}/pages/{page}/content",
            Operation.LIST_PAGE_CONTENT,
            deadline,
            size_param="pageContentLimit",
            page_size=PAGE_CONTENT_LIST_LIMIT,
        )
        return listing.rows

    async def list_rows(
        self,
        table: str,
        deadline: Deadline,
        *,
        limit: int,
        params: dict[str, object] | None = None,
    ) -> Listing:
        """Follow `nextPageToken` to `limit`, walking the 504 ladder the
        `request-sizing` topic sets, if the API answers with a gateway timeout.

        Scoped to this method alone, not to paging in general: the 504
        evidence rule 9 is built on is specific to row listing, whose natural
        page size differs from `listPages`/`listTables`/`listColumns`, and
        that topic is explicit that inventing a ladder for those from one
        endpoint's evidence would be extrapolation the RFC means to rule out.

        A 504 halves the page size and restarts the whole pass from no
        token, discarding whatever the failed pass had collected — a
        `pageToken` ignores every other parameter sent beside it, so a
        smaller size cannot take effect part-way through. The floor size is
        attempted once before the ladder gives up; only a size that would
        fall *below* the floor is refused without trying. Only a 504
        ladders: any other refusal — including one raised mid-ladder, such
        as the deadline expiring before the next pass's first request — is
        left to propagate immediately and unchanged.

        A deadline that runs out mid-pass does not raise once rows are in
        hand: the pass returns them marked incomplete, and the ladder stops
        there. Rule 9 keeps the rows from the pass the deadline cut short,
        because they were never distrusted by any response — only the passes
        a 504 ended are discarded.

        No 504 has ever been observed against the real API from this
        client; this path ships tested only against a mock.
        """
        path = f"/docs/{self._doc_id}/tables/{table}/rows"
        page_size = LIST_PAGE_SIZE
        while True:
            try:
                return await self._paged(
                    path,
                    Operation.LIST_ROWS,
                    deadline,
                    limit=limit,
                    page_size=page_size,
                    params=params,
                )
            except UpstreamRefused as refusal:
                if refusal.status != 504:
                    raise
                page_size //= 2
                if page_size < LIST_PAGE_SIZE_FLOOR:
                    raise UpstreamRefused(
                        Operation.LIST_ROWS.value,
                        504,
                        "Repeated gateway timeouts persisted down to the "
                        f"page-size floor of {LIST_PAGE_SIZE_FLOOR}. This "
                        "usually means the document itself is too large to "
                        "list in a single pass, not that the request was "
                        "malformed.",
                    ) from refusal

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

    # --- Writes --------------------------------------------------------
    #
    # One method per mutating operation, following `get_row`'s shape: a
    # single `self._client.request(...)` naming its operation and bucket,
    # and returning `response.json()` — a 202 body carrying the `requestId`
    # the mutation poll loop needs, not the raw response. Every write
    # declares its own `Replay` explicitly rather than relying on the
    # client's default, so the choice is visible at each call site: only
    # GETs and a keyed `upsert_rows` may be replayed after transmission,
    # because this API has no idempotency keys and replaying anything else
    # risks duplicating a change. See the `failure-policy` topic.
    #
    # `rows`/`cells` here are plain `{column_id: value}` mappings — the
    # shape every other write-wave task builds and consumes — translated
    # here into the API's `RowEdit.cells` list of `{column, value}` pairs,
    # which is the only place that translation needs to happen.

    async def create_page(
        self,
        name: str,
        *,
        subtitle: str | None = None,
        parent_page_id: str | None = None,
        canvas: dict | None = None,
        deadline: Deadline,
    ) -> dict:
        """`canvas`, when given, is a `{format, content}` pair — `format` is
        always `html`, per the `tool-surface` topic — and becomes the new
        page's initial canvas content."""
        body: dict[str, object] = {"name": name}
        if subtitle is not None:
            body["subtitle"] = subtitle
        if parent_page_id is not None:
            body["parentPageId"] = parent_page_id
        if canvas is not None:
            body["pageContent"] = {"type": "canvas", "canvasContent": canvas}
        response = await self._client.request(
            "POST",
            f"/docs/{self._doc_id}/pages",
            operation=Operation.CREATE_PAGE.value,
            bucket=bucket_for(Operation.CREATE_PAGE),
            deadline=deadline,
            replay=Replay.UNSAFE,
            json=body,
        )
        return response.json()

    async def update_page(
        self,
        page: str,
        *,
        name: str | None = None,
        canvas: dict | None = None,
        insertion_mode: str = "append",
        element_id: str | None = None,
        deadline: Deadline,
    ) -> dict:
        """`canvas`, when given, is a `{format, content}` pair carrying the
        new content. The API nests it as `contentUpdate.canvasContent`, not
        at the top level, so it is wrapped here rather than left to callers
        to get right.

        `insertion_mode` defaults to `append`. Both `append` and `prepend`
        are additive; `replace` with no `element_id` rewrites the whole page,
        so the default is the one mode that adds at the end and can surprise
        no one. The page-write tools differ from each other in exactly these
        two arguments, so they are parameters rather than something a later
        caller bolts on.

        `element_id` narrows a `replace` to the single named element.
        Measured on 2026-09-07: the named element alone changes, and every
        element ID on the page survives the write, so an ID read earlier in
        the same tool call is still valid afterwards. The failure that
        measurement ruled out was the dangerous one — a field accepted and
        silently ignored would turn an intended one-line edit into a
        whole-page wipe. It is sent only when given, because the API
        distinguishes "this element" from "the entire page" by the field's
        absence rather than by a separate flag.
        """
        body: dict[str, object] = {}
        if name is not None:
            body["name"] = name
        if canvas is not None:
            content_update: dict[str, object] = {
                "insertionMode": insertion_mode,
                "canvasContent": canvas,
            }
            if element_id is not None:
                content_update["elementId"] = element_id
            body["contentUpdate"] = content_update
        response = await self._client.request(
            "PUT",
            f"/docs/{self._doc_id}/pages/{page}",
            operation=Operation.UPDATE_PAGE.value,
            bucket=bucket_for(Operation.UPDATE_PAGE),
            deadline=deadline,
            replay=Replay.UNSAFE,
            json=body,
        )
        return response.json()

    async def delete_page(self, page: str, deadline: Deadline) -> dict:
        response = await self._client.request(
            "DELETE",
            f"/docs/{self._doc_id}/pages/{page}",
            operation=Operation.DELETE_PAGE.value,
            bucket=bucket_for(Operation.DELETE_PAGE),
            deadline=deadline,
            replay=Replay.UNSAFE,
        )
        return response.json()

    async def delete_page_content(
        self,
        page: str,
        *,
        element_ids: list[str] | None = None,
        deadline: Deadline,
    ) -> dict:
        """Omitting `element_ids` (or passing an empty list) deletes every
        element on the page — the API distinguishes "all content" from
        "these elements" by absence, not by a separate flag."""
        body: dict[str, object] = {}
        if element_ids is not None:
            body["elementIds"] = element_ids
        response = await self._client.request(
            "DELETE",
            f"/docs/{self._doc_id}/pages/{page}/content",
            operation=Operation.DELETE_PAGE_CONTENT.value,
            bucket=bucket_for(Operation.DELETE_PAGE_CONTENT),
            deadline=deadline,
            replay=Replay.UNSAFE,
            json=body,
        )
        return response.json()

    async def upsert_rows(
        self,
        table: str,
        rows: list[dict],
        *,
        key_columns: list[str] | None,
        deadline: Deadline,
    ) -> dict:
        """Replay eligibility travels with the call: with `key_columns` set
        the upsert is idempotent and safe to replay after a timeout;
        without them there are no idempotency keys, and replaying would
        duplicate rows. `key_columns` is required (not defaulted) so every
        caller states that choice rather than inheriting it silently."""
        body: dict[str, object] = {
            "rows": [
                {"cells": [{"column": column, "value": value} for column, value in row.items()]}
                for row in rows
            ]
        }
        if key_columns:
            body["keyColumns"] = key_columns
        response = await self._client.request(
            "POST",
            f"/docs/{self._doc_id}/tables/{table}/rows",
            operation=Operation.UPSERT_ROWS.value,
            bucket=bucket_for(Operation.UPSERT_ROWS),
            deadline=deadline,
            replay=Replay.SAFE if key_columns else Replay.UNSAFE,
            json=body,
        )
        return response.json()

    async def update_row(
        self, table: str, row_id: str, cells: dict, deadline: Deadline
    ) -> dict:
        body = {
            "row": {
                "cells": [
                    {"column": column, "value": value} for column, value in cells.items()
                ]
            }
        }
        response = await self._client.request(
            "PUT",
            f"/docs/{self._doc_id}/tables/{table}/rows/{row_id}",
            operation=Operation.UPDATE_ROW.value,
            bucket=bucket_for(Operation.UPDATE_ROW),
            deadline=deadline,
            replay=Replay.UNSAFE,
            json=body,
        )
        return response.json()

    async def delete_rows(
        self, table: str, row_ids: list[str], deadline: Deadline
    ) -> dict:
        response = await self._client.request(
            "DELETE",
            f"/docs/{self._doc_id}/tables/{table}/rows",
            operation=Operation.DELETE_ROWS.value,
            bucket=bucket_for(Operation.DELETE_ROWS),
            deadline=deadline,
            replay=Replay.UNSAFE,
            json={"rowIds": row_ids},
        )
        return response.json()

    async def push_button(
        self, table: str, row_id: str, column: str, deadline: Deadline
    ) -> dict:
        response = await self._client.request(
            "POST",
            f"/docs/{self._doc_id}/tables/{table}/rows/{row_id}/buttons/{column}",
            operation=Operation.PUSH_BUTTON.value,
            bucket=bucket_for(Operation.PUSH_BUTTON),
            deadline=deadline,
            replay=Replay.UNSAFE,
        )
        return response.json()

    async def get_mutation_status(self, request_id: str, deadline: Deadline) -> dict:
        """The one method whose path is not doc-scoped: `/mutationStatus`
        lives at the API root, not under `/docs/{docId}/`. Declares
        `Replay.SAFE` — it is an idempotent GET, and re-reading a status
        never replays the operation being watched."""
        response = await self._client.request(
            "GET",
            f"/mutationStatus/{request_id}",
            operation=Operation.GET_MUTATION_STATUS.value,
            bucket=bucket_for(Operation.GET_MUTATION_STATUS),
            deadline=deadline,
            replay=Replay.SAFE,
        )
        return response.json()
