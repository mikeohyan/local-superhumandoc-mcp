"""The boundary that translates typed client failures into ToolError.

The MCP SDK redacts bare exceptions to 'Error executing tool <name>', but lets
a ToolError message through verbatim. This boundary catches the client's typed
failures and translates them, leaving bugs in this server to be redacted by the
SDK — surfacing them verbatim would leak internals to the model.
"""

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from superhumandoc_mcp.config import Config
from superhumandoc_mcp.errors import AuthFailure, UpstreamRefused
from superhumandoc_mcp.tools.boundary import tool_boundary


def _config() -> Config:
    from pathlib import Path

    return Config(
        api_key="synthetic-token-not-real",
        doc_id="doc-under-test",
        allow_destructive=False,
        log_level="INFO",
        env_file=Path("/synthetic/.env"),
        sources={},
    )


async def test_a_typed_failure_reaches_the_model_intact():
    """An UpstreamRefused with status and detail becomes a ToolError with both."""

    @tool_boundary
    async def failing() -> str:
        raise UpstreamRefused("find_rows", 404, "No such table.")

    with pytest.raises(ToolError) as caught:
        await failing()
    assert "404" in str(caught.value)
    assert "No such table." in str(caught.value)


async def test_an_unexpected_failure_is_not_dressed_up_as_a_tool_error():
    """A bug in our own code must stay a bug, and be redacted by the SDK."""

    @tool_boundary
    async def failing() -> str:
        raise ZeroDivisionError("this is a bug, not an upstream refusal")

    with pytest.raises(ZeroDivisionError):
        await failing()


async def test_the_boundary_never_leaks_the_token():
    """An AuthFailure becomes ToolError but the token must not appear."""
    config = _config()

    @tool_boundary
    async def failing() -> str:
        raise AuthFailure("whoami", 401)

    with pytest.raises(ToolError) as caught:
        await failing()
    assert config.api_key not in str(caught.value)
