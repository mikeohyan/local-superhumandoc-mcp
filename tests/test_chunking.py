"""The chunker: splitting an over-cap row batch and sending the pieces.

`plan_chunks` is pure and synchronous — it only decides the split. Everything
about what happens when a chunk is actually sent (budget, refusals, the local
rate limiter) belongs to `send_chunks`, exercised here through small fakes
built once per test rather than shared, since none of them is used by more
than one task.
"""

import pytest

from superhumandoc_mcp.chunking import CHUNK_COST_ESTIMATE_S, plan_chunks, send_chunks
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ClientError, ThrottleRefused, UpstreamRefused
from superhumandoc_mcp.outcomes import BatchReport, RowOutcome
from superhumandoc_mcp.polling import UNKNOWN as POLL_UNKNOWN
from superhumandoc_mcp.polling import MutationOutcome
from superhumandoc_mcp.sizing import request_wire_bytes
from tests.conftest import _fixtures, _huge, _of_size, _rows, _small, _tiny

_MAX_ROWS = 100
_MAX_ROW_BYTES = 10**6
_MAX_REQUEST_BYTES = 10**7


def _planned(rows: list[dict]) -> list[list[int]]:
    """The three caps this module's own tests use unless a test needs a
    tighter one of its own — generous enough that only the count cap or a
    test's explicit sizing binds."""
    return plan_chunks(
        rows,
        max_rows=_MAX_ROWS,
        max_row_bytes=_MAX_ROW_BYTES,
        max_request_bytes=_MAX_REQUEST_BYTES,
    )


def test_an_oversized_row_is_isolated_in_its_own_chunk():
    chunks = plan_chunks(
        [_small(), _huge(), _small()], max_rows=100, max_row_bytes=100, max_request_bytes=10**6
    )
    assert [len(c) for c in chunks] == [1, 1, 1]


def test_an_empty_batch_sends_nothing():
    assert plan_chunks([], max_rows=100, max_row_bytes=1, max_request_bytes=1) == []


def test_the_count_cap_governs_many_small_rows():
    chunks = plan_chunks(
        [_tiny()] * 250, max_rows=100, max_row_bytes=10**6, max_request_bytes=10**7
    )
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_the_request_cap_governs_rows_that_are_individually_fine():
    """The second byte axis. Each row is well under the row cap; together
    they exceed what one request may carry."""
    rows = [_of_size(200_000)] * 10
    chunks = plan_chunks(rows, max_rows=100, max_row_bytes=10**6, max_request_bytes=1_500_000)
    assert len(chunks) > 1
    assert all(
        request_wire_bytes([rows[i] for i in c]) <= 1_500_000 for c in chunks
    )


def test_chunks_partition_the_input_in_order():
    """Indices, contiguous, ascending, every row exactly once — which is what
    lets an outcome be attributed to the caller's own position."""
    chunks = plan_chunks(
        [_tiny()] * 250, max_rows=100, max_row_bytes=10**6, max_request_bytes=10**7
    )
    assert [i for c in chunks for i in c] == list(range(250))


async def _send_recording(*, refuse_above: int, rows: list[dict]) -> list[list[int]]:
    """A `send` that records every chunk it is asked to attempt, and refuses
    — as an oversized request would — any chunk larger than `refuse_above`.

    The refusal is spelled exactly as the API spells one: a 400 whose message
    is the verbatim `request entity too large` body recorded in
    docs/reference/api-operational-constants.md §2.3. That wording is the only
    discriminator a size refusal has, so a fake that invented its own would
    not be exercising the branch this test believes it is.
    """
    clock, _, _ = _fixtures()
    deadline = Deadline(total_s=90.0, clock=clock)
    report = BatchReport.for_rows(rows)
    sent: list[list[int]] = []

    async def send(indices: list[int]) -> MutationOutcome:
        sent.append(list(indices))
        if len(indices) > refuse_above:
            raise UpstreamRefused(
                "upsert_rows", 400, "request entity too large"
            )
        return MutationOutcome(True, None, "applied")

    await send_chunks(_planned(rows), rows, send, deadline, report=report)
    return sent


async def test_a_size_refusal_halves_and_resends_in_order():
    sent = await _send_recording(refuse_above=2, rows=_rows(4))
    assert [len(c) for c in sent] == [4, 2, 2]


async def _send_with_budget_for(*, chunks: int, rows: list[dict]) -> BatchReport:
    """A `send` that always succeeds but is charged `CHUNK_COST_ESTIMATE_S`
    against the clock, on a deadline sized for exactly `chunks` of those
    charges — so the `chunks + 1`-th chunk fails the admission gate."""
    clock, _, _ = _fixtures()
    deadline = Deadline(total_s=chunks * CHUNK_COST_ESTIMATE_S + 10.0, clock=clock)
    report = BatchReport.for_rows(rows)

    async def send(indices: list[int]) -> MutationOutcome:
        clock.advance(CHUNK_COST_ESTIMATE_S)
        return MutationOutcome(True, None, "applied")

    return await send_chunks(_planned(rows), rows, send, deadline, report=report)


