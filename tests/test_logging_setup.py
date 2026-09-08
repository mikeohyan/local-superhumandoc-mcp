"""The resolved level must reach the logging module, not just the Config."""

import logging
import sys
from pathlib import Path

import pytest

from superhumandoc_mcp.__main__ import _configure_logging
from superhumandoc_mcp.config import Config


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    saved_level, saved_handlers = root.level, root.handlers[:]
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


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
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_can_lower_the_level_again():
    _configure_logging(_config("DEBUG"))
    _configure_logging(_config("WARNING"))
    assert logging.getLogger().level == logging.WARNING


def test_configure_logging_never_writes_to_stdout():
    _configure_logging(_config("INFO"))
    streams = [
        handler.stream
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.StreamHandler)
    ]
    assert streams, "expected basicConfig to install a handler"
    assert sys.stdout not in streams
