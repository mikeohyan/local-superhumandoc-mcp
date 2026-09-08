"""The resolved level must reach the logging module, not just the Config."""

import logging
import sys
from pathlib import Path

import pytest

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
    """The regression this fix exists to prevent: raising the package logger's
    level must not raise root's, or every library's own logging (httpx, for
    one) switches on for a user who only meant to control this server's own
    output.
    """
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    _configure_logging(_config("DEBUG"))
    assert root.level == logging.WARNING


def test_configure_logging_does_not_accumulate_handlers():
    _configure_logging(_config("INFO"))
    _configure_logging(_config("DEBUG"))
    assert len(logging.getLogger(_LOGGER_NAME).handlers) == 1