async def test_rows_not_attempted_are_a_suffix_of_the_input():
    """End to end, from the chunker's own output rather than a fixture: the
    caller resends a tail rather than reconstructing a subset."""
    report = await _send_with_budget_for(chunks=1, rows=_rows(250))
    not_attempted = report.indices_with(RowOutcome.NOT_ATTEMPTED)
    assert not_attempted == list(range(min(not_attempted), 250))
    assert report.resume_from() == min(not_attempted)


async def _send_where_each_chunk_takes(
    duration_s: float, *, rows: list[dict], clock, deadline: Deadline
) -> BatchReport:
    report = BatchReport.for_rows(rows)

    async def send(indices: list[int]) -> MutationOutcome:
        clock.advance(duration_s)
        return MutationOutcome(True, None, "applied")

    return await send_chunks(_planned(rows), rows, send, deadline, report=report)


async def test_a_slow_chunk_may_outrun_the_estimate_that_admitted_it():
    """The estimate gates admission; the poll ceiling is twice it. A chunk
    that takes its full ceiling leaves the rest not attempted, and that is
    the designed outcome rather than a miscalculation."""
    clock, _, _ = _fixtures()
    report = await _send_where_each_chunk_takes(
        60.0, rows=_rows(250), clock=clock, deadline=Deadline(total_s=90.0, clock=clock)
    )
    assert report.counts()[RowOutcome.APPLIED] == 100
    assert report.counts()[RowOutcome.NOT_ATTEMPTED] == 150


async def _send_with(
    *, rows: list[dict], throttle_after: int | None = None, deadline: Deadline | None = None
) -> BatchReport:
    """A `send` that succeeds until `throttle_after` calls, then refuses as
    the local limiter would; and that — like the real request layer in
    `client.py`'s `Client.request` — refuses outright once the deadline is
    dead, rather than pretending there was ever a request to make."""
    clock, _, _ = _fixtures()
    if deadline is None:
        deadline = Deadline(total_s=90.0, clock=clock)
    report = BatchReport.for_rows(rows)
    calls = 0

    async def send(indices: list[int]) -> MutationOutcome:
        nonlocal calls
        calls += 1
        if deadline.expired:
            raise ClientError(
                "send: this tool call ran out of time before the request could be sent."
            )
        if throttle_after is not None and calls > throttle_after:
            raise ThrottleRefused(
                "send: the local rate limiter would have to wait longer than this "
                "tool call's remaining time."
            )
        return MutationOutcome(True, None, "applied")

    return await send_chunks(_planned(rows), rows, send, deadline, report=report)


async def test_a_throttle_refusal_folds_into_not_attempted():
    """Losing the account of a whole batch because its last chunk could not
    get a slot is the failure the four outcomes exist to prevent."""
    report = await _send_with(throttle_after=1, rows=_rows(250))
    assert report.counts()[RowOutcome.NOT_ATTEMPTED] > 0
    assert report.counts()[RowOutcome.APPLIED] > 0


async def test_a_dead_deadline_is_not_mistaken_for_a_throttle_refusal():
    """Both were once the same bare error type, and they mean opposite
    things: one is 'no slot', the other is 'no time left at all'."""
    with pytest.raises(ClientError):
        clock, _, _ = _fixtures()
        await _send_with(deadline=Deadline(total_s=0.0, clock=clock), rows=_rows(4))


async def test_an_unapplied_outcome_marks_its_chunk_unknown_not_refused():
    """The API accepted the write and this call merely lost track of it —
    that is not the same as the API having said no, so `REFUSED` would claim
    a verdict nothing supports. The warning belongs only to this chunk's
    rows, per `BatchReport.mark`'s per-call `warning`."""
    clock, _, _ = _fixtures()
    deadline = Deadline(total_s=90.0, clock=clock)
    rows = _rows(3)
    report = BatchReport.for_rows(rows)

    async def send(indices: list[int]) -> MutationOutcome:
        return MutationOutcome(False, "queued but not confirmed", POLL_UNKNOWN)

    result = await send_chunks(_planned(rows), rows, send, deadline, report=report)
    assert result.indices_with(RowOutcome.UNKNOWN) == [0, 1, 2]
    assert result.indices_with(RowOutcome.REFUSED) == []
    as_dict = result.as_dict()
    assert all(r["warning"] == "queued but not confirmed" for r in as_dict["rows"])


async def test_a_refusal_that_is_not_about_size_is_not_halved():
    """Halving answers one question — "was that request too big?" — and a 403
    or a missing table is not that question. Splitting one anyway would ask it
    again on each half, up to seven more times for a full batch, and get the
    same answer every time while spending rate budget and deadline to relearn
    what the first response already said. The chunk is refused where it
    stands, and the batch carries on to the next one.
    """
    clock, _, _ = _fixtures()
    deadline = Deadline(total_s=90.0, clock=clock)
    rows = _rows(4)
    report = BatchReport.for_rows(rows)
    sent: list[list[int]] = []

    async def send(indices: list[int]) -> MutationOutcome:
        sent.append(list(indices))
        raise UpstreamRefused("upsert_rows", 403, "not authorised for this table")

    await send_chunks(_planned(rows), rows, send, deadline, report=report)

    assert sent == [[0, 1, 2, 3]]
    assert report.counts()[RowOutcome.REFUSED] == 4

