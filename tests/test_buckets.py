"""Test the operation-to-bucket map."""

import pytest

from superhumandoc_mcp.buckets import Operation, bucket_for
from superhumandoc_mcp.throttle import Bucket


def test_every_operation_has_exactly_one_bucket():
    """A missing entry must fail loudly at import, not silently at runtime."""
    for operation in Operation:
        assert isinstance(bucket_for(operation), Bucket)


def test_reads_are_read_bucket():
    for operation in (Operation.LIST_PAGES, Operation.LIST_TABLES,
                      Operation.LIST_COLUMNS, Operation.LIST_PAGE_CONTENT,
                      Operation.LIST_ROWS, Operation.GET_ROW):
        assert bucket_for(operation) is Bucket.READ


def test_row_writes_are_charged_to_the_doc_content_bucket():
    """Staff name upsertRows specifically as a doc content change. Provisional:
    no RFC has ratified this map."""
    for operation in (Operation.UPSERT_ROWS, Operation.UPDATE_ROW,
                      Operation.DELETE_ROWS):
        assert bucket_for(operation) is Bucket.DOC_CONTENT_WRITE


def test_the_export_post_follows_the_one_bucket_decision_that_exists():
    """The `async-operations` topic charges it to the write bucket until
    something measures otherwise."""
    assert bucket_for(Operation.BEGIN_PAGE_CONTENT_EXPORT) is Bucket.WRITE
