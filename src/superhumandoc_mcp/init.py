"""Scaffold a consuming project: the `init` subcommand.

Offline, credential-free, and run by a person before any MCP session exists.
The rules here are set by the `project-setup` topic; see `_rfc/README.md`.
"""

import re
from importlib.resources import files
from pathlib import Path

_TEMPLATE = "templates/env.example"

# A `SHDOC_` assignment at the start of a line, commented out or not. The same
# expression finds a key's block in the template and decides whether a target
# file already carries that key, so a `.env` this command wrote is recognised
# by this command on a re-run. `export KEY=` is deliberately not matched:
# `load_config` reads through `dotenv_values`, which does not honour `export`
# either, so such a line is not a key this server can read.
_ASSIGNMENT = re.compile(r"^[ \t]*#?[ \t]*(SHDOC_[A-Z0-9_]+)[ \t]*=")


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

    A commented-out assignment counts. A project that deliberately commented an
    optional key out has made a decision, and appending a second copy would
    both override it and leave the reader two lines to reconcile.
    """
    pattern = re.compile(rf"^[ \t]*#?[ \t]*{re.escape(key)}[ \t]*=", re.MULTILINE)
    return pattern.search(text) is not None
