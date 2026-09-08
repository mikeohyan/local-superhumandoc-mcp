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


def test_a_directory_is_not_reported_as_missing(tmp_path: Path) -> None:
    """`is_file()` is false for a directory too, and telling someone a path
    they can see does not exist sends them looking for the wrong problem."""
    (tmp_path / "somedir").mkdir()
    with pytest.raises(ConfigError) as excinfo:
        resolve_env_file(str(tmp_path / "somedir"), {}, tmp_path)
    message = str(excinfo.value)
    assert "directory" in message
    assert "does not exist" not in message


def test_an_empty_path_is_named_as_empty_and_does_not_fall_through(
    tmp_path: Path,
) -> None:
    """An empty value resolves to the current directory, so the old message
    claimed the cwd did not exist. It still must not fall through."""
    (tmp_path / ".env").write_text("SHDOC_DOC_ID=wrong-document\n")
    with pytest.raises(ConfigError) as excinfo:
        resolve_env_file("", {}, tmp_path)
    assert "empty value" in str(excinfo.value)


def test_an_empty_locator_variable_is_also_refused(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("")
    with pytest.raises(ConfigError) as excinfo:
        resolve_env_file(None, {"SHDOC_ENV_FILE": "   "}, tmp_path)
    assert "empty value" in str(excinfo.value)


def test_a_genuinely_missing_path_still_says_so(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        resolve_env_file(str(tmp_path / "typo.env"), {}, tmp_path)
    assert "does not exist" in str(excinfo.value)


def test_the_project_dir_wins_over_cwd_when_both_hold_an_env(
    tmp_path: Path,
) -> None:
    """Both inferred candidates exist at once whenever a session is launched
    in a subdirectory that carries its own .env. Every other test here gives
    exactly one candidate a file, so only this one pins the order between
    them -- and the order is what the launch-directory convention rests on.
    """
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("SHDOC_DOC_ID=the-project-document\n")
    cwd = project / "subdir"
    cwd.mkdir()
    (cwd / ".env").write_text("SHDOC_DOC_ID=the-subdirectory-document\n")
    got = resolve_env_file(None, {"CLAUDE_PROJECT_DIR": str(project)}, cwd)
    assert got == project / ".env"


def test_a_tilde_in_an_explicit_path_is_expanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path from a config file or an .mcp.json arrives unexpanded, because
    no shell touched it. Without expansion `~` is a literal directory name
    and the path is reported as missing while sitting where the user put it.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    named = tmp_path / "named.env"
    named.write_text("")
    assert resolve_env_file("~/named.env", {}, tmp_path) == named


def test_a_tilde_in_the_project_dir_is_expanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same expansion on candidate 3, which is a separate call site."""
    monkeypatch.setenv("HOME", str(tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("")
    got = resolve_env_file(None, {"CLAUDE_PROJECT_DIR": "~/project"}, tmp_path)
    assert got == project / ".env"
