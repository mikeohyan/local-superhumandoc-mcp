"""`.env.example` is shipped documentation; hold it to the code.

The `tool-surface` topic's gated tools are named in the file's comments so a
user knows what the flag arms. If a gated tool is added or renamed and the
comment is not, this fails.
"""

import asyncio
from pathlib import Path

from superhumandoc_mcp.config import Config
from superhumandoc_mcp.server import build_server

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def _tool_names(*, allow_destructive: bool) -> set[str]:
    config = Config(
        api_key="k",
        doc_id="d",
        allow_destructive=allow_destructive,
        log_level="INFO",
        env_file=Path("/nowhere/.env"),
        sources={},
    )
    tools = asyncio.run(build_server(config).list_tools())
    return {tool.name for tool in tools}


def test_every_gated_tool_is_named_in_the_comment():
    gated = _tool_names(allow_destructive=True) - _tool_names(
        allow_destructive=False
    )
    assert gated, "expected the flag to gate at least one tool"
    text = ENV_EXAMPLE.read_text()
    missing = sorted(name for name in gated if name not in text)
    assert not missing, f".env.example does not name gated tools: {missing}"


def test_comment_names_no_tool_the_flag_does_not_gate():
    always_on = _tool_names(allow_destructive=False)
    text = ENV_EXAMPLE.read_text()
    wrongly_named = sorted(name for name in always_on if name in text)
    assert not wrongly_named, (
        f".env.example implies the flag gates always-on tools: {wrongly_named}"
    )


def test_the_stale_claim_is_gone():
    assert "registers no tools at all" not in ENV_EXAMPLE.read_text()
