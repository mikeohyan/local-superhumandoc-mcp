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
    """`basicConfig` is a no-op once the root logger has handlers -- and
    pytest's own logging plugin has already installed one before this test
    runs, at level WARNING. Two `_configure_logging` calls that both land on
    WARNING would pass vacuously against that default without proving
    anything moved. Seed the level directly (bypassing `_configure_logging`)
    to a value pytest did not choose, so the assertion can only pass if the
    `force=True` call actually overrode it.
    """
    logging.getLogger().setLevel(logging.DEBUG)
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
