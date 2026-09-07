import pytest

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import RateLimited, UpstreamRefused
from superhumandoc_mcp.polling import await_mutation
from tests.conftest import _fixtures


class _StatusApi:
    """Returns each queued reply in turn. A reply that is an exception is
    raised rather than returned, so a test can queue a 404."""

    def __init__(self, replies):
        self._replies = list(replies)

    async def get_mutation_status(self, request_id, deadline):
        reply = self._replies.pop(0) if self._replies else {"completed": False}
        if isinstance(reply, Exception):
            raise reply
        return reply


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
    """Two budgets on one clock is one budget with a bug. The operation's own
    ceiling is 60s; this deadline has 20, so 20 is what it gets."""
    clock, _, sleep = _fixtures()
    start = clock()
    await await_mutation(
        _StatusApi([{"completed": False}] * 99),
        "r",
        Deadline(total_s=20.0, reserved_tail_s=0.0, clock=clock),
        clock=clock,
        sleep=sleep,
    )
    assert clock() - start <= 20.0


async def test_the_opening_wait_cannot_overrun_the_deadline_either():
    """The first sleep is the one that runs before any loop condition, so it
    is the one that can overshoot unchecked. A mutation polled with almost no
    budget left must not spend more than the budget waiting to start: past
    `remaining()` lies the reserved tail, which exists for the terminal fetch
    of a result already paid for."""
    clock, slept, sleep = _fixtures()
    deadline = Deadline(total_s=11.0, clock=clock)
    api = _StatusApi([{"completed": True}])

    await await_mutation(api, "r", deadline, clock=clock, sleep=sleep)

    assert slept[0] == 1.0
    assert clock() <= 1.0

