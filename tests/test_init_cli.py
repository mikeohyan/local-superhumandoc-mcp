"""The subcommand's wiring, and proof the old invocation still works.

Driven in-process by calling `main()` with a patched `sys.argv`, which is this
suite's established pattern -- there is no subprocess-CLI precedent here.
"""

import sys
from pathlib import Path

import pytest

import superhumandoc_mcp.__main__ as main_module


def test_init_scaffolds_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["superhumandoc-mcp", "init"])

    with pytest.raises(SystemExit) as exit_info:
        main_module.main()

    assert exit_info.value.code == 0
    assert (tmp_path / ".env").is_file()
    assert (tmp_path / ".mcp.json").is_file()
    assert (tmp_path / ".gitignore").is_file()
    assert "wrote .env" in capsys.readouterr().out


def test_init_never_resolves_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`init` is offline and handles no credentials. If it ever reaches
    `load_config` it would fail in an empty directory -- which is precisely the
    directory it exists to serve."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["superhumandoc-mcp", "init"])

    def _explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("init must not resolve configuration")

    monkeypatch.setattr(main_module, "load_config", _explode)

    with pytest.raises(SystemExit) as exit_info:
        main_module.main()
    assert exit_info.value.code == 0


def test_the_bare_invocation_still_reaches_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression this task exists to prevent: every deployed `.mcp.json`
    emits exactly this argv, with no subcommand."""
    env_file = tmp_path / ".env"
    env_file.write_text("SHDOC_API_KEY=k\nSHDOC_DOC_ID=d\n", encoding="utf-8")
    for key in ("SHDOC_API_KEY", "SHDOC_DOC_ID", "SHDOC_LOG_LEVEL",
                "SHDOC_ALLOW_DESTRUCTIVE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        sys, "argv", ["superhumandoc-mcp", "--env-file", str(env_file)]
    )

    async def _fake_identify(config: object) -> None:
        return None

    monkeypatch.setattr(main_module, "_identify", _fake_identify)

    transports: list[str] = []

    class _FakeServer:
        def run(self, transport: str) -> None:
            transports.append(transport)

    monkeypatch.setattr(main_module, "build_server", lambda config: _FakeServer())

    main_module.main()

    assert transports == ["stdio"]


def test_an_unknown_subcommand_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["superhumandoc-mcp", "setup"])
    with pytest.raises(SystemExit) as exit_info:
        main_module.main()
    assert exit_info.value.code != 0


def test_a_failed_artifact_reaches_the_shell_as_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the success path was asserted at the CLI boundary.

    A `main` that ran the scaffolding and then exited 0 regardless left the
    whole suite green, so a shell wrapper checking `$?` would never learn that
    an artifact failed.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").mkdir()
    monkeypatch.setattr(sys, "argv", ["superhumandoc-mcp", "init"])

    with pytest.raises(SystemExit) as exit_info:
        main_module.main()

    assert exit_info.value.code == 2
