import httpx2
import pytest

from superhumandoc_mcp.client import DocsClient
from superhumandoc_mcp.config import Config
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import (
    AuthFailure, NotTransmitted, OutcomeUnknown, RateLimited, Replay,
    StickyRateLimit, UpstreamRefused,
)
from superhumandoc_mcp.throttle import Bucket


def _config() -> Config:
    from pathlib import Path

    return Config(
        api_key="synthetic-token-not-real",
        doc_id="doc-under-test",
        allow_destructive=False,
        log_level="INFO",
        env_file=Path("/synthetic/.env"),
        sources={},
    )


def _client(handler, **kw) -> DocsClient:
    return DocsClient(
        _config(),
        transport=httpx2.MockTransport(handler),
        sleep=_no_sleep,
        rand=lambda: 1.0,
        **kw,
    )


async def _no_sleep(seconds: float) -> None:
    return None


async def test_the_token_travels_as_a_bearer_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(request.headers)
        return httpx2.Response(200, json={"ok": True})

    client = _client(handler)
    await client.request(
        "GET", "/whoami", bucket=Bucket.READ, replay=Replay.SAFE,
        deadline=Deadline(), operation="probe",
    )
    assert seen["authorization"] == "Bearer synthetic-token-not-real"


async def test_a_safe_call_replays_once_after_a_read_timeout() -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx2.ReadTimeout("lost", request=request)
        return httpx2.Response(200, json={"ok": True})

    client = _client(handler)
    response = await client.request(
        "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
        deadline=Deadline(), operation="find_rows",
    )
    assert response.status_code == 200
    assert len(calls) == 2


async def test_an_unsafe_call_is_never_replayed_after_transmission() -> None:
    """No idempotency keys exist, so replaying an unkeyed upsert duplicates
    rows."""
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        raise httpx2.ReadTimeout("lost", request=request)

    client = _client(handler)
    with pytest.raises(OutcomeUnknown):
        await client.request(
            "POST", "/rows", bucket=Bucket.WRITE, replay=Replay.UNSAFE,
            deadline=Deadline(), operation="upsert_rows",
        )
    assert len(calls) == 1


async def test_only_one_replay_even_when_the_replay_also_fails() -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        raise httpx2.ReadTimeout("lost", request=request)

    client = _client(handler)
    with pytest.raises(OutcomeUnknown):
        await client.request(
            "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=Deadline(), operation="find_rows",
        )
    assert len(calls) == 2


async def test_a_connect_failure_does_not_override_an_unsafe_declaration() -> None:
    """It is believed replay-safe, but nothing establishes when httpx2 raises
    these relative to bytes reaching the socket, so a destructive write is not
    replayed on a belief."""
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        raise httpx2.ConnectError("refused", request=request)

    client = _client(handler)
    with pytest.raises(NotTransmitted):
        await client.request(
            "POST", "/buttons", bucket=Bucket.WRITE, replay=Replay.UNSAFE,
            deadline=Deadline(), operation="push_button",
        )
    assert len(calls) == 1


async def test_a_connect_failure_on_an_unsafe_call_does_not_claim_uncertainty(
) -> None:
    """Saying the outcome is unknown would be actively false, and would invite
    the caller to go looking for a change that was never made."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    client = _client(handler)
    with pytest.raises(NotTransmitted) as excinfo:
        await client.request(
            "POST", "/buttons", bucket=Bucket.WRITE, replay=Replay.UNSAFE,
            deadline=Deadline(), operation="push_button",
        )
    assert "unknown" not in str(excinfo.value)


async def test_a_429_replays_even_an_unsafe_call() -> None:
    """A 429 is refused before execution, so replaying it is safe on every
    method — the one retry case that needs no idempotency key."""
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx2.Response(429)
        return httpx2.Response(200, json={"ok": True})

    client = _client(handler)
    response = await client.request(
        "POST", "/rows", bucket=Bucket.WRITE, replay=Replay.UNSAFE,
        deadline=Deadline(), operation="upsert_rows",
    )
    assert response.status_code == 200
    assert len(calls) == 3


async def test_an_exhausted_429_budget_names_batching_as_the_remedy() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429)

    client = _client(handler)
    with pytest.raises(RateLimited) as excinfo:
        await client.request(
            "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=Deadline(), operation="find_rows",
        )
    assert "Batching" in str(excinfo.value)


async def test_a_429_does_not_spend_the_replay_budget() -> None:
    """Composition is explicit: the two budgets are independent, so a call that
    was rate-limited and then answered still tolerates one transient blip."""
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx2.Response(429)
        if len(calls) == 2:
            raise httpx2.ReadTimeout("lost", request=request)
        return httpx2.Response(200, json={"ok": True})

    client = _client(handler)
    response = await client.request(
        "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
        deadline=Deadline(), operation="find_rows",
    )
    assert response.status_code == 200
    assert len(calls) == 3


async def test_three_exhausted_budgets_with_no_success_read_as_account_level(
) -> None:
    """Sticky counts whole EXHAUSTED budgets, not individual 429 responses.
    Within one call backoff has not had time to clear anything, so three 429s
    inside a single request are ordinary congestion; three consecutive calls
    that each burned a full budget are the account-level signal."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429)

    client = _client(handler)
    for _ in range(3):
        with pytest.raises(RateLimited):
            await client.request(
                "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
                deadline=Deadline(), operation="find_rows",
            )
    with pytest.raises(StickyRateLimit):
        await client.request(
            "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=Deadline(), operation="find_rows",
        )


