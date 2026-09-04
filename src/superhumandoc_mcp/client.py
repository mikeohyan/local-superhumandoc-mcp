"""The one place every failure decision is made.

Policy lives here rather than at seventeen call sites, because the first tool
written slightly differently would be a silent data-duplication bug. The rules
are set by the `failure-policy` topic and the `upstream-api` topic; see
`_rfc/README.md`.
"""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2

from superhumandoc_mcp.backoff import equal_jitter, parse_retry_after
from superhumandoc_mcp.classify import classify_exception, classify_status
from superhumandoc_mcp.config import Config
from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import (
    AuthFailure, ClientError, FailureClass, NotTransmitted, OutcomeUnknown,
    RateLimited, Replay, ResponseUnusable, StickyRateLimit, UpstreamRefused,
)
from superhumandoc_mcp.throttle import Bucket, Throttle

BASE_URL = "https://docs.superhuman.com/apis/v1"

_BACKOFF_BASE_S = 2.0
_BACKOFF_FACTOR = 3.0
_BACKOFF_MAX_S = 60.0
_REPLAY_BASE_S = 1.0
_RETRY_AFTER_CLAMP_S = (1.0, 60.0)
_MAX_429_RETRIES_READ = 3
_MAX_429_RETRIES_WRITE = 4
_STICKY_429_THRESHOLD = 3
_STICKY_429_WINDOW_S = 120.0
_REPLAYS_PER_REQUEST = 1
_WHOAMI_TIMEOUT = httpx2.Timeout(10.0, connect=5.0)


@dataclass(frozen=True)
class TokenIdentity:
    """What `whoami` can establish. `scoped` says WHETHER the token is
    restricted, never what the restriction covers — that is only learnable by
    making a call and reading a 403."""

    name: str | None
    scoped: bool | None


