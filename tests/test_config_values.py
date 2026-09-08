from pathlib import Path

import pytest

from superhumandoc_mcp.config import ConfigError, load_config, parse_affirmative


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", " On "])
def test_affirmative_values_enable(value: str) -> None:
    assert parse_affirmative(value) is True


@pytest.mark.parametrize(
    "value", [None, "", "0", "false", "no", "off", "FALSE", "maybe", "2", "y"]
)
def test_everything_else_disables(value: str | None) -> None:
    assert parse_affirmative(value) is False


REQUIRED = "SHDOC_API_KEY=file-token\nSHDOC_DOC_ID=file-doc\n"


def _env_file(tmp_path: Path, body: str = REQUIRED) -> Path:
    path = tmp_path / ".env"
    path.write_text(body)
    return path


def test_reads_required_values_from_the_file(tmp_path: Path) -> None:
    _env_file(tmp_path)
    config = load_config(None, {}, tmp_path)
    assert config.api_key == "file-token"
    assert config.doc_id == "file-doc"


def test_real_environment_wins_over_the_file(tmp_path: Path) -> None:
    _env_file(tmp_path)
    config = load_config(None, {"SHDOC_DOC_ID": "env-doc"}, tmp_path)
    assert config.doc_id == "env-doc"
    assert config.sources["SHDOC_DOC_ID"] == "environment"
    assert config.sources["SHDOC_API_KEY"] == "file"


def test_non_prefixed_keys_are_ignored(tmp_path: Path) -> None:
    """A project .env holds other projects' secrets. They must not be read."""
    _env_file(tmp_path, REQUIRED + "AWS_SECRET_ACCESS_KEY=not-ours\nDB_PASSWORD=nope\n")
    config = load_config(None, {}, tmp_path)
    assert not hasattr(config, "aws_secret_access_key")
    assert all(key.startswith("SHDOC_") for key in config.sources)


def test_env_file_is_not_exported_to_the_process(tmp_path: Path, monkeypatch) -> None:
    import os

    _env_file(tmp_path, REQUIRED + "AWS_SECRET_ACCESS_KEY=not-ours\n")
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    load_config(None, {}, tmp_path)
    assert "AWS_SECRET_ACCESS_KEY" not in os.environ
    assert "SHDOC_API_KEY" not in os.environ


def test_missing_required_value_raises_naming_it(tmp_path: Path) -> None:
    _env_file(tmp_path, "SHDOC_API_KEY=only-this\n")
    with pytest.raises(ConfigError) as excinfo:
        load_config(None, {}, tmp_path)
    assert "SHDOC_DOC_ID" in str(excinfo.value)


def test_no_env_file_anywhere_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(None, {}, tmp_path)


def test_the_token_never_appears_in_an_error(tmp_path: Path) -> None:
    _env_file(tmp_path, "SHDOC_API_KEY=super-secret-value\n")
    with pytest.raises(ConfigError) as excinfo:
        load_config(None, {}, tmp_path)
    assert "super-secret-value" not in str(excinfo.value)


def test_destructive_flag_defaults_off(tmp_path: Path) -> None:
    _env_file(tmp_path)
    assert load_config(None, {}, tmp_path).allow_destructive is False


def test_destructive_flag_enabled_from_file(tmp_path: Path) -> None:
    _env_file(tmp_path, REQUIRED + "SHDOC_ALLOW_DESTRUCTIVE=true\n")
    assert load_config(None, {}, tmp_path).allow_destructive is True


def test_disagreement_resolves_restrictively(tmp_path: Path) -> None:
    """A stale export must not arm destructive tools in a project whose own
    .env disables them."""
    _env_file(tmp_path, REQUIRED + "SHDOC_ALLOW_DESTRUCTIVE=false\n")
    config = load_config(None, {"SHDOC_ALLOW_DESTRUCTIVE": "1"}, tmp_path)
    assert config.allow_destructive is False


def test_disagreement_the_other_way_is_also_restrictive(tmp_path: Path) -> None:
    _env_file(tmp_path, REQUIRED + "SHDOC_ALLOW_DESTRUCTIVE=1\n")
    config = load_config(None, {"SHDOC_ALLOW_DESTRUCTIVE": "off"}, tmp_path)
    assert config.allow_destructive is False


def test_both_agreeing_enables(tmp_path: Path) -> None:
    _env_file(tmp_path, REQUIRED + "SHDOC_ALLOW_DESTRUCTIVE=yes\n")
    config = load_config(None, {"SHDOC_ALLOW_DESTRUCTIVE": "on"}, tmp_path)
    assert config.allow_destructive is True


def test_disagreement_is_reported_as_restricted_not_as_a_source(
    tmp_path: Path,
) -> None:
    _env_file(tmp_path, REQUIRED + "SHDOC_ALLOW_DESTRUCTIVE=false\n")
    config = load_config(None, {"SHDOC_ALLOW_DESTRUCTIVE": "1"}, tmp_path)
    assert config.allow_destructive is False
    assert config.sources["SHDOC_ALLOW_DESTRUCTIVE"] == "restricted"


def test_agreement_still_reports_an_ordinary_source(tmp_path: Path) -> None:
    _env_file(tmp_path, REQUIRED + "SHDOC_ALLOW_DESTRUCTIVE=1\n")
    config = load_config(None, {"SHDOC_ALLOW_DESTRUCTIVE": "true"}, tmp_path)
    assert config.sources["SHDOC_ALLOW_DESTRUCTIVE"] == "environment"


def test_the_locator_is_not_configuration(tmp_path: Path) -> None:
    """SHDOC_ENV_FILE carries the prefix but says only where to look. Reporting
    it beside the resolved values invites reading it as one of them."""
    named = tmp_path / "named.env"
    named.write_text(REQUIRED + "SHDOC_ENV_FILE=/ignored\n")
    config = load_config(None, {"SHDOC_ENV_FILE": str(named)}, tmp_path)
    assert "SHDOC_ENV_FILE" not in config.sources


def test_unusable_log_level_is_rejected(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "SHDOC_API_KEY=k\nSHDOC_DOC_ID=d\nSHDOC_LOG_LEVEL=chatty\n"
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(str(env), {}, tmp_path)
    message = str(excinfo.value)
    assert "chatty" in message
    assert "DEBUG" in message


def test_log_level_is_normalised_to_upper_case(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SHDOC_API_KEY=k\nSHDOC_DOC_ID=d\nSHDOC_LOG_LEVEL=debug\n")
    assert load_config(str(env), {}, tmp_path).log_level == "DEBUG"


def test_blank_log_level_falls_back_to_info(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SHDOC_API_KEY=k\nSHDOC_DOC_ID=d\nSHDOC_LOG_LEVEL=\n")
    assert load_config(str(env), {}, tmp_path).log_level == "INFO"


def test_whitespace_only_log_level_falls_back_to_info(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SHDOC_API_KEY=k\nSHDOC_DOC_ID=d\nSHDOC_LOG_LEVEL=   \n")
    assert load_config(str(env), {}, tmp_path).log_level == "INFO"
