"""Serialising exports of one page, and capping how many run at once.

The blob a kickoff writes to is keyed `DOC_EXPORT_RENDERING/{pageId}/{docId}`
-- by page and document, and *not* by request id -- so two in-flight exports
of the same page do not race for two blobs, they contend for one. That makes
`EXPORT_CONCURRENCY_PER_PAGE` a correctness constraint rather than a pacing
choice, and it is the reason this class exists at all: without it, a caller
that reads the same page twice in quick succession could have both exports
overwrite each other's blob before either poll loop reads it back.
`EXPORT_CONCURRENCY_GLOBAL` is a separate, weaker concern -- a judgement about
how much export traffic to generate against the API at once, not something
any single page's correctness depends on. Both values and the reasoning
behind them are set by the `async-operations` topic; see
`docs/reference/api-operational-constants.md` §1.4 and §3.2 item 11.

`for_page` is the only way to reach either limit, and it always acquires the
global semaphore before the per-page lock. That fixed order is what stops two
callers each wanting both from deadlocking on the reverse order -- one
holding page A's lock while waiting on the global cap, the other holding a
global slot while waiting on page A's lock. Because `for_page` is the sole
entry point, no caller can acquire them in the other order and reintroduce
that.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ClientError

EXPORT_CONCURRENCY_PER_PAGE = 1
EXPORT_CONCURRENCY_GLOBAL = 3


class ExportGate:
    def __init__(self, concurrency: int = EXPORT_CONCURRENCY_GLOBAL) -> None:
        self._global = asyncio.Semaphore(concurrency)
        # Not evicted: this server is scoped to one document, so this dict
        # plateaus at that document's page count. Removing an entry while a
        # task is about to acquire it would be a race -- the growth eviction
        # would guard against is already bounded.
        self._per_page: dict[str, asyncio.Semaphore] = {}

    def _lock_for(self, page_id: str) -> asyncio.Semaphore:
        # No `await` between the lookup and the insert, so two tasks calling
        # this for the same new page cannot both see it missing -- this is
        # not racy under cooperative scheduling. Keep it that way.
        lock = self._per_page.get(page_id)
        if lock is None:
            # A Semaphore rather than a Lock so EXPORT_CONCURRENCY_PER_PAGE is
            # the thing being enforced rather than a number that happens to
            # agree with a Lock's fixed capacity of one. A constant nothing
            # reads is a constant that can be changed without effect.
            lock = self._per_page[page_id] = asyncio.Semaphore(
                EXPORT_CONCURRENCY_PER_PAGE
            )
        return lock

    @asynccontextmanager
    async def for_page(self, page_id: str, deadline: Deadline) -> AsyncIterator[None]:
        """Hold the global slot and page `page_id`'s lock for one export.

        Both acquisitions are bounded by `deadline`: queueing for a slot is
        time the deadline can measure but, without this, nothing it could act
        on. A call already out of budget would still queue indefinitely, and
        with only `EXPORT_CONCURRENCY_GLOBAL` slots and no timeout anywhere, a
        few stuck exports would wedge every later `read_page` for the life of
        the process rather than just failing the calls that caused it.
        """
        await _acquire_within(
            self._global, deadline, "an export slot"
        )
        try:
            lock = self._lock_for(page_id)
            await _acquire_within(
                lock, deadline, f"the export slot for page {page_id!r}"
            )
            try:
                yield
            finally:
                lock.release()
        finally:
            self._global.release()


async def _acquire_within(primitive, deadline: Deadline, what: str) -> None:
    try:
        await asyncio.wait_for(primitive.acquire(), timeout=deadline.remaining())
    except TimeoutError:
        raise ClientError(
            f"waited for {what} until this call's remaining time ran out "
            "before one was free"
        ) from None
