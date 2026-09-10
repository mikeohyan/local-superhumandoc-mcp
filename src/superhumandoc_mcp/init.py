"""Scaffold a consuming project: the `init` subcommand.

Offline, credential-free, and run by a person before any MCP session exists.
The rules here are set by the `project-setup` topic; see `_rfc/README.md`.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path
from typing import TextIO

_TEMPLATE = "templates/env.example"
_SERVER_KEY = "superhumandoc"
_REPO = "https://github.com/mikeohyan/local-superhumandoc-mcp"

# A `SHDOC_` assignment at the start of a line, commented out or not, with or
# without an `export` prefix. The same expression finds a key's block in the
# template and decides whether a target file already carries that key, so a
# `.env` this command wrote is recognised by this command on a re-run.
#
# `export` is matched because `dotenv_values` honours it -- measured against
# the pinned dependency, not assumed. Missing it would be the worst bug this
# command could have: a project whose `.env` reads
# `export SHDOC_API_KEY=<token>` would look like it had no such key, get the
# template's empty `SHDOC_API_KEY=` appended, and `dotenv_values` takes the
# LAST assignment -- silently shadowing a live token with an empty string.
# Nothing is deleted, so nothing looks wrong, and the server then dies at
# startup insisting the key is not set.
_ASSIGNMENT = re.compile(
    r"^[ \t]*(?:#[ \t]*)?(?:export[ \t]+)?(SHDOC_[A-Z0-9_]+)[ \t]*="
)

# The ref in a `git+<this repository>@<ref>` argument, with or without a
# `.git` suffix on the repository -- uv treats the two as the same repository,
# and a hand-written registration is as likely to carry it as not. Anchored to
# this server's own repository, so a registration that points this key at a
# fork, or at some other git-hosted server, is never read as a pin of this one.
_PIN = re.compile(re.escape(f"git+{_REPO}") + r"(?:\.git)?@(\S+)\Z")


class InitError(Exception):
    """Scaffolding could not proceed. The message is shown to the user."""


def template_text() -> str:
    """Read the one `.env` template, from wherever this install put it.

    `force-include` re-exposes the repository's root `.env.example` inside the
    wheel at `superhumandoc_mcp/templates/env.example`, which is the path an
    installed server sees. An editable install has no such file: hatchling
    applies `force-include` when it builds a wheel, not when it points a `.pth`
    at `src/`, so the anchor resolves into the source tree and the template is
    two directories above this module under its canonical name. Trying the
    packaged copy first and falling back keeps a single file on disk -- the
    property that makes drift impossible -- while letting the command run for a
    contributor as well as for a user.
    """
    packaged = files("superhumandoc_mcp").joinpath(_TEMPLATE)
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    source = Path(__file__).resolve().parents[2] / ".env.example"
    if source.is_file():
        return source.read_text(encoding="utf-8")
    raise InitError(
        "the .env template is missing from this installation. Looked for "
        f"superhumandoc_mcp/{_TEMPLATE} and {source}."
    )


def template_blocks(text: str) -> list[tuple[str, str]]:
    """Split the template into `(key, block)` pairs, in template order.

    The template is paragraphs separated by blank lines, and a paragraph
    belongs to a key when one of its lines assigns that key -- commented out or
    not, since the two optional keys ship commented. A paragraph that assigns
    nothing is prose: the header explaining the prefix rule, and the footer
    explaining why `SHDOC_ENV_FILE` is absent. Prose is copied verbatim when
    this command creates a file and is never appended to one that already
    exists, because there is no key it could be missing for.

    This makes the paragraph structure of `.env.example` load-bearing rather
    than cosmetic; `tests/test_init_template.py` is what holds it in place.
    """
    blocks: list[tuple[str, str]] = []
    for paragraph in text.split("\n\n"):
        if not paragraph.strip():
            continue
        for line in paragraph.splitlines():
            match = _ASSIGNMENT.match(line)
            if match:
                blocks.append((match.group(1), paragraph.strip("\n")))
                break
    return blocks


def key_present(text: str, key: str) -> bool:
    """Whether `text` already assigns `key` at the start of some line.

    A commented-out assignment counts, and so does an `export` prefix. A
    project that deliberately commented an optional key out has made a
    decision, and appending a second copy would both override it and leave the
    reader two lines to reconcile. An `export` line is a live assignment that
    `dotenv_values` reads, so appending beside it would shadow a real value.
    """
    pattern = re.compile(
        rf"^[ \t]*(?:#[ \t]*)?(?:export[ \t]+)?{re.escape(key)}[ \t]*=",
        re.MULTILINE,
    )
    return pattern.search(text) is not None


@dataclass(frozen=True)
class Outcome:
    """What happened to one artifact, and the line that reports it."""

    artifact: str
    action: str
    detail: str = ""
    stanza: str = ""

    @property
    def line(self) -> str:
        if self.detail:
            return f"{self.action} {self.artifact}: {self.detail}"
        return f"{self.action} {self.artifact}"

    @property
    def failed(self) -> bool:
        return self.action == "failed"


def _append(path: Path, block: str) -> None:
    """Append a block, guaranteeing it starts on a line of its own.

    A file whose last line carries no trailing newline would otherwise have the
    first appended line welded onto it, silently producing a key nothing reads.
    A blank line separates the addition from whatever the project already had,
    so the result reads as an addition rather than as an edit.
    """
    existing = path.read_text(encoding="utf-8")
    prefix = ""
    if existing and not existing.endswith("\n"):
        prefix += "\n"
    if existing.strip():
        prefix += "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(prefix + block.rstrip("\n") + "\n")


def scaffold_env(cwd: Path) -> Outcome:
    """Create `.env` from the template, or append only the keys it lacks.

    Appending overwrites nothing, so it satisfies "never overwrite a byte this
    command did not write" as completely as refusing would, and leaves the user
    better off. A `.env` holding credentials for something else entirely is
    safe: `load_config` consults only `SHDOC_`-prefixed keys, so everything
    else in the file is inert to this server and untouched here.
    """
    path = cwd / ".env"
    template = template_text()
    if not path.exists():
        path.write_text(template, encoding="utf-8")
        # POSIX only in effect: on Windows `chmod` clears the read-only
        # attribute and buys no confidentiality. This file holds a bearer token.
        path.chmod(0o600)
        return Outcome(".env", "wrote")

    existing = path.read_text(encoding="utf-8")
    missing = [
        block for key, block in template_blocks(template)
        if not key_present(existing, key)
    ]
    if not missing:
        return Outcome(".env", "skipped", "already exists")
    _append(path, "\n\n".join(missing))
    # The mode of a file this command did not create stays the project's.
    count = len(missing)
    return Outcome(".env", "appended", f"{count} key{'' if count == 1 else 's'} added")


def server_entry() -> dict[str, dict[str, object]]:
    """The registration stanza, pinned to the version doing the scaffolding.

    The `packaging` topic requires a tag pin rather than a branch and forbids
    moving a published tag, so version X.Y.Z and tag vX.Y.Z name the same code
    permanently: a scaffolded project pins the exact server that scaffolded it.
    In an uninstalled source tree `version` raises `PackageNotFoundError`,
    which `_attempt` treats as this artifact's failure rather than the run's.
    """
    pin = version("superhumandoc-mcp")
    return {
        _SERVER_KEY: {
            "type": "stdio",
            "command": "uvx",
            "args": ["--from", f"git+{_REPO}@v{pin}", "superhumandoc-mcp"],
        }
    }


def entry_fragment() -> str:
    """The stanza as a fragment ready to paste under `mcpServers`.

    Dumped as an object and then unwrapped rather than hand-assembled, so the
    quoting and escaping come from `json` and cannot drift from what
    `scaffold_mcp_json` writes into a file it creates.
    """
    body = json.dumps(server_entry(), indent=2).splitlines()[1:-1]
    return "\n".join(line[2:] for line in body)


def existing_pin(text: str) -> str | None:
    """The ref an existing `.mcp.json` pins this server to, or None.

    None means "could not tell", never "not pinned": malformed JSON, a document
    that is not an object, no `mcpServers` object, no object under this
    server's key, no `args` list, or no argument naming this repository all
    come back as None, and the caller then offers the full stanza exactly as it
    did before the pin was read at all. Reading is the whole of it -- nothing
    here writes, which is what keeps the `project-setup` topic's create-only
    rule for `.mcp.json` intact.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return None
    servers = document.get("mcpServers") if isinstance(document, dict) else None
    entry = servers.get(_SERVER_KEY) if isinstance(servers, dict) else None
    args = entry.get("args") if isinstance(entry, dict) else None
    if not isinstance(args, list):
        return None
    for arg in args:
        if isinstance(arg, str) and (match := _PIN.match(arg)):
            return match.group(1)
    return None


