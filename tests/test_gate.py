"""Pins for the export concurrency gate.

Two things are checked: that exports of one page never overlap (a
correctness constraint -- the export blob two overlapping exports of the same
page would write to is the same object) and that overlap across distinct
pages is capped rather than eliminated. Also pinned: a crash inside the gate
releases what it held, and a caller with no time left to wait for a slot
fails fast rather than queueing forever. See
`src/superhumandoc_mcp/gate.py`.
"""

import asyncio

import pytest

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ClientError
from superhumandoc_mcp.gate import EXPORT_CONCURRENCY_GLOBAL, ExportGate
from tests.conftest import _fixtures


class _OverlapCounter:
    """Counts how many holders are inside `hold()` at once.

    Each holder increments, yields to the event loop twice with
    `await asyncio.sleep(0)`, then decrements. `asyncio.gather` starts every
    task at once, so any task the gate let through is already runnable before
    this one's first yield; two yields -- rather than one -- give a slower
    task that is still working through its own `for_page` acquisition a
    second chance to catch up and record its increment before the first
    holder decrements. No real delay is involved: `sleep(0)` only reschedules
    the current task to the back of the loop's ready queue.
    """

    def __init__(self) -> None:
        self._current = 0
        self.max_concurrent = 0

    async def hold(self) -> None:
        self._current += 1
        self.max_concurrent = max(self.max_concurrent, self._current)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self._current -= 1


async def test_two_exports_of_one_page_do_not_overlap():
    """The blob they would write is keyed by page and document, not by
    request id, so overlapping exports of one page contend for a single
    object. This is correctness, not pacing."""
    gate, overlap = ExportGate(), _OverlapCounter()

    async def one():
        async with gate.for_page("page-x", Deadline()):
            await overlap.hold()

    await asyncio.gather(one(), one(), one())
    assert overlap.max_concurrent == 1


async def test_exports_of_different_pages_do_overlap():
    """Serialising everything would make the global cap meaningless and a
    multi-page read needlessly serial."""
    gate, overlap = ExportGate(), _OverlapCounter()

    async def one(page):
        async with gate.for_page(page, Deadline()):
            await overlap.hold()

    await asyncio.gather(one("a"), one("b"))
    assert overlap.max_concurrent == 2


async def test_no_more_than_the_global_cap_run_at_once():
    """Ten distinct pages, so the per-page lock is not what is being
    measured. The equality catches an unenforced cap (which would reach ten)
    and an off-by-one (which would reach four), not merely a broken one."""
    gate, overlap = ExportGate(), _OverlapCounter()

    async def one(page):
        async with gate.for_page(page, Deadline()):
            await overlap.hold()

    await asyncio.gather(*(one(f"page-{n}") for n in range(10)))
    assert overlap.max_concurrent == EXPORT_CONCURRENCY_GLOBAL


async def test_a_failure_inside_the_gate_still_releases_it():
    """A lock held by a crashed export would wedge that page for the life of
    the process, and the next call would hang rather than fail."""
    gate = ExportGate()
    with pytest.raises(RuntimeError):
        async with gate.for_page("page-x", Deadline()):
            raise RuntimeError("boom")
    async with gate.for_page("page-x", Deadline()):
        pass  # would hang forever if the lock leaked


async def test_waiting_for_a_slot_is_bounded_by_the_deadline():
    """Otherwise gate-wait time is measurable but not actionable: a call with
    no budget left still queues, and three wedged exports block every later
    read for the life of the process. The refusal names the wait, because a
    bare timeout sends the reader to look at the export instead."""
    clock, _, _ = _fixtures()
    gate = ExportGate()
    async with gate.for_page("page-x", Deadline(clock=clock)):
        with pytest.raises(ClientError) as caught:
            async with gate.for_page("page-x", Deadline(total_s=0.0, clock=clock)):
                pass
    assert "slot" in str(caught.value).lower()
