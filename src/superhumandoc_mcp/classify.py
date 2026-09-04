"""Sort a failure by what the server did, not by what came back.

Whether the request was transmitted is the property replay safety depends on,
so it is the axis. Decided by the `failure-policy` topic; see `_rfc/README.md`.
"""

import httpx2

from superhumandoc_mcp.errors import FailureClass

# Nothing reached the application. httpx2 raises these during connection
# establishment, before a request is written.
_CONNECT_PHASE = (httpx2.ConnectTimeout, httpx2.ConnectError)


def classify_exception(exc: Exception) -> FailureClass:
    if isinstance(exc, _CONNECT_PHASE):
        return FailureClass.REFUSED
    # Everything else transport-level happened at or after transmission:
    # read timeouts, write timeouts, mid-response drops, protocol errors.
    return FailureClass.TRANSMITTED_UNKNOWN


def classify_status(status: int) -> FailureClass | None:
    if status < 300:
        return None
    if status == 429:
        return FailureClass.REFUSED
    if status in (401, 403):
        return FailureClass.AUTH
    if status == 504:
        # A gateway timeout here is not a blip. Staff attribute it to an
        # infrastructure limit, and the recorded remedy is a smaller request
        # rather than a later one, so the transport never replays it.
        return FailureClass.ANSWERED
    if 500 <= status < 600:
        return FailureClass.TRANSMITTED_UNKNOWN
    # 3xx and every other 4xx: the server answered. Redirects are surfaced
    # rather than followed, because the base URL is pinned.
    return FailureClass.ANSWERED
