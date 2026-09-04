import pytest
from superhumandoc_mcp.config import parse_affirmative


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", " On "])
def test_affirmative_values_enable(value: str) -> None:
    assert parse_affirmative(value) is True


@pytest.mark.parametrize(
    "value", [None, "", "0", "false", "no", "off", "FALSE", "maybe", "2", "y"]
)
def test_everything_else_disables(value: str | None) -> None:
    assert parse_affirmative(value) is False
