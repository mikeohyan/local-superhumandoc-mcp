"""What `init` does to each of the three files it touches."""

import io
import json
import os
import stat
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

import superhumandoc_mcp.init as init_module
from superhumandoc_mcp.init import (
    entry_fragment,
    run_init,
    scaffold_env,
    scaffold_gitignore,
    scaffold_mcp_json,
    server_entry,
    template_text,
)

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


def test_writes_a_registration_pinned_to_a_real_tag(tmp_path: Path) -> None:
    outcome = scaffold_mcp_json(tmp_path)
    assert outcome.line == "wrote .mcp.json"
    document = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    server = document["mcpServers"]["superhumandoc"]
    assert server["type"] == "stdio" and server["command"] == "uvx"
    assert server["args"][0] == "--from"
    assert server["args"][1].startswith("git+https://") and "@v" in server["args"][1]
    assert server["args"][2] == "superhumandoc-mcp"
    assert "env" not in server


def test_the_registration_carries_no_secret(tmp_path: Path) -> None:
    scaffold_mcp_json(tmp_path)
    text = (tmp_path / ".mcp.json").read_text(encoding="utf-8")
    assert "SHDOC_API_KEY" not in text and "SHDOC_DOC_ID" not in text


def test_an_existing_mcp_json_is_untouched_and_the_stanza_is_offered(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".mcp.json"
    before = '{\n    "mcpServers": {"other": {"command": "x"}}\n}\n'
    path.write_text(before, encoding="utf-8")
    outcome = scaffold_mcp_json(tmp_path)
    assert outcome.line == "skipped .mcp.json: already exists"
    assert path.read_text(encoding="utf-8") == before
    assert "mcpServers" in outcome.stanza


def test_the_offered_fragment_is_valid_json_once_wrapped() -> None:
    """It is printed for a human to paste, so it must parse as what would have
    been written rather than merely look like it."""
    assert json.loads("{" + entry_fragment() + "}") == server_entry()


def test_creates_gitignore_when_absent(tmp_path: Path) -> None:
    assert scaffold_gitignore(tmp_path).line == "wrote .gitignore"
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".env\n"


def test_appends_env_to_an_existing_gitignore(tmp_path: Path) -> None:
    path = tmp_path / ".gitignore"
    path.write_text("__pycache__/\n", encoding="utf-8")
    assert scaffold_gitignore(tmp_path).line == "appended .gitignore: 1 line added"
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
    assert "__pycache__/" in lines and ".env" in lines


def test_an_existing_env_line_is_not_duplicated(tmp_path: Path) -> None:
    path = tmp_path / ".gitignore"
    path.write_text("  .env  \n", encoding="utf-8")
    assert scaffold_gitignore(tmp_path).line == "skipped .gitignore: already ignores .env"
    assert path.read_text(encoding="utf-8").count(".env") == 1


def test_a_clean_run_reports_three_lines_and_exits_zero(tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert run_init(tmp_path, out, err) == 0
    assert out.getvalue().splitlines()[:3] == [
        "wrote .env", "wrote .mcp.json", "wrote .gitignore",
    ]
    assert err.getvalue() == ""


def test_re_running_a_finished_directory_is_success(tmp_path: Path) -> None:
    """Finding nothing left to do is the steady state, not an error."""
    out, err = io.StringIO(), io.StringIO()
    run_init(tmp_path, out, err)
    out2, err2 = io.StringIO(), io.StringIO()
    assert run_init(tmp_path, out2, err2) == 0
    assert "skipped .env: already exists" in out2.getvalue()
    assert "skipped .mcp.json: already exists" in out2.getvalue()
    assert "skipped .gitignore: already ignores .env" in out2.getvalue()


def test_one_artifact_failing_does_not_stop_the_others(tmp_path: Path) -> None:
    """Per-artifact independence: a person recovering from a failure needs the
    state of all three, not just the first one that broke."""
    (tmp_path / ".env").mkdir()          # a directory where a file must go
    out, err = io.StringIO(), io.StringIO()
    assert run_init(tmp_path, out, err) == 2
    printed = out.getvalue()
    assert printed.startswith("failed .env:")
    assert "wrote .mcp.json" in printed and "wrote .gitignore" in printed
    assert "superhumandoc-mcp: could not write .env:" in err.getvalue()


def test_the_offered_fragment_starts_at_column_zero() -> None:
    """Parsing it is not a strong enough check on its own.

    The fragment is unwrapped from a dumped object, so it inherits that
    object's indentation unless it is deliberately dedented -- and a fragment
    indented one level too deep still parses as valid JSON while looking
    broken the moment someone pastes it under `mcpServers`. Proven by
    mutation: removing the dedent left every other test green.
    """
    assert entry_fragment().splitlines()[0] == '"superhumandoc": {'


def test_a_missing_installation_fails_only_the_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`importlib.metadata.version` raises in an uninstalled source tree.

    Per-artifact independence makes that the registration's failure rather
    than the run's: the other two artifacts are still written, no half-formed
    `.mcp.json` is left behind, and the exit code still reports that something
    failed. Without this test the whole path is uncovered -- dropping
    `PackageNotFoundError` from the caught set leaves the suite green while
    turning the failure into a traceback.
    """

    def _uninstalled(_name: str) -> str:
        raise PackageNotFoundError("superhumandoc-mcp")

    monkeypatch.setattr(init_module, "version", _uninstalled)
    out, err = io.StringIO(), io.StringIO()

    assert run_init(tmp_path, out, err) == 2

    printed = out.getvalue()
    assert "failed .mcp.json:" in printed
    assert "wrote .env" in printed and "wrote .gitignore" in printed
    assert not (tmp_path / ".mcp.json").exists()
    assert "superhumandoc-mcp: could not write .mcp.json:" in err.getvalue()
