"""Configuration resolution.

The server finds its own `.env` because the MCP client cannot be trusted to
supply a working directory and cannot carry a secret. The rules here are set by
the `config-resolution` topic; see `_rfc/README.md`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

_AFFIRMATIVE = frozenset({"1", "true", "yes", "on"})
_PREFIX = "SHDOC_"
_REQUIRED = ("SHDOC_API_KEY", "SHDOC_DOC_ID")
_FLAG = "SHDOC_ALLOW_DESTRUCTIVE"
# A locator, not configuration: it says where to look, and the file it names
# has already been read by the time anything below runs.
_LOCATOR = "SHDOC_ENV_FILE"


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

    return Config(
        api_key=resolved["SHDOC_API_KEY"],
        doc_id=resolved["SHDOC_DOC_ID"],
        allow_destructive=allow_destructive,
        log_level=resolved.get("SHDOC_LOG_LEVEL", "INFO"),
        env_file=env_file,
        sources=sources,
    )


def format_startup_line(config: Config) -> str:
    """One line to stderr at startup.

    Every failure mode in resolution is otherwise silent — the wrong file loads,
    or none does, and the first symptom is an authentication error several tool
    calls later. This line turns that mystery into an observation. It must never
    carry the token.

    Seam: the `config-resolution` topic also specifies a token name and a
    `scoped` flag on this line. Both come from a `whoami` call, which needs an
    HTTP client this wave does not build — that lands with the `upstream-api`
    topic. Deliberately not implemented here.
    """
    sources = " ".join(f"{key}={origin}" for key, origin in sorted(config.sources.items()))
    state = "ON" if config.allow_destructive else "off"
    return (
        f"superhumandoc-mcp: env={config.env_file} doc={config.doc_id} "
        f"destructive tools: {state} [{sources}]"
    )
