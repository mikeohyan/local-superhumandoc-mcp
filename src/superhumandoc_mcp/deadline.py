"""One deadline per tool call.

An MCP tool call has a human waiting on it, so the ceiling is absolute and
every retry is checked against it. The `failure-policy` topic makes this the
single authority: the export and mutation ceilings may consume what remains and
never extend it. See `_rfc/README.md`.
"""

import time
from collections.abc import Callable


class Deadline:
    def __init__(
        self,
        total_s: float = 90.0,
        reserved_tail_s: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._started = clock()
        self._total = total_s
        self._tail = reserved_tail_s

    def _elapsed(self) -> float:
        return self._clock() - self._started

    def remaining(self) -> float:
        """Budget for ordinary requests. Never negative."""
        return max(0.0, self._total - self._tail - self._elapsed())

    def remaining_with_tail(self) -> float:
        """Budget including the reserve, for the terminal fetch of a result
        that has already been paid for."""
        return max(0.0, self._total - self._elapsed())

    def can_afford(self, seconds: float) -> bool:
        return seconds <= self.remaining()

    @property
    def expired(self) -> bool:
        return self.remaining() <= 0.0
