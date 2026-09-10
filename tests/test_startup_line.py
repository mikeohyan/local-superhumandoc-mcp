from pathlib import Path

from importlib.metadata import PackageNotFoundError

import pytest

import superhumandoc_mcp
from superhumandoc_mcp import running_version
from superhumandoc_mcp.config import Config, format_startup_line


def _config(**overrides) -> Config:
    base = dict(
        api_key="secret-token-value",
        doc_id="doc-under-test",
        allow_destructive=False,
        log_level="INFO",
        env_file=Path("/project/.env"),
        sources={"SHDOC_API_KEY": "file", "SHDOC_DOC_ID": "file"},
    )
    base.update(overrides)
    return Config(**base)


def test_names_the_resolved_env_file() -> None:
    assert "/project/.env" in format_startup_line(_config())


def test_names_the_document() -> None:
    assert "doc-under-test" in format_startup_line(_config())


def test_never_contains_the_token() -> None:
    assert "secret-token-value" not in format_startup_line(_config())


def test_reports_the_source_of_each_value() -> None:
    line = format_startup_line(
        _config(sources={"SHDOC_API_KEY": "file", "SHDOC_DOC_ID": "environment"})
    )
    assert "SHDOC_DOC_ID=environment" in line


def test_states_when_destructive_tools_are_off() -> None:
    assert "destructive tools: off" in format_startup_line(_config())


def test_states_when_destructive_tools_are_on() -> None:
    line = format_startup_line(_config(allow_destructive=True))
    assert "destructive tools: ON" in line


def test_names_the_restrictive_rule_rather_than_the_losing_source() -> None:
    """When the file vetoes an enabling environment variable, reporting the
    environment as the source would describe the opposite of what happened."""
    line = format_startup_line(
        _config(sources={"SHDOC_ALLOW_DESTRUCTIVE": "restricted"})
    )
    assert "SHDOC_ALLOW_DESTRUCTIVE=restricted" in line


def test_the_sources_field_is_sorted_rather_than_insertion_ordered() -> None:
    """The keys reach this function from a set union, whose iteration order
    varies between processes. Sorting is what makes two startup lines from
    the same configuration comparable, which is the whole point of the line.
    The sources below are deliberately given in non-alphabetical order.
    """
    line = format_startup_line(
        _config(
            sources={
                "SHDOC_LOG_LEVEL": "file",
                "SHDOC_DOC_ID": "file",
                "SHDOC_API_KEY": "environment",
            }
        )
    )
    assert (
        "[SHDOC_API_KEY=environment SHDOC_DOC_ID=file SHDOC_LOG_LEVEL=file]"
        in line
    )


def test_names_the_running_version() -> None:
    """A bug report that cannot say which build produced it has to be
    reproduced before it can be read."""
    line = format_startup_line(_config(), version="9.8.7")
    assert "version=9.8.7 " in line


def test_the_version_is_derived_from_installed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Derived, not hardcoded, and asked for by the right distribution name.

    A fake value is what proves the derivation: a constant that happened to
    equal today's release would pass a comparison against the real metadata.
    The lookup raises KeyError for any name but the distribution's own.
    """
    monkeypatch.setattr(
        superhumandoc_mcp, "version", lambda name: {"superhumandoc-mcp": "4.5.6"}[name]
    )
    assert "version=4.5.6 " in format_startup_line(_config())


def test_a_missing_version_degrades_to_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An uninstalled source tree has no metadata. That is no reason to
    refuse to serve, so the version reads `unknown` rather than raising."""

    def _uninstalled(_name: str) -> str:
        raise PackageNotFoundError("superhumandoc-mcp")

    monkeypatch.setattr(superhumandoc_mcp, "version", _uninstalled)
    assert running_version() == "unknown"
    assert "version=unknown " in format_startup_line(_config())
