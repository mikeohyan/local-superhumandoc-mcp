"""Configuration resolution.

The server finds its own `.env` because the MCP client cannot be trusted to
supply a working directory and cannot carry a secret. The rules here are set by
the `config-resolution` topic; see `_rfc/README.md`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import dotenv_values

from superhumandoc_mcp import running_version

if TYPE_CHECKING:
    # Type-checking only: the client imports Config from here, so importing it
    # back at runtime would be a cycle.
    from superhumandoc_mcp.client import TokenIdentity

_AFFIRMATIVE = frozenset({"1", "true", "yes", "on"})
_PREFIX = "SHDOC_"
_REQUIRED = ("SHDOC_API_KEY", "SHDOC_DOC_ID")
_FLAG = "SHDOC_ALLOW_DESTRUCTIVE"
# A locator, not configuration: it says where to look, and the file it names
# has already been read by the time anything below runs.
_LOCATOR = "SHDOC_ENV_FILE"
_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")


def parse_affirmative(value: str | None) -> bool:
    """True only for an explicit affirmative. Unrecognised values fail closed."""
    if value is None:
        return False
    return value.strip().lower() in _AFFIRMATIVE


class ConfigError(Exception):
    """Configuration could not be resolved. The message is shown to the user."""


def _why_unusable(value: str, path: Path) -> str:
    """Say what is actually wrong with a path the user named.

    `is_file()` is false for a missing path, a directory, and an empty value
    that resolves to the current directory alike. Reporting all three as "does
    not exist" tells the user to go looking for a file that is sitting right
    where they put it, which is worse than saying nothing.
    """
    if not value.strip():
        return "was set to an empty value"
    if path.is_dir():
        return f"names {path}, which is a directory rather than a file"
    if path.exists():
        return f"names {path}, which is not a regular file"
    return f"names {path}, which does not exist"


def resolve_env_file(
    cli_path: str | None, environ: Mapping[str, str], cwd: Path
) -> Path | None:
    """Resolve the `.env` from four candidates, in order.

    Candidates 1 and 2 name a path explicitly, so a miss is an error rather than
    a reason to try the next one: an explicit path is a statement of intent, and
    silently resolving elsewhere binds the server to the wrong document with a
    token that works. Candidates 3 and 4 are inferred, so a miss falls through.

    An empty value counts as naming a path, not as leaving one unset. It
    usually comes from a shell line that meant to set one and did not, and
    falling through would resolve somewhere the user never chose -- the exact
    outcome the rule above exists to prevent.
    """
    candidates = (
        (cli_path, "--env-file"),
        (environ.get(_LOCATOR), _LOCATOR),
    )
    for value, source in candidates:
        if value is None:
            continue
        path = Path(value).expanduser()
        if not path.is_file():
            raise ConfigError(
                f"{source} {_why_unusable(value, path)}. "
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


@dataclass(frozen=True)
class Config:
    api_key: str
    doc_id: str
    allow_destructive: bool
    log_level: str
    env_file: Path | None
    sources: dict[str, str] = field(default_factory=dict)


def load_config(
    cli_path: str | None, environ: Mapping[str, str], cwd: Path
) -> Config:
    env_file = resolve_env_file(cli_path, environ, cwd)
    if env_file is None:
        raise ConfigError(
            "No .env found. Looked for --env-file, $SHDOC_ENV_FILE, "
            "$CLAUDE_PROJECT_DIR/.env and ./.env."
        )

    # Only this server's own variables. A project .env legitimately holds other
    # credentials, and none of them belong in this process.
    from_file = {
        key: value
        for key, value in dotenv_values(env_file).items()
        if key.startswith(_PREFIX) and key != _LOCATOR and value is not None
    }
    from_env = {
        k: v
        for k, v in environ.items()
        if k.startswith(_PREFIX) and k != _LOCATOR
    }

    resolved: dict[str, str] = {}
    sources: dict[str, str] = {}
    for key in set(from_file) | set(from_env):
        if key in from_env:
            resolved[key], sources[key] = from_env[key], "environment"
        else:
            resolved[key], sources[key] = from_file[key], "file"

    missing = [key for key in _REQUIRED if not resolved.get(key)]
    if missing:
        # Never interpolate a value here; one of them is the token.
        raise ConfigError(
            f"{', '.join(missing)} not set. Resolved .env: {env_file}"
        )

    # The flag is the one exception to the precedence above: when the file and
    # the environment disagree, the restrictive answer wins, so a stale export
    # cannot arm a destructive tool in a project that disables it.
    present = [v for v in (from_file.get(_FLAG), from_env.get(_FLAG)) if v is not None]
    allow_destructive = bool(present) and all(parse_affirmative(v) for v in present)
    if len(present) == 2 and parse_affirmative(present[0]) != parse_affirmative(
        present[1]
    ):
        # Precedence named the source that lost. Reporting it would tell a
        # reader the environment disabled the tools when the environment asked
        # for them and the file refused, which is the opposite of what happened.
        sources[_FLAG] = "restricted"

    raw_log_level = resolved.get("SHDOC_LOG_LEVEL", "")
    log_level = raw_log_level.strip().upper() or "INFO"
    if log_level not in _LEVELS:
        raise ConfigError(
            f"SHDOC_LOG_LEVEL is {raw_log_level!r}, which is not a level. "
            f"Use one of: {', '.join(_LEVELS)}."
        )

    return Config(
        api_key=resolved["SHDOC_API_KEY"],
        doc_id=resolved["SHDOC_DOC_ID"],
        allow_destructive=allow_destructive,
        log_level=log_level,
        env_file=env_file,
        sources=sources,
    )


def format_startup_line(
    config: Config,
    identity: "TokenIdentity | None" = None,
    version: str | None = None,
) -> str:
    """One line to stderr at startup.

    Every failure mode in resolution is otherwise silent — the wrong file loads,
    or none does, and the first symptom is an authentication error several tool
    calls later. This line turns that mystery into an observation. It must never
    carry the token.

    `identity` is None whenever `whoami` could not establish one, which the
    `failure-policy` topic makes a normal startup rather than a failure: the
    line then says the scope is unknown and the server serves anyway.

    `version` is resolved here when not given, so every caller reports the
    running build without having to remember to; a test passes one to pin it.
    It leads the line because it is the first thing a bug report needs.
    """
    version = version if version is not None else running_version()
    sources = " ".join(f"{key}={origin}" for key, origin in sorted(config.sources.items()))
    state = "ON" if config.allow_destructive else "off"
    if identity is None:
        token = "token: scope unknown"
    else:
        scope = "scoped" if identity.scoped else "unscoped"
        token = f"token: {identity.name or 'unnamed'} ({scope})"
    return (
        f"superhumandoc-mcp: version={version} env={config.env_file} "
        f"doc={config.doc_id} {token} destructive tools: {state} [{sources}]"
    )
