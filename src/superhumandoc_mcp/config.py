"""Configuration resolution.

The server finds its own `.env` because the MCP client cannot be trusted to
supply a working directory and cannot carry a secret. The rules here are set by
the `config-resolution` topic; see `_rfc/README.md`.
"""

from collections.abc import Mapping
from pathlib import Path

_AFFIRMATIVE = frozenset({"1", "true", "yes", "on"})


def parse_affirmative(value: str | None) -> bool:
    """True only for an explicit affirmative. Unrecognised values fail closed."""
    if value is None:
        return False
    return value.strip().lower() in _AFFIRMATIVE


class ConfigError(Exception):
    """Configuration could not be resolved. The message is shown to the user."""


def resolve_env_file(
    cli_path: str | None, environ: Mapping[str, str], cwd: Path
) -> Path | None:
    """Resolve the `.env` from four candidates, in order.

    Candidates 1 and 2 name a path explicitly, so a miss is an error rather than
    a reason to try the next one: an explicit path is a statement of intent, and
    silently resolving elsewhere binds the server to the wrong document with a
    token that works. Candidates 3 and 4 are inferred, so a miss falls through.
    """
    for value, source in ((cli_path, "--env-file"), (environ.get("SHDOC_ENV_FILE"), "SHDOC_ENV_FILE")):
        if value is not None:
            path = Path(value).expanduser()
            if not path.is_file():
                raise ConfigError(
                    f"{source} names {path}, which does not exist. "
                    "Refusing to fall back to another .env."
                )
            return path

    project_dir = environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        candidate = Path(project_dir).expanduser() / ".env"
        if candidate.is_file():
            return candidate

    candidate = cwd / ".env"
    return candidate if candidate.is_file() else None
