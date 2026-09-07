"""The mutation poll loop: one bounded wait for `completed: true`.

A write returns a 202 and a request id; this is what turns that into an
outcome. The `async-operations` topic sets the loop's shape — wait, poll on a
backing-off interval, stop on a terminal answer or a deadline — and the
`failure-policy` topic sets what a non-terminal outcome must say. See
`_rfc/README.md`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ClientError, UpstreamRefused

MUTATION_INITIAL_SLEEP_S = 3.0
MUTATION_POLL_INTERVAL_S = 2.0
MUTATION_POLL_BACKOFF = 1.5
MUTATION_POLL_MAX_INTERVAL_S = 15.0
MUTATION_404_GRACE_S = 30.0
MUTATION_DEADLINE_S = 60.0

UNKNOWN = (
    "The outcome is unknown: the write was queued and not confirmed before "
    "this call ran out of time. It may already have been applied — check "
    "before sending it again, because this API has no idempotency keys and a "
    "repeat may duplicate it."
)
"""Every non-applied exit path returns this exact sentence.

Written once so the three exits — grace window exceeded, a transport failure
mid-poll, and plain deadline exhaustion — cannot drift apart. The third
clause, that the write may already have been applied, is required by the
`failure-policy` topic: "unknown" alone invites a caller to retry by hand and
duplicate a row, since this API has no idempotency keys.
"""


@dataclass(frozen=True)
class MutationOutcome:
    """What a poll settled on. `detail` is `"applied"` on success and
    `UNKNOWN` on every other exit — never a bespoke message, so a caller
    cannot end up depending on wording that only one path produces."""

    applied: bool
    warning: str | None
    detail: str


async def await_mutation(
    api,
    request_id: str,
    deadline: Deadline,
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]],
) -> MutationOutcome:
    """Poll one mutation to completion, or to a bounded give-up.

    The poll itself always runs at least once after the opening sleep, rather
    than being gated by the same ceiling check that ends the loop: a call made
    with almost no budget left must still get to ask its one question, or a
    write placed near its own deadline could report "unknown" without ever
    checking whether the mutation it just sent already applied. Everything
    after that first question is bounded the usual way.

    The operation's own ceiling never extends the tool call's: `clamp` takes
    the lesser, so a deadline that has less than `MUTATION_DEADLINE_S` left
    still governs. A 404 is caught here, around each status call, rather than
    inside the transport's classifier — that table is uniform with no
    per-endpoint carve-out, and a 404 within `MUTATION_404_GRACE_S` of the
    first poll is replication lag on the status endpoint, not evidence the
    mutation never happened.
    """
    started = clock()
    ceiling = started + deadline.clamp(MUTATION_DEADLINE_S)
    grace_ends = started + MUTATION_404_GRACE_S
    interval = MUTATION_POLL_INTERVAL_S
    # Clamped like every other subordinate wait. Unclamped, this is the sleep
    # that would run before any loop condition is even checked and so could
    # overshoot straight into the reserved tail before a single question is
    # asked.
    await sleep(deadline.clamp(MUTATION_INITIAL_SLEEP_S))
    while True:
        try:
            body = await api.get_mutation_status(request_id, deadline)
        except UpstreamRefused as refusal:
            if refusal.status == 404 and clock() < grace_ends:
                pass  # not yet: the status has not replicated
            else:
                return MutationOutcome(False, None, UNKNOWN)
        except ClientError:
            return MutationOutcome(False, None, UNKNOWN)
        else:
            if body.get("completed"):
                return MutationOutcome(True, body.get("warning"), "applied")
        if clock() >= ceiling:
            return MutationOutcome(False, None, UNKNOWN)
        if not deadline.can_afford(interval):
            # Said separately from the ceiling above, because they are
            # different facts: one means the mutation is slow, the other that
            # this tool call had other work to pay for first.
            return MutationOutcome(False, None, UNKNOWN)
        await sleep(interval)
        interval = min(interval * MUTATION_POLL_BACKOFF, MUTATION_POLL_MAX_INTERVAL_S)
