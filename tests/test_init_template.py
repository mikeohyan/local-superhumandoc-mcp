"""The `.env` template: that it is reachable, and that it parses.

The block parsing here is the load-bearing half. Once `init` appends a single
key's block to an existing `.env`, the paragraph structure of `.env.example`
stops being cosmetic and becomes a format these tests have to hold in place.
"""

import tomllib
from pathlib import Path

from superhumandoc_mcp.init import key_present, template_blocks, template_text

ROOT = Path(__file__).resolve().parents[1]


def test_template_text_is_the_canonical_env_example() -> None:
    assert template_text() == (ROOT / ".env.example").read_text(encoding="utf-8")


def test_pyproject_force_includes_the_template_into_the_wheel() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    force_include = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include[".env.example"] == "superhumandoc_mcp/templates/env.example"


def test_blocks_are_the_four_settable_keys_in_template_order() -> None:
    assert [key for key, _ in template_blocks(template_text())] == [
        "SHDOC_API_KEY",
        "SHDOC_DOC_ID",
        "SHDOC_ALLOW_DESTRUCTIVE",
        "SHDOC_LOG_LEVEL",
    ]


def test_prose_paragraphs_claim_no_key() -> None:
    """The header names SHDOC_ALLOW_DESTRUCTIVE and the footer names
    SHDOC_ENV_FILE, both in running prose. Neither assigns anything, so neither
    is a block, and SHDOC_ENV_FILE must never be appended to a project's .env —
    setting it inside the file the server already found does nothing.
    """
    assert "SHDOC_ENV_FILE" not in [key for key, _ in template_blocks(template_text())]


def test_a_block_carries_its_comment_and_its_assignment_together() -> None:
    blocks = dict(template_blocks(template_text()))
    block = blocks["SHDOC_ALLOW_DESTRUCTIVE"]
    assert block.startswith("# Registers the destructive tools")
    assert "# SHDOC_ALLOW_DESTRUCTIVE=false" in block


def test_key_present_accepts_the_forms_a_real_env_uses() -> None:
    for line in ("SHDOC_LOG_LEVEL=DEBUG", "#SHDOC_LOG_LEVEL=", "# SHDOC_LOG_LEVEL=INFO",
                 "  SHDOC_LOG_LEVEL = INFO"):
        assert key_present(f"OTHER=1\n{line}\n", "SHDOC_LOG_LEVEL"), line


def test_key_present_rejects_a_mention_that_is_not_an_assignment() -> None:
    text = "# SHDOC_LOG_LEVEL is explained above\nSHDOC_LOG_LEVEL_EXTRA=1\n"
    assert not key_present(text, "SHDOC_LOG_LEVEL")


def test_key_present_does_not_honour_export() -> None:
    """`load_config` reads through `dotenv_values`, which ignores `export`, so
    such a line is not a key this server can read and must not suppress the
    append."""
    assert not key_present("export SHDOC_LOG_LEVEL=INFO\n", "SHDOC_LOG_LEVEL")
