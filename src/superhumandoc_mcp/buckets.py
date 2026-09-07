"""One place that says which bucket an operation belongs to."""

from enum import StrEnum

from superhumandoc_mcp.throttle import Bucket


class Operation(StrEnum):
    LIST_PAGES = "listPages"
    LIST_TABLES = "listTables"
    LIST_COLUMNS = "listColumns"
    LIST_CONTROLS = "listControls"
    LIST_FORMULAS = "listFormulas"
    LIST_PAGE_CONTENT = "listPageContent"
    LIST_ROWS = "listRows"
    GET_ROW = "getRow"
    BEGIN_PAGE_CONTENT_EXPORT = "beginPageContentExport"
    GET_PAGE_CONTENT_EXPORT_STATUS = "getPageContentExportStatus"
    GET_MUTATION_STATUS = "getMutationStatus"
    CREATE_PAGE = "createPage"
    UPDATE_PAGE = "updatePage"
    DELETE_PAGE = "deletePage"
    DELETE_PAGE_CONTENT = "deletePageContent"
    UPSERT_ROWS = "upsertRows"
    UPDATE_ROW = "updateRow"
    DELETE_ROWS = "deleteRows"
    PUSH_BUTTON = "pushButton"


# Provisional. No RFC has ratified this map; see the plan's assumptions.
_BUCKETS: dict[Operation, Bucket] = {
    # Every GET. Nothing in the evidence disputes these.
    Operation.LIST_PAGES: Bucket.READ,
    Operation.LIST_TABLES: Bucket.READ,
    Operation.LIST_COLUMNS: Bucket.READ,
    Operation.LIST_CONTROLS: Bucket.READ,
    Operation.LIST_FORMULAS: Bucket.READ,
    Operation.LIST_PAGE_CONTENT: Bucket.READ,
    Operation.LIST_ROWS: Bucket.READ,
    Operation.GET_ROW: Bucket.READ,
    Operation.GET_PAGE_CONTENT_EXPORT_STATUS: Bucket.READ,
    Operation.GET_MUTATION_STATUS: Bucket.READ,
    # The one bucket decision an RFC has actually made.
    Operation.BEGIN_PAGE_CONTENT_EXPORT: Bucket.WRITE,
    # Doc content changes. Staff name rows explicitly; the page write surface
    # is the most literal reading of "doc content" there is.
    Operation.CREATE_PAGE: Bucket.DOC_CONTENT_WRITE,
    Operation.UPDATE_PAGE: Bucket.DOC_CONTENT_WRITE,
    Operation.DELETE_PAGE: Bucket.DOC_CONTENT_WRITE,
    Operation.DELETE_PAGE_CONTENT: Bucket.DOC_CONTENT_WRITE,
    Operation.UPSERT_ROWS: Bucket.DOC_CONTENT_WRITE,
    Operation.UPDATE_ROW: Bucket.DOC_CONTENT_WRITE,
    Operation.DELETE_ROWS: Bucket.DOC_CONTENT_WRITE,
    # An action invocation rather than a content change, and nothing in the
    # evidence addresses it either way.
    Operation.PUSH_BUTTON: Bucket.WRITE,
}


_UNMAPPED = set(Operation) - set(_BUCKETS)
if _UNMAPPED:  # pragma: no cover - a coding error, not a runtime condition
    raise RuntimeError(
        "Every operation needs a bucket, and these have none: "
        + ", ".join(sorted(op.value for op in _UNMAPPED))
        + ". Adding an operation without a bucket would otherwise surface as a "
        "KeyError inside a tool call, long after the mistake was made."
    )


def bucket_for(operation: Operation) -> Bucket:
    return _BUCKETS[operation]