async def test_a_run_of_exhausted_budgets_older_than_the_window_is_not_sticky(
) -> None:
    """The window is what separates an account-level limit from a busy day."""
    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = FakeClock()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429)

    client = _client(handler, clock=clock)
    for _ in range(3):
        with pytest.raises(RateLimited):
            await client.request(
                "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
                deadline=Deadline(), operation="find_rows",
            )
    clock.now = 500.0
    with pytest.raises(RateLimited):
        await client.request(
            "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=Deadline(), operation="find_rows",
        )


async def test_a_success_clears_the_sticky_counter() -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        if len(calls) > 5:
            return httpx2.Response(200, json={"ok": True})
        return httpx2.Response(429)

    client = _client(handler)
    with pytest.raises(RateLimited):
        await client.request(
            "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=Deadline(), operation="find_rows",
        )
    response = await client.request(
        "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
        deadline=Deadline(), operation="find_rows",
    )
    assert response.status_code == 200
    assert client.exhausted_budgets == 0


async def test_a_504_is_surfaced_immediately_and_never_replayed() -> None:
    """Replaying the identical request fails identically; reshaping it belongs
    to the tool that owns paging."""
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(504)

    client = _client(handler)
    with pytest.raises(UpstreamRefused):
        await client.request(
            "GET", "/rows", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=Deadline(), operation="find_rows",
        )
    assert len(calls) == 1


async def test_a_redirect_is_surfaced_rather_than_followed() -> None:
    """The base URL is pinned; following a redirect would defeat the pin."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"location": "https://elsewhere/"})

    client = _client(handler)
    with pytest.raises(UpstreamRefused):
        await client.request(
            "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=Deadline(), operation="get_doc_overview",
        )


async def test_a_401_is_an_auth_failure_and_is_not_replayed() -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(401)

    client = _client(handler)
    with pytest.raises(AuthFailure):
        await client.request(
            "GET", "/whoami", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=Deadline(), operation="whoami",
        )
    assert len(calls) == 1


async def test_no_error_message_ever_contains_the_token() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500)

    client = _client(handler)
    with pytest.raises(Exception) as excinfo:
        await client.request(
            "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=Deadline(), operation="find_rows",
        )
    assert "synthetic-token-not-real" not in str(excinfo.value)


async def test_an_expired_deadline_stops_before_sending() -> None:
    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = FakeClock()
    deadline = Deadline(clock=clock)
    clock.now = 200.0

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("should not have been sent")

    client = _client(handler)
    with pytest.raises(Exception):
        await client.request(
            "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=deadline, operation="find_rows",
        )


async def test_a_backoff_the_deadline_cannot_afford_is_refused_not_truncated(
) -> None:
    """The deadline is a hard ceiling regardless of retries remaining. Sleeping
    a shortened interval and trying anyway would both overrun the ceiling and
    hit the bucket sooner than the backoff intended."""
    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = FakeClock()
    # 79 s of the 80 s working budget already spent: no backoff interval fits.
    deadline = Deadline(clock=clock)
    calls: list[int] = []
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        clock.now = 79.0
        return httpx2.Response(429)

    client = DocsClient(
        _config(),
        transport=httpx2.MockTransport(handler),
        sleep=record_sleep,
        rand=lambda: 1.0,
        clock=clock,
    )
    with pytest.raises(RateLimited):
        await client.request(
            "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
            deadline=deadline, operation="find_rows",
        )
    assert calls == [1]
    assert slept == []


async def test_the_replay_backoff_stays_under_a_second() -> None:
    """Rule 4 replays on the one-second base, giving 0.5-1.0 s. There is no
    second jitter scheme."""
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx2.ReadTimeout("lost", request=request)
        return httpx2.Response(200, json={"ok": True})

    client = DocsClient(
        _config(),
        transport=httpx2.MockTransport(handler),
        sleep=record_sleep,
        rand=lambda: 0.0,
    )
    await client.request(
        "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
        deadline=Deadline(), operation="find_rows",
    )
    assert slept == [0.5]


async def test_a_retry_after_header_is_honoured_but_clamped() -> None:
    """Opportunistic and never trusted unclamped: no such header has ever been
    observed from this API."""
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx2.Response(429, headers={"retry-after": "9000"})
        return httpx2.Response(200, json={"ok": True})

    client = DocsClient(
        _config(),
        transport=httpx2.MockTransport(handler),
        sleep=record_sleep,
        rand=lambda: 1.0,
    )
    response = await client.request(
        "GET", "/docs", bucket=Bucket.READ, replay=Replay.SAFE,
        deadline=Deadline(), operation="find_rows",
    )
    assert response.status_code == 200
    assert slept == [60.0]
