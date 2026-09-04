"""Configuration resolution.

The server finds its own `.env` because the MCP client cannot be trusted to
supply a working directory and cannot carry a secret. The rules here are set by
the `config-resolution` topic; see `_rfc/README.md`.
"""

_AFFIRMATIVE = frozenset({"1", "true", "yes", "on"})


def parse_affirmative(value: str | None) -> bool:
    """True only for an explicit affirmative. Unrecognised values fail closed."""
    if value is None:
        return False
    return value.strip().lower() in _AFFIRMATIVE
