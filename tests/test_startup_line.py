from pathlib import Path

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
