"""What `init` does to each of the three files it touches."""

import os
import stat
from pathlib import Path

import pytest

from superhumandoc_mcp.init import scaffold_env, template_text

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")


def test_creates_env_from_the_template(tmp_path: Path) -> None:
    outcome = scaffold_env(tmp_path)
    assert outcome.line == "wrote .env"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == template_text()


@posix_only
def test_a_created_env_is_readable_only_by_its_owner(tmp_path: Path) -> None:
    scaffold_env(tmp_path)
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600


def test_appends_only_the_missing_keys_and_keeps_what_was_there(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("OTHER_TOOL_TOKEN=abc\nSHDOC_API_KEY=already\n", encoding="utf-8")
    outcome = scaffold_env(tmp_path)
    assert outcome.line == "appended .env: 3 keys added"
    text = env.read_text(encoding="utf-8")
    assert text.startswith("OTHER_TOOL_TOKEN=abc\nSHDOC_API_KEY=already\n")
    assert text.count("SHDOC_API_KEY=") == 1
    assert "SHDOC_DOC_ID=" in text and "SHDOC_LOG_LEVEL=INFO" in text


def test_one_missing_key_is_reported_in_the_singular(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "SHDOC_API_KEY=x\nSHDOC_DOC_ID=y\nSHDOC_ALLOW_DESTRUCTIVE=false\n",
        encoding="utf-8",
    )
    assert scaffold_env(tmp_path).line == "appended .env: 1 key added"


def test_a_commented_out_key_counts_as_present(tmp_path: Path) -> None:
    """A project that commented an optional key out made a decision. Appending
    a second copy would both override it and leave two lines to reconcile."""
    env = tmp_path / ".env"
    before = (
        "SHDOC_API_KEY=x\nSHDOC_DOC_ID=y\n"
        "# SHDOC_ALLOW_DESTRUCTIVE=false\n# SHDOC_LOG_LEVEL=INFO\n"
    )
    env.write_text(before, encoding="utf-8")
    outcome = scaffold_env(tmp_path)
    assert outcome.line == "skipped .env: already exists"
    assert env.read_text(encoding="utf-8") == before


def test_an_append_is_shaped_the_same_with_or_without_a_trailing_newline(
    tmp_path: Path,
) -> None:
    """Comparing the two cases is what makes the newline guard testable.

    Asserting only that the first line survived passes even with the guard
    deleted, because the blank-separator branch happens to terminate the line
    too -- proven by mutation, not assumed. What the guard actually buys is
    that a file lacking a final newline gets the same shape as one that has
    it, rather than silently losing the blank line before the addition.
    """
    with_newline, without = tmp_path / "a", tmp_path / "b"
    with_newline.mkdir()
    without.mkdir()
    (with_newline / ".env").write_text("SHDOC_API_KEY=x\n", encoding="utf-8")
    (without / ".env").write_text("SHDOC_API_KEY=x", encoding="utf-8")

    scaffold_env(with_newline)
    scaffold_env(without)

    appended = (with_newline / ".env").read_text(encoding="utf-8")
    assert appended == (without / ".env").read_text(encoding="utf-8")
    assert appended.startswith("SHDOC_API_KEY=x\n\n")


def test_the_footer_prose_is_never_appended(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SHDOC_API_KEY=x\n", encoding="utf-8")
    scaffold_env(tmp_path)
    assert "SHDOC_ENV_FILE" not in env.read_text(encoding="utf-8")


@posix_only
def test_an_existing_envs_mode_is_left_alone(tmp_path: Path) -> None:
    """Changing the mode of a file this command did not create is a mutation
    beyond appending."""
    env = tmp_path / ".env"
    env.write_text("SHDOC_API_KEY=x\n", encoding="utf-8")
    env.chmod(0o644)
    scaffold_env(tmp_path)
    assert stat.S_IMODE(env.stat().st_mode) == 0o644
