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


def test_reading_one_page_is_charged_to_the_read_bucket():
    """`read_page` needs a page's contentType and updatedAt before it can
    decide whether to export at all, so this runs on every page read and
    belongs on the cheapest bucket."""
    assert bucket_for(Operation.GET_PAGE) is Bucket.READ


def test_no_operation_is_spelled_twice():
    """A StrEnum aliases rather than raising on a duplicate value, so a second
    spelling of an existing operation is invisible at import and shows up only
    as two names for one bucket decision.

    The check has to go through `__members__`. Iterating the enum yields only
    canonical members and silently skips aliases, so a test that compares
    `[m.value for m in Operation]` against its own set can never fail --
    it would pass a module with the duplicate it was written to catch.
    """
    aliases = [
        name for name, member in Operation.__members__.items() if member.name != name
    ]
    assert aliases == []
