import pytest

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ClientError, RateLimited, UpstreamRefused
from superhumandoc_mcp.polling import await_mutation
from tests.conftest import _fixtures


class _StatusApi:
    """Returns each queued reply in turn. A reply that is an exception is
    raised rather than returned, so a test can queue a 404."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    async def get_mutation_status(self, request_id, deadline):
        self.calls += 1
        reply = self._replies.pop(0) if self._replies else {"completed": False}
        if isinstance(reply, Exception):
            raise reply
        return reply


class _DeadlineRespectingStatusApi:
    """Answers like `_StatusApi`, but refuses once the deadline has expired --
    the way the real `DocsClient.request` does, rather than answering
    regardless of how much budget is left.

    `_StatusApi` cannot see a defect in the opening sleep: it answers no
    matter what the deadline looks like, so a sleep that silently consumed
    the entire remaining budget before ever asking still "passed" against
    it. This double is what a test needs to measure whether the one question
    the opening-sleep carve-out exists to ask actually got sent, not merely
    whether the loop still has the right shape.
    """

    def __init__(self, reply):
        self._reply = reply
        self.calls = 0

    async def get_mutation_status(self, request_id, deadline):
        if deadline.expired:
            raise ClientError(
                "status: this tool call ran out of time before the request "
                "could be sent."
            )
        self.calls += 1
        return self._reply


async def test_a_completed_mutation_reports_applied():
    clock, _, sleep = _fixtures()
    api = _StatusApi([{"completed": False}, {"completed": True}])
    outcome = await await_mutation(
        api, "r", Deadline(clock=clock), clock=clock, sleep=sleep
    )
    assert outcome.applied is True


async def test_a_warning_is_surfaced_verbatim():
    """Silent degradation is reported here and nowhere else."""
    clock, _, sleep = _fixtures()
    api = _StatusApi([{"completed": True, "warning": "Column X was ignored."}])
    outcome = await await_mutation(
        api, "r", Deadline(clock=clock), clock=clock, sleep=sleep
    )
    assert outcome.warning == "Column X was ignored."


async def test_a_missing_warning_key_is_absent_not_null():
    """The API omits `warning` entirely on a plain completion rather than
    sending an explicit null; a `.get` that assumed the key was always
    present would still pass here, so this pins the absent case too."""
    clock, _, sleep = _fixtures()
    api = _StatusApi([{"completed": True}])
    outcome = await await_mutation(
        api, "r", Deadline(clock=clock), clock=clock, sleep=sleep
    )
    assert outcome.warning is None


async def test_a_404_inside_the_grace_window_means_not_yet():
    """A 404 right after the first poll is the status endpoint's own
    replication lag, not evidence the mutation never happened, so polling
    continues rather than giving up on the first refusal."""
    clock, _, sleep = _fixtures()
    api = _StatusApi([UpstreamRefused("status", 404), {"completed": True}])
    outcome = await await_mutation(
        api, "r", Deadline(clock=clock), clock=clock, sleep=sleep
    )
    assert outcome.applied is True


@pytest.mark.parametrize(
    "replies",
    [
        [UpstreamRefused("status", 404)] * 40,  # 404 past the grace window
        [UpstreamRefused("status", 500)] * 40,  # transport retries exhausted
        [RateLimited("status")] * 40,  # 429 budget exhausted
        [{"completed": False}] * 40,  # deadline exhaustion
    ],
)
async def test_every_non_applied_outcome_says_all_three_things(replies):
    """Unknown, queued and not confirmed, and may already have been applied.
    The third is what stops a model retrying by hand and duplicating rows,
    and it is required of this message, not optional."""
    clock, _, sleep = _fixtures()
    outcome = await await_mutation(
        _StatusApi(replies), "r", Deadline(clock=clock), clock=clock, sleep=sleep
    )
    assert outcome.applied is False
    assert "unknown" in outcome.detail
    assert "queued" in outcome.detail
    assert "may already have been applied" in outcome.detail


async def test_the_interval_backs_off_and_caps():
    clock, slept, sleep = _fixtures()
    await await_mutation(
        _StatusApi([{"completed": False}] * 30),
        "r",
        Deadline(clock=clock),
        clock=clock,
        sleep=sleep,
    )
    assert slept[0] == 3.0
    assert slept[1:4] == [2.0, 3.0, 4.5]
    assert max(slept) <= 15.0


async def test_the_operation_ceiling_never_extends_the_tool_deadline():
    """Two budgets on one clock is one budget with a bug -- but a loose bound
    cannot prove that, because every non-applied exit here returns the same
    `UNKNOWN` (unlike `export.py`'s ceiling, whose sibling test discriminates
    on the *message*: `test_the_export_ceiling_never_extends_the_tool_deadline`).
    With no message to tell branches apart, only the clock can, and it can
    only do that if `can_afford` is not already going to end the loop at the
    same instant regardless of the ceiling.

    `Deadline(total_s=20.0)` -- this suite's old bound -- fails that: with
    only 20s of remaining budget, `deadline.clamp(MUTATION_DEADLINE_S)` here
    equals `remaining()` itself, the exact instant the whole budget is gone,
    a point `can_afford` always reaches first (it refuses once what is left
    is smaller than the next interval, which is strictly before the budget
    hits zero). So `can_afford` ends the loop identically whether or not the
    ceiling exists at all -- deleting `if clock() >= ceiling` outright still
    passes, and so does replacing the clamped ceiling with a bare
    `MUTATION_DEADLINE_S` (that mutation is not merely untested here, it is
    unobservable: whenever `clamp` would lower the ceiling below the
    constant, `can_afford` has already ended the loop at that same clock
    value for an unrelated reason, so no clock-based assertion can ever tell
    the two apart -- verified by running both mutants against every variant
    of this test attempted while fixing this defect).

    A generous deadline (`total_s=100.0`, `remaining()=90.0`) is what makes
    the ceiling the tighter, binding constraint instead: `can_afford`'s own
    cutoff would let this run past 89s (confirmed against a build with the
    `if clock() >= ceiling` check deleted), while the operation's 60s
    ceiling -- only checked between polls, so it is noticed at the next poll
    at t=74.375, not at t=60 itself -- stops it well before that. 80.0 sits
    strictly between the two, so it holds for the real loop and fails for
    the "delete the check" mutant; `test_the_opening_wait_*` tests above
    cover the small-remaining regime this scenario deliberately avoids.
    """
    clock, _, sleep = _fixtures()
    start = clock()
    await await_mutation(
        _StatusApi([{"completed": False}] * 99),
        "r",
        Deadline(total_s=100.0, reserved_tail_s=10.0, clock=clock),
        clock=clock,
        sleep=sleep,
    )
    assert clock() - start <= 80.0


async def test_the_opening_wait_cannot_overrun_the_deadline_either():
    """The first sleep is the one that runs before any loop condition, so it
    is the one that can overshoot unchecked. A mutation polled with almost no
    budget left must not spend more than the budget waiting to start: past
    `remaining()` lies the reserved tail, which exists for the terminal fetch
    of a result already paid for.

    `Deadline(total_s=11.0)` leaves `remaining()` at 1.0s once the reserved
    tail is subtracted. The opening sleep takes half of that (0.5s), not all
    of it -- consuming the whole 1.0s would leave nothing for the one
    question this carve-out exists to ask, which is exactly the defect
    `test_the_opening_sleep_leaves_room_to_ask_its_one_question` below pins
    against a deadline that actually enforces that. This test instead pins
    the opening sleep's own shape: it is bounded by what remains, at half
    rather than all of it, using the same deadline-agnostic double
    (`_StatusApi`) the rest of this module's shape tests use.
    """
    clock, slept, sleep = _fixtures()
    deadline = Deadline(total_s=11.0, clock=clock)
    api = _StatusApi([{"completed": True}])

    outcome = await await_mutation(api, "r", deadline, clock=clock, sleep=sleep)

    assert slept[0] == 0.5
    assert clock() <= 1.0
    assert api.calls == 1
    assert outcome.applied is True
    assert outcome.detail == "applied"


@pytest.mark.parametrize(
    "remaining",
    [1.0, 2.0, 3.0, 3.5, 4.0, 80.0],
)
async def test_the_opening_sleep_leaves_room_to_ask_its_one_question(remaining):
    """The defect this pins: `await sleep(deadline.clamp(MUTATION_INITIAL_SLEEP_S))`
    consumed the *entire* remaining budget whenever remaining was at or below
    `MUTATION_INITIAL_SLEEP_S` (3.0s), so `DocsClient.request` then refused on
    `deadline.expired` before the mutation status was ever asked about --
    `remaining=1.0/2.0/3.0` all made zero HTTP calls against the real client,
    even though the carve-out exists precisely so a call this squeezed still
    gets its one cheap question. `remaining=3.5/4.0/80.0` already worked, and
    stay working.

    `_StatusApi` cannot catch this: it answers regardless of the deadline it
    is handed, which is how `test_a_squeezed_deadline_still_gets_exactly_one_poll`
    (the test this one replaces) passed while pinning a defect that made zero
    real calls -- it asserted the *shape* of the carve-out, not its benefit.
    `_DeadlineRespectingStatusApi` refuses once expired, the way the real
    client does, so it is what would have failed here before the fix.
    """
    clock, _, sleep = _fixtures()
    api = _DeadlineRespectingStatusApi({"completed": True})

    outcome = await await_mutation(
        api,
        "r",
        Deadline(total_s=remaining + 10.0, clock=clock),
        clock=clock,
        sleep=sleep,
    )

    assert api.calls == 1
    assert outcome.applied is True
    assert outcome.detail == "applied"

