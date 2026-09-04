"""Backoff timing, and the header nobody parses for us.

Values are set by the `upstream-api` topic; see `_rfc/README.md`.
"""

import random
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def equal_jitter(
    attempt: int,
    base_s: float,
    factor: float,
    max_s: float,
    rand: Callable[[], float] = random.random,
) -> float:
    """Half the delay, plus a random draw over the other half.

    Buckets are shared beyond this process, so clients that back off in
    lockstep re-collide at exactly the same moment.
    """
    full = min(base_s * (factor**attempt), max_s)
    return full / 2 + rand() * (full / 2)


def parse_retry_after(
    value: str | None, now: datetime | None = None
) -> float | None:
    """Seconds to wait, or None if the header is absent or unreadable.

    Opportunistic by decision: no such header has ever been observed from this
    API, so a parse failure is not an error.
    """
    if not value:
        return None
    text = value.strip()
    try:
        return float(int(text))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return max(0.0, (when - reference).total_seconds())