class DocsClient:
    def __init__(
        self,
        config: Config,
        transport: httpx2.AsyncBaseTransport | None = None,
        throttle: Throttle | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] = random.random,
        timeout: httpx2.Timeout | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # Default-plus-override: naming only connect and read raises ValueError.
        self._timeout = timeout or httpx2.Timeout(30.0, connect=5.0)
        self._http = httpx2.AsyncClient(
            base_url=BASE_URL,
            transport=transport,
            timeout=self._timeout,
            headers={"Authorization": f"Bearer {config.api_key}"},
            follow_redirects=False,
        )
        self._throttle = throttle or Throttle(sleep=sleep)
        self._sleep = sleep
        self._rand = rand
        self._clock = clock
        self._exhausted_budgets = 0
        self._first_exhaustion_at: float | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def whoami(self) -> TokenIdentity:
        """Never retried, on its own short ceiling.

        The ceiling lives in the read timeout because a call with no replays
        has no retry checkpoint for a deadline to act at. Not retrying also
        matters operationally: a supervisor restarting a crash-looping server
        must not be able to amplify one bad launch into repeated calls on a
        bucket shared with every other client using this token.

        Every failure leaves here as a typed failure, including a transport
        one, because startup has to survive having no network at all.
        """
        try:
            response = await self._http.request(
                "GET", "/whoami", timeout=_WHOAMI_TIMEOUT
            )
        except Exception as exc:  # noqa: BLE001 - classified below
            if classify_exception(exc) is FailureClass.REFUSED:
                raise NotTransmitted("whoami") from exc
            raise OutcomeUnknown("whoami") from exc

        failure = classify_status(response.status_code)
        if failure is FailureClass.AUTH:
            raise AuthFailure("whoami", response.status_code)
        if failure is not None:
            raise UpstreamRefused("whoami", response.status_code)
        try:
            body = response.json()
        except ValueError as exc:
            raise ResponseUnusable("whoami") from exc
        if not isinstance(body, dict):
            raise ResponseUnusable("whoami")
        return TokenIdentity(
            name=body.get("tokenName"), scoped=body.get("scoped")
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        bucket: Bucket,
        deadline: Deadline,
        operation: str,
        replay: Replay = Replay.UNSAFE,
        **kwargs: object,
    ) -> httpx2.Response:
        max_429 = (
            _MAX_429_RETRIES_READ
            if bucket is Bucket.READ
            else _MAX_429_RETRIES_WRITE
        )
        # One replay per REQUEST, not per tool call: a blip on the first of a
        # read_page's twenty requests must not strip tolerance from the rest.
        replays_left = _REPLAYS_PER_REQUEST if replay is Replay.SAFE else 0
        attempt_429 = 0

        while True:
            if deadline.expired:
                raise ClientError(
                    f"{operation}: this tool call ran out of time before the "
                    "request could be sent."
                )
            if self._sticky():
                raise StickyRateLimit(operation)

            await self._throttle.acquire(bucket, deadline)
            try:
                response = await self._http.request(method, path, **kwargs)
            except Exception as exc:  # noqa: BLE001 - classified below
                failure = classify_exception(exc)
                if failure is FailureClass.REFUSED:
                    # Believed replay-safe, but the belief is not evidence:
                    # nothing here establishes when httpx2 raises this
                    # relative to bytes reaching the socket, so a declared
                    # UNSAFE call is not replayed on it. What the class earns
                    # is honest wording, not a replay.
                    if replay is Replay.SAFE and replays_left:
                        replays_left -= 1
                        await self._wait_a_replay(deadline, operation)
                        continue
                    raise NotTransmitted(operation) from exc
                if replay is Replay.SAFE and replays_left:
                    replays_left -= 1
                    await self._wait_a_replay(deadline, operation)
                    continue
                raise OutcomeUnknown(operation) from exc

            failure = classify_status(response.status_code)
            if failure is None:
                self._exhausted_budgets = 0
                self._first_exhaustion_at = None
                return response

            if response.status_code == 429:
                # A 429 does not spend the replay budget; the two compose but
                # do not draw on each other.
                if attempt_429 >= max_429:
                    self._note_exhausted_budget()
                    raise RateLimited(operation)
                delay = self._delay_for_429(response, attempt_429)
                # Refused rather than truncated: the deadline is a hard ceiling
                # regardless of retries remaining, and a shortened sleep would
                # return to a bucket sooner than the backoff intended.
                if not deadline.can_afford(delay):
                    raise RateLimited(operation)
                attempt_429 += 1
                await self._sleep(delay)
                continue

            if failure is FailureClass.AUTH:
                raise AuthFailure(operation, response.status_code)
            if failure is FailureClass.TRANSMITTED_UNKNOWN:
                if replay is Replay.SAFE and replays_left:
                    replays_left -= 1
                    await self._wait_a_replay(deadline, operation)
                    continue
                raise OutcomeUnknown(operation)
            raise UpstreamRefused(operation, response.status_code)

    async def _wait_a_replay(self, deadline: Deadline, operation: str) -> None:
        delay = equal_jitter(
            0, _REPLAY_BASE_S, _BACKOFF_FACTOR, _BACKOFF_MAX_S, self._rand
        )
        if not deadline.can_afford(delay):
            raise ClientError(
                f"{operation}: this tool call ran out of time before it could "
                "try again."
            )
        await self._sleep(delay)

    @property
    def exhausted_budgets(self) -> int:
        return self._exhausted_budgets

    def _note_exhausted_budget(self) -> None:
        now = self._clock()
        if (
            self._first_exhaustion_at is not None
            and now - self._first_exhaustion_at > _STICKY_429_WINDOW_S
        ):
            # Outside the window, so this is not a run.
            self._exhausted_budgets = 0
            self._first_exhaustion_at = None
        if self._first_exhaustion_at is None:
            self._first_exhaustion_at = now
        self._exhausted_budgets += 1

    def _sticky(self) -> bool:
        if self._exhausted_budgets < _STICKY_429_THRESHOLD:
            return False
        assert self._first_exhaustion_at is not None
        return self._clock() - self._first_exhaustion_at <= _STICKY_429_WINDOW_S

    def _delay_for_429(self, response: httpx2.Response, attempt: int) -> float:
        # Parsed opportunistically, never required, never trusted unclamped.
        named = parse_retry_after(response.headers.get("retry-after"))
        if named is not None:
            low, high = _RETRY_AFTER_CLAMP_S
            return min(max(named, low), high)
        return equal_jitter(
            attempt, _BACKOFF_BASE_S, _BACKOFF_FACTOR, _BACKOFF_MAX_S, self._rand
        )
