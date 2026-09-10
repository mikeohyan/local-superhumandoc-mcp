"""What the server says when it refuses to start.

Driven in-process by calling `main()` with a patched `sys.argv`, the pattern
`tests/test_init_cli.py` established.
"""

import sys
from pathlib import Path

import pytest

import superhumandoc_mcp
import superhumandoc_mcp.__main__ as main_module


def test_a_configuration_failure_names_the_running_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The commonest refused startup -- no usable .env -- is the one a bug
    report is most likely to be about. It leads with the same `version=` field
    as the startup line, so one pattern finds the build whether the server
    started or not.

    An explicit `--env-file` naming a missing file fails before resolution
    looks anywhere else, so no real `.env` is ever read.
    """
    monkeypatch.setattr(
        superhumandoc_mcp, "version", lambda name: {"superhumandoc-mcp": "4.5.6"}[name]
    )
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "missing.env"
    monkeypatch.setattr(sys, "argv", ["superhumandoc-mcp", "--env-file", str(missing)])

    with pytest.raises(SystemExit) as exit_info:
        main_module.main()

    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("superhumandoc-mcp: version=4.5.6 ")
    assert str(missing) in err
