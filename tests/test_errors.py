import pytest
from superhumandoc_mcp.errors import (
    AuthFailure, ClientError, NotTransmitted, OutcomeUnknown, Replay,
    ResponseUnusable, StickyRateLimit, UpstreamRefused,
)


def test_unsafe_is_the_default_replay_value() -> None:
    """A call site that forgets must get the conservative answer."""
    assert Replay.UNSAFE.value is False
    assert Replay.SAFE.value is True


@pytest.mark.parametrize(
    "cls",
    [AuthFailure, NotTransmitted, OutcomeUnknown, ResponseUnusable,
     StickyRateLimit, UpstreamRefused],
)
def test_every_failure_is_one_exception_family(cls: type) -> None:
    assert issubclass(cls, ClientError)


def test_outcome_unknown_says_unknown_and_says_it_may_have_applied() -> None:
    """The tool-surface topic requires the word 'unknown'; the failure-policy
    topic adds that the write may already have been applied, because 'unknown'
    alone invites a user to retry by hand and duplicate rows."""
    message = str(OutcomeUnknown("upsert_rows"))
    assert "unknown" in message
    assert "may already have been applied" in message


def test_not_transmitted_does_not_claim_uncertainty() -> None:
    """A connect-phase failure most likely never reached the server. Saying the
    outcome is unknown would be actively false."""
    message = str(NotTransmitted("push_button"))
    assert "unknown" not in message
    assert "did not reach" in message