def _indented_fragment() -> str:
    """`entry_fragment`, indented to sit under a report line."""
    return "\n".join(f"  {line}" for line in entry_fragment().splitlines())


def scaffold_mcp_json(cwd: Path) -> Outcome:
    """Create `.mcp.json`, or say what to change in the one already there.

    JSON cannot be appended to: adding a key means parsing and re-serialising
    the whole document, which rewrites bytes this command did not write and
    discards whatever formatting the project chose. So an existing file is left
    exactly as it is, and is never written to here.

    What is printed instead depends on what that file already says. If it
    registers this server at the version doing the scaffolding, there is
    nothing to do. If it registers it at another ref, the report names both and
    the one string to change -- which is the whole of an upgrade. Anything
    else, including a file this command cannot read or parse, gets the full
    stanza, as it did before the existing pin was read at all.
    """
    entry = server_entry()
    path = cwd / ".mcp.json"
    if path.exists():
        return _existing_registration(path)
    path.write_text(
        json.dumps({"mcpServers": entry}, indent=2) + "\n", encoding="utf-8"
    )
    return Outcome(".mcp.json", "wrote")


def _existing_registration(path: Path) -> Outcome:
    """Report on an existing `.mcp.json` without writing to it.

    Nothing here may fail the artifact. A file that cannot be read or decoded
    was still left untouched, which is a skip; turning it into `failed` would
    report an error in a directory where nothing went wrong. `OSError` covers a
    directory at this path, which was a skip before the file was ever read.

    The wording for a differing pin is deliberately neutral about direction:
    an older build's `init` run in a newer project would otherwise tell the
    user to "upgrade" backwards.

    The fallback says to replace an existing entry as well as to add one. A
    registration this command could not read may still carry this server's
    key -- under a URL form it does not recognise, say -- and pasting a second
    entry beside it would leave the document with a duplicate key.
    """
    current = f"v{version('superhumandoc-mcp')}"
    try:
        pinned = existing_pin(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        pinned = None
    if pinned == current:
        return Outcome(
            ".mcp.json", "skipped", f"already registers {_SERVER_KEY} at {current}"
        )
    if pinned is not None:
        stanza = (
            f"  this build is {current}; to run it instead, change the "
            f"argument ending @{pinned} to:\n\n"
            f'      "git+{_REPO}@{current}"\n\n'
            "  or replace the whole entry with:\n\n" + _indented_fragment()
        )
        return Outcome(
            ".mcp.json",
            "skipped",
            f"already registers {_SERVER_KEY}, pinned to @{pinned}",
            stanza,
        )
    stanza = (
        '  add this under the top-level "mcpServers" key, replacing any '
        f'existing "{_SERVER_KEY}" entry:\n\n'
        + _indented_fragment()
    )
    return Outcome(".mcp.json", "skipped", "already exists", stanza)


def scaffold_gitignore(cwd: Path) -> Outcome:
    """Make sure `.env` is ignored, creating the file if there is none.

    Written even outside a git repository: the ignore rule is what keeps the
    token safe on the day the directory becomes one. The presence test is an
    exact match against a stripped line, so a project that ignores `.env`
    through a broader pattern such as `.env*`, or through a global ignore file,
    gets a redundant but harmless extra line rather than a silent skip.
    """
    path = cwd / ".gitignore"
    if not path.exists():
        path.write_text(".env\n", encoding="utf-8")
        return Outcome(".gitignore", "wrote")
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    if ".env" in lines:
        return Outcome(".gitignore", "skipped", "already ignores .env")
    _append(path, ".env")
    return Outcome(".gitignore", "appended", "1 line added")


def _attempt(artifact: str, action: Callable[[], Outcome]) -> Outcome:
    try:
        return action()
    # `UnicodeDecodeError` is a `ValueError`, not an `OSError`, so it has to be
    # named: a `.env` or `.gitignore` saved in a non-UTF-8 encoding would
    # otherwise escape as a traceback and abort the remaining artifacts --
    # exactly the whole-run gate per-artifact independence exists to prevent.
    except (OSError, UnicodeDecodeError, InitError, PackageNotFoundError) as error:
        return Outcome(artifact, "failed", str(error) or type(error).__name__)


def run_init(cwd: Path, out: TextIO, err: TextIO) -> int:
    """Scaffold `cwd`, report on every artifact, and return the exit code.

    Every artifact is attempted even after an earlier one fails. Stopping would
    treat the first artifact as a gate on the others, which is the opposite of
    the per-artifact independence this command is built on, and would leave the
    user knowing less about the directory than a full report gives them.

    The report goes to stdout rather than stderr. That inverts the rule
    `__main__` follows everywhere else, and deliberately: the rule protects the
    MCP transport, this command exits before any transport exists, and the
    report is not a diagnostic beside a protocol stream but the entire output a
    person at a terminal is here for.

    A failure is printed on both streams on purpose -- on stdout so the
    per-artifact report is complete, on stderr so a caller capturing only
    stderr still sees it. Do not collapse that into one stream.
    """
    outcomes = [
        _attempt(".env", lambda: scaffold_env(cwd)),
        _attempt(".mcp.json", lambda: scaffold_mcp_json(cwd)),
        _attempt(".gitignore", lambda: scaffold_gitignore(cwd)),
    ]
    for outcome in outcomes:
        print(outcome.line, file=out)
        if outcome.stanza:
            print(outcome.stanza, file=out)
        if outcome.failed:
            print(
                f"superhumandoc-mcp: could not write {outcome.artifact}: "
                f"{outcome.detail}",
                file=err,
            )
    return 2 if any(outcome.failed for outcome in outcomes) else 0
