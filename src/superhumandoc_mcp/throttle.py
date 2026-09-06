"""Self-throttling, below the published figures rather than at them.

The buckets are shared at minimum per user across all docs, and possibly per
IP, so a second client can exhaust a bucket this limiter believes has headroom.
Operating values are set by the `upstream-api` topic; see `_rfc/README.md`.
"""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from enum import Enum

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ThrottleRefused


class Bucket(Enum):
    READ = (50, 6.0)
    WRITE = (5, 6.0)
    DOC_CONTENT_WRITE = (2, 10.0)
    LIST_DOCS = (2, 6.0)

    @property
    def capacity(self) -> int:
        return self.value[0]

    @property
    def window_s(self) -> float:
        return self.value[1]


class Throttle:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._history: dict[Bucket, deque[float]] = {b: deque() for b in Bucket}

    async def acquire(self, bucket: Bucket, deadline: Deadline) -> None:
        history = self._history[bucket]
        now = self._clock()
        while history and now - history[0] >= bucket.window_s:
            history.popleft()
        if len(history) >= bucket.capacity:
            wait = bucket.window_s - (now - history[0])
            if not deadline.can_afford(wait):
                raise ThrottleRefused(
                    "The local rate limiter would have to wait longer than this "
                    "tool call's remaining time. Batching several changes into "
                    "one call is the effective remedy."
                )
            await self._sleep(wait)
            return await self.acquire(bucket, deadline)
        history.append(self._clock())
