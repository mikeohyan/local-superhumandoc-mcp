"""The column-schema cache: per-process, per-table, with no expiry in this
read-only wave. `describe_table` (tests/test_tools_reads.py) reads through the
same cache, so its own test pins that reading through it warms rather than
duplicates."""

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.schema_cache import ColumnCache


class _CountingApi:
    """Stands in for `DocsApi`: records one call per `list_columns` invocation
    so a test can assert exactly how many times the API was actually hit."""

    def __init__(self, columns: list[dict] | None = None) -> None:
        self._columns = columns if columns is not None else [{"id": "c-1"}]
        self.calls: list[str] = []

    async def list_columns(self, table: str, deadline: Deadline) -> list[dict]:
        self.calls.append(table)
        return self._columns


async def test_a_second_call_for_the_same_table_does_not_hit_the_api_again():
    """The cache has no expiry in this wave: nothing here writes, so nothing
    here can invalidate it."""
    api = _CountingApi()
    cache = ColumnCache(api)
    await cache.columns("grid-x", Deadline())
    await cache.columns("grid-x", Deadline())
    assert len(api.calls) == 1


async def test_two_tables_are_cached_separately():
    """Warming one table's entry must not satisfy a lookup for another."""
    api = _CountingApi()
    cache = ColumnCache(api)
    await cache.columns("grid-x", Deadline())
    await cache.columns("grid-y", Deadline())
    assert len(api.calls) == 2


async def test_the_cached_columns_are_the_ones_the_api_returned():
    api = _CountingApi(columns=[{"id": "c-1", "name": "Name"}])
    cache = ColumnCache(api)
    columns = await cache.columns("grid-x", Deadline())
    assert columns == [{"id": "c-1", "name": "Name"}]
