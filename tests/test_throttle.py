import pytest

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ClientError
from superhumandoc_mcp.throttle import Bucket, Throttle


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _throttle(clock: FakeClock) -> tuple[Throttle, list[float]]:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(seconds)

    return Throttle(clock=clock, sleep=sleep), slept


async def test_operating_values_sit_below_the_published_figures() -> None:
    """Operating exactly at a published limit is safe only for a bucket's sole
    consumer, and this process is never that."""
    assert Bucket.READ.capacity == 50 and Bucket.READ.window_s == 6.0
    assert Bucket.WRITE.capacity == 5 and Bucket.WRITE.window_s == 6.0
    assert Bucket.DOC_CONTENT_WRITE.capacity == 2
    assert Bucket.DOC_CONTENT_WRITE.window_s == 10.0
    assert Bucket.LIST_DOCS.capacity == 2 and Bucket.LIST_DOCS.window_s == 6.0


async def test_requests_within_the_allowance_do_not_wait() -> None:
    clock = FakeClock()
    throttle, slept = _throttle(clock)
    d = Deadline(clock=clock)
    for _ in range(2):
        await throttle.acquire(Bucket.DOC_CONTENT_WRITE, d)
    assert slept == []


async def test_the_request_over_the_allowance_waits_for_the_window() -> None:
    clock = FakeClock()
    throttle, slept = _throttle(clock)
    d = Deadline(clock=clock)
    for _ in range(3):
        await throttle.acquire(Bucket.DOC_CONTENT_WRITE, d)
    assert slept and slept[0] == pytest.approx(10.0)


async def test_buckets_are_independent() -> None:
    clock = FakeClock()
    throttle, slept = _throttle(clock)
    d = Deadline(clock=clock)
    for _ in range(2):
        await throttle.acquire(Bucket.DOC_CONTENT_WRITE, d)
    await throttle.acquire(Bucket.READ, d)
    assert slept == []


async def test_a_wait_longer_than_the_deadline_is_refused_not_truncated() -> None:
    """Sleeping a partial interval and trying anyway spends what is left of the
    user's budget on an attempt that cannot finish.

    DOC_CONTENT_WRITE's window is only 10.0 s, far shorter than a tool call's
    80 s working budget, so a deadline cannot be driven near expiry without
    the bucket's own window recycling first — advancing the clock enough to
    exhaust the default deadline empties the bucket history along with it and
    the acquire would succeed outright. A deadline sized to expire before the
    bucket's wait can complete reproduces the refusal the plan's docstring
    describes.
    """
    clock = FakeClock()
    throttle, _ = _throttle(clock)
    d = Deadline(total_s=1.0, reserved_tail_s=0.0, clock=clock)
    for _ in range(2):
        await throttle.acquire(Bucket.DOC_CONTENT_WRITE, d)
    with pytest.raises(ClientError):
        await throttle.acquire(Bucket.DOC_CONTENT_WRITE, d)
