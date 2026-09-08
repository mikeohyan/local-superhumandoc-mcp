"""The resolved level must reach the logging module, not just the Config."""

import logging
import sys
from pathlib import Path

import pytest

from superhumandoc_mcp import __main__ as main_module
from superhumandoc_mcp.__main__ import _configure_logging
from superhumandoc_mcp.config import Config

_LOGGER_NAME = "superhumandoc_mcp"


@pytest.fixture(autouse=True)
def _restore_logger_state():
    logger = logging.getLogger(_LOGGER_NAME)
    saved_level = logger.level
    saved_handlers = logger.handlers[:]
    saved_propagate = logger.propagate
    root = logging.getLogger()
    saved_root_level = root.level
    yield
    logger.handlers[:] = saved_handlers
    logger.setLevel(saved_level)
    logger.propagate = saved_propagate
    root.setLevel(saved_root_level)


def _config(level: str) -> Config:
    return Config(
        api_key="k",
        doc_id="d",
        allow_destructive=False,
        log_level=level,
        env_file=Path("/nowhere/.env"),
        sources={},
    )


def test_configure_logging_applies_the_resolved_level():
    _configure_logging(_config("DEBUG"))
    assert logging.getLogger(_LOGGER_NAME).level == logging.DEBUG


def test_configure_logging_can_lower_the_level_again():
    """Seed the package logger to a level `_configure_logging` did not choose,
    so the assertion can only pass if the second call actually moved it, not
    because it happened to already be there.
    """
    logging.getLogger(_LOGGER_NAME).setLevel(logging.DEBUG)
    _configure_logging(_config("WARNING"))
    assert logging.getLogger(_LOGGER_NAME).level == logging.WARNING


def test_configure_logging_never_writes_to_stdout():
    _configure_logging(_config("INFO"))
    streams = [
        handler.stream
        for handler in logging.getLogger(_LOGGER_NAME).handlers
        if isinstance(handler, logging.StreamHandler)
    ]
    assert streams, "expected _configure_logging to install a handler"
    assert sys.stdout not in streams


def test_configure_logging_leaves_the_root_logger_untouched():
    """`_configure_logging` must not change root's own level -- it only sets
    the level on the `superhumandoc_mcp` logger.
    """
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    _configure_logging(_config("DEBUG"))
    assert root.level == logging.WARNING


class _Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_configure_logging_does_not_propagate_to_root():
    """Configuring the `superhumandoc_mcp` logger must neither leak its
    records to root's handlers nor disturb root's own handler list.
    """
    root = logging.getLogger()
    recorder = _Recorder()
    root.addHandler(recorder)
    try:
        _configure_logging(_config("DEBUG"))
        assert recorder in root.handlers
        logging.getLogger(_LOGGER_NAME).debug("should not reach root")
        assert recorder.records == []
    finally:
        root.removeHandler(recorder)


def test_configure_logging_does_not_accumulate_handlers():
    _configure_logging(_config("INFO"))
    _configure_logging(_config("DEBUG"))
    assert len(logging.getLogger(_LOGGER_NAME).handlers) == 1


def test_main_applies_shdoc_log_level_to_the_package_logger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`main` must actually call `_configure_logging`, not merely resolve the
    level into `Config` and leave it unread. `_identify` and `build_server`
    are replaced so the test never touches the network or blocks on stdio.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SHDOC_API_KEY=synthetic-token-not-real\n"
        "SHDOC_DOC_ID=doc-under-test\n"
        "SHDOC_LOG_LEVEL=DEBUG\n"
    )
    for key in (
        "SHDOC_API_KEY", "SHDOC_DOC_ID", "SHDOC_LOG_LEVEL", "SHDOC_ALLOW_DESTRUCTIVE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        sys, "argv", ["superhumandoc-mcp", "--env-file", str(env_file)]
    )

    async def _fake_identify(config):
        return None

    monkeypatch.setattr(main_module, "_identify", _fake_identify)

    run_calls: list[str] = []

    class _FakeServer:
        def run(self, transport: str) -> None:
            run_calls.append(transport)

    monkeypatch.setattr(main_module, "build_server", lambda config: _FakeServer())

    main_module.main()

    assert run_calls == ["stdio"]
    assert logging.getLogger(_LOGGER_NAME).level == logging.DEBUG
