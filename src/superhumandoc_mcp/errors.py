"""Typed failures, and the two enums the policy table is keyed on.

Classification is by whether the request was TRANSMITTED, not by what came
back, because that is the property replay safety depends on. The rules are set
by the `failure-policy` topic; see `_rfc/README.md`.
"""

from enum import Enum


class Replay(Enum):
    """Declared by the caller, never inferred by the client."""

    UNSAFE = False
    SAFE = True


class FailureClass(Enum):
    REFUSED = "refused before execution"
    TRANSMITTED_UNKNOWN = "transmitted, outcome unknown"
    ANSWERED = "answered with a refusal"
    AUTH = "auth"


class ClientError(Exception):
    """Anything the client could not complete. Never carries the token."""


class RateLimited(ClientError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            f"{operation}: the API's rate limit was hit and the retry budget ran "
            "out. These limits are shared across every client using this token, "
            "so this is not necessarily a bug in this server. Batching several "
            "changes into one call is the effective remedy."
        )


class StickyRateLimit(ClientError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            f"{operation}: repeated rate-limit refusals with no success between "
            "them, which indicates an account-level limit that waiting does not "
            "clear. Retrying will not help."
        )


class NotTransmitted(ClientError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            f"{operation}: the connection could not be established, so the "
            "request did not reach the server and nothing was changed."
        )


class OutcomeUnknown(ClientError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            f"{operation}: the connection was lost after the request was sent, "
            "so the outcome is unknown. The change may already have been "
            "applied — check before sending it again, because this API has no "
            "idempotency keys and a repeat may duplicate it."
        )


class UpstreamRefused(ClientError):
    def __init__(self, operation: str, status: int, detail: str = "") -> None:
        super().__init__(
            f"{operation}: the API refused the request with HTTP {status}."
            + (f" {detail}" if detail else "")
        )


class AuthFailure(ClientError):
    # `status` is kept as a value because 401 and 403 mean different things:
    # one is a verdict on the token, the other is what the token teaches about
    # a single call. Callers must not have to read that out of the message.
    def __init__(self, operation: str, status: int) -> None:
        super().__init__(
            f"{operation}: the API rejected the token with HTTP {status}."
        )
        self.status = status


class ResponseUnusable(ClientError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            f"{operation}: the API returned a success status with a body this "
            "client could not read."
        )
