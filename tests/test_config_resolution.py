from pathlib import Path

import pytest

from superhumandoc_mcp.config import ConfigError, resolve_env_file


def test_cli_path_wins_over_everything(tmp_path: Path) -> None:
    chosen = tmp_path / "chosen.env"
    chosen.write_text("")
    (tmp_path / ".env").write_text("")
    got = resolve_env_file(
        str(chosen), {"SHDOC_ENV_FILE": str(tmp_path / ".env")}, tmp_path
    )
    assert got == chosen


def test_env_var_used_when_no_cli_path(tmp_path: Path) -> None:
    named = tmp_path / "named.env"
    named.write_text("")
    assert resolve_env_file(None, {"SHDOC_ENV_FILE": str(named)}, tmp_path) == named


def test_project_dir_used_when_no_explicit_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("")
    got = resolve_env_file(None, {"CLAUDE_PROJECT_DIR": str(project)}, tmp_path)
    assert got == project / ".env"


def test_cwd_is_the_last_resort(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("")
    assert resolve_env_file(None, {}, tmp_path) == tmp_path / ".env"


def test_returns_none_when_nothing_is_found(tmp_path: Path) -> None:
    assert resolve_env_file(None, {}, tmp_path) is None


def test_missing_cli_path_raises_and_names_the_path(tmp_path: Path) -> None:
    missing = tmp_path / "typo.env"
    with pytest.raises(ConfigError) as excinfo:
        resolve_env_file(str(missing), {}, tmp_path)
    assert str(missing) in str(excinfo.value)


def test_missing_cli_path_does_not_fall_through(tmp_path: Path) -> None:
    """The failure this rule exists to prevent: a typo silently loading
    another project's .env and binding the server to the wrong document."""
    (tmp_path / ".env").write_text("SHDOC_DOC_ID=wrong-document\n")
    with pytest.raises(ConfigError):
        resolve_env_file(str(tmp_path / "typo.env"), {}, tmp_path)


def test_missing_env_var_path_also_raises(tmp_path: Path) -> None:
    missing = tmp_path / "nope.env"
    (tmp_path / ".env").write_text("")
    with pytest.raises(ConfigError) as excinfo:
        resolve_env_file(None, {"SHDOC_ENV_FILE": str(missing)}, tmp_path)
    assert str(missing) in str(excinfo.value)


def test_project_dir_without_an_env_file_falls_through_to_cwd(
    tmp_path: Path,
) -> None:
    """Candidate 3 is inferred, not stated, so a miss is not an error."""
    project = tmp_path / "project"
    project.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".env").write_text("")
    got = resolve_env_file(None, {"CLAUDE_PROJECT_DIR": str(project)}, cwd)
    assert got == cwd / ".env"
