"""Pins for the export concurrency gate.

Two things are checked: that exports of one page never overlap (a
correctness constraint -- the export blob two overlapping exports of the same
page would write to is the same object) and that overlap across distinct
pages is capped rather than eliminated. Also pinned: a crash inside the gate
releases what it held, a caller with no time left to wait for a slot fails
fast rather than queueing forever -- for both the per-page lock and the
global cap, each with its own distinguishable refusal -- and `for_page`
always acquires the global slot before the per-page lock, which is what
makes the two-holder deadlock the module docstring describes impossible. See
`src/superhumandoc_mcp/gate.py`.

Every re-entry that would hang forever if a slot leaked is wrapped in
`asyncio.wait_for` with a small bound, so a leak fails this suite in bounded
time rather than wedging it -- `pytest-timeout` is not a dependency here.
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
    object. This is correctness, not pacing.

    Three concurrent calls on one page necessarily contend for its lock, so a
    leaked per-page lock (the `finally: lock.release()` in `for_page` gone
    missing) would wedge the losers here until `Deadline()`'s real ~80s ran
    out -- not infinite, but far past what a suite this size should ever
    take. Bounding the gather turns that into a prompt failure."""
    gate, overlap = ExportGate(), _OverlapCounter()

    async def one():
        async with gate.for_page("page-x", Deadline()):
            await overlap.hold()

    await asyncio.wait_for(asyncio.gather(one(), one(), one()), timeout=5.0)
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
    and an off-by-one (which would reach four), not merely a broken one.

    Ten calls against a cap of `EXPORT_CONCURRENCY_GLOBAL` necessarily
    contend for the global semaphore, so a leaked global slot (the
    `finally: self._global.release()` in `for_page` gone missing) would
    wedge the losers here until `Deadline()`'s real ~80s ran out. Bounding
    the gather turns that into a prompt failure instead."""
    gate, overlap = ExportGate(), _OverlapCounter()

    async def one(page):
        async with gate.for_page(page, Deadline()):
            await overlap.hold()

    await asyncio.wait_for(
        asyncio.gather(*(one(f"page-{n}") for n in range(10))), timeout=5.0
    )
    assert overlap.max_concurrent == EXPORT_CONCURRENCY_GLOBAL


async def test_a_failure_inside_the_gate_still_releases_it():
    """A lock held by a crashed export would wedge that page for the life of
    the process, and the next call would hang rather than fail. The re-entry
    is wrapped in `asyncio.wait_for` so a leaked lock or slot fails this test
    in bounded time instead of wedging the whole suite -- there is no
    `pytest-timeout` here to catch that for us."""
    gate = ExportGate()
    with pytest.raises(RuntimeError):
        async with gate.for_page("page-x", Deadline()):
            raise RuntimeError("boom")

    async def reacquire() -> None:
        async with gate.for_page("page-x", Deadline()):
            pass  # would hang forever if the lock leaked

    await asyncio.wait_for(reacquire(), timeout=5.0)


async def test_waiting_for_a_slot_is_bounded_by_the_deadline():
    """Otherwise gate-wait time is measurable but not actionable: a call with
    no budget left still queues, and three wedged exports block every later
    read for the life of the process. The refusal names the wait, because a
    bare timeout sends the reader to look at the export instead.

    `total_s=0.0` (giving `remaining() == 0.0`) would make
    `asyncio.wait_for(..., timeout=0)` refuse *any* not-yet-done acquisition
    -- including the global slot, which has two of its three free here. That
    makes the global semaphore time out first and the outer `for_page` this
    test sets up to contend with is never actually reached. `total_s=10.05`
    instead gives `remaining() ~= 0.05`: enough for the free global slot to
    be acquired, but not enough for the page lock the outer call is holding.
    Asserting the page-specific refusal (rather than just "slot" appearing
    somewhere in it) is what makes this test fail if `for_page`'s per-page
    `_acquire_within` call is replaced by a bare `await lock.acquire()`.
    That mutation drops the timeout entirely rather than mis-measuring it,
    so the attempt is wrapped in an outer `asyncio.wait_for`: under that
    mutation the attempt would otherwise hang here rather than raising --
    bypassing the deadline is exactly the wedge this bounding exists to
    prevent -- and the outer bound turns that hang into a prompt failure
    instead of wedging the suite. Under correct code the inner `ClientError`
    is raised well within the outer bound, so it costs nothing here."""
    clock, _, _ = _fixtures()
    gate = ExportGate()

    async def attempt() -> None:
        async with gate.for_page("page-x", Deadline(total_s=10.05, clock=clock)):
            pass

    async with gate.for_page("page-x", Deadline(clock=clock)):
        with pytest.raises(ClientError) as caught:
            await asyncio.wait_for(attempt(), timeout=2.0)
    assert str(caught.value) == (
        "waited for the export slot for page 'page-x' until this call's "
        "remaining time ran out before one was free"
    )


async def test_waiting_for_the_global_cap_is_bounded_by_the_deadline():
    """The per-page test above cannot exercise this: it only ever contends
    one page's lock, so it cannot tell a bare `await self._global.acquire()`
    (bypassing the deadline for the global cap) from correct code -- both let
    the free global slot through immediately. Here all
    `EXPORT_CONCURRENCY_GLOBAL` slots are held by other pages, so a further
    call must wait on the global semaphore itself, and its refusal is
    asserted verbatim to distinguish it from the per-page one -- it does not
    name a page.

    Like the per-page test above, the attempt is wrapped in an outer
    `asyncio.wait_for`: the bare-acquire mutation this guards against drops
    the global semaphore's timeout entirely, which would otherwise hang this
    test rather than fail it."""
    clock, _, _ = _fixtures()
    gate = ExportGate()
    acquired = [asyncio.Event() for _ in range(EXPORT_CONCURRENCY_GLOBAL)]
    release = asyncio.Event()

    async def hold(page: str, ev: asyncio.Event) -> None:
        async with gate.for_page(page, Deadline(clock=clock)):
            ev.set()
            await release.wait()

    async def attempt() -> None:
        async with gate.for_page("page-new", Deadline(total_s=10.05, clock=clock)):
            pass

    holders = [
        asyncio.create_task(hold(f"page-{n}", ev)) for n, ev in enumerate(acquired)
    ]
    try:
        await asyncio.wait_for(
            asyncio.gather(*(ev.wait() for ev in acquired)), timeout=5.0
        )

        with pytest.raises(ClientError) as caught:
            await asyncio.wait_for(attempt(), timeout=2.0)
        assert str(caught.value) == (
            "waited for an export slot until this call's remaining time ran "
            "out before one was free"
        )
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(*holders), timeout=5.0)


async def test_for_page_acquires_the_global_slot_before_the_page_lock():
    """The module docstring says this fixed order is what stops two callers
    each wanting both primitives from deadlocking on the reverse order -- one
    holding page A's lock while waiting on the global cap, the other holding
    a global slot while waiting on page A's lock. Racing two tasks to try to
    trigger that deadlock would only *sometimes* reproduce it, which is worse
    than no test at all: it doesn't fail reliably when `for_page` is broken,
    and a test that hangs instead of failing wedges the suite either way.

    Observing the order directly, by recording which of the two primitives'
    `acquire` is called first, is deterministic instead: it fails outright,
    every run, the moment the per-page lock is acquired before the global
    semaphore."""
    gate = ExportGate()
    order: list[str] = []

    original_global_acquire = gate._global.acquire

    async def spy_global_acquire():
        order.append("global")
        return await original_global_acquire()

    gate._global.acquire = spy_global_acquire

    original_lock_for = gate._lock_for

    def spy_lock_for(page_id: str):
        lock = original_lock_for(page_id)
        if not hasattr(lock, "_order_spied"):
            lock._order_spied = True
            original_lock_acquire = lock.acquire

            async def spy_lock_acquire():
                order.append("page")
                return await original_lock_acquire()

            lock.acquire = spy_lock_acquire
        return lock

    gate._lock_for = spy_lock_for

    async with gate.for_page("page-x", Deadline()):
        pass

    assert order == ["global", "page"]
