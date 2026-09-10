import httpx2
import pytest

from superhumandoc_mcp.__main__ import _identify
from superhumandoc_mcp.client import DocsClient, TokenIdentity
from superhumandoc_mcp.config import Config, format_startup_line
from superhumandoc_mcp.errors import AuthFailure, ClientError


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


async def _no_sleep(seconds: float) -> None:
    return None


def _client(handler) -> DocsClient:
    return DocsClient(
        _config(), transport=httpx2.MockTransport(handler), sleep=_no_sleep
    )


async def test_whoami_reports_the_name_and_whether_the_token_is_scoped() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/whoami")
        return httpx2.Response(
            200, json={"name": "a@example.com", "tokenName": "MCP Validator",
                       "scoped": True}
        )

    identity = await _client(handler).whoami()
    assert identity.name == "MCP Validator"
    assert identity.scoped is True


async def test_whoami_is_never_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(Exception):
        await _client(handler).whoami()
    assert len(calls) == 1


async def test_whoami_is_never_retried_on_a_429_either() -> None:
    """A supervisor restarting a crash-looping server must not be able to
    amplify one bad launch into repeated calls on a shared bucket."""
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(429)

    with pytest.raises(ClientError):
        await _client(handler).whoami()
    assert len(calls) == 1


async def test_whoami_uses_its_own_shorter_read_ceiling() -> None:
    """A call with no replays has no retry checkpoint for a deadline to act
    at, so the ceiling has to live in the read timeout."""
    seen: list[httpx2.Timeout] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.extensions["timeout"])
        return httpx2.Response(200, json={"tokenName": "n", "scoped": False})

    await _client(handler).whoami()
    assert seen[0]["read"] == 10.0
    assert seen[0]["connect"] == 5.0


async def test_whoami_translates_a_transport_failure_into_a_typed_failure(
) -> None:
    """Startup must survive having no network at all. A raw transport
    exception escaping here would crash the process instead of starting the
    server with scope unknown."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route to host", request=request)

    with pytest.raises(ClientError):
        await _client(handler).whoami()


async def test_whoami_never_puts_the_token_in_a_failure_message() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route to host", request=request)

    with pytest.raises(ClientError) as excinfo:
        await _client(handler).whoami()
    assert "synthetic-token-not-real" not in str(excinfo.value)


async def test_whoami_raises_auth_failure_on_401() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401)

    with pytest.raises(AuthFailure):
        await _client(handler).whoami()


async def test_a_401_at_startup_exits_non_zero() -> None:
    """The token is not valid, so every tool would fail. Starting anyway would
    turn one configuration mistake into seventeen confusing failures."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401)

    with pytest.raises(SystemExit) as excinfo:
        await _identify(_config(), _client(handler))
    assert excinfo.value.code == 2


async def test_a_403_at_startup_starts_the_server_with_scope_unknown() -> None:
    """A 403 is what a token teaches per call, not a verdict on the token: the
    server learns what the token may do only by making a call and reading one.
    """
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403)

    assert await _identify(_config(), _client(handler)) is None


async def test_no_network_at_startup_starts_the_server_with_scope_unknown(
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route to host", request=request)

    assert await _identify(_config(), _client(handler)) is None


def test_the_startup_line_carries_the_token_name_and_scope() -> None:
    line = format_startup_line(
        _config(), TokenIdentity(name="MCP Validator", scoped=True)
    )
    assert "MCP Validator" in line
    assert "scoped" in line


def test_the_startup_line_distinguishes_an_unscoped_token() -> None:
    line = format_startup_line(
        _config(), TokenIdentity(name="MCP Validator", scoped=False)
    )
    assert "unscoped" in line


def test_the_startup_line_says_so_when_scope_could_not_be_established() -> None:
    line = format_startup_line(_config(), None)
    assert "scope unknown" in line


def test_the_startup_line_still_never_carries_the_token() -> None:
    line = format_startup_line(
        _config(), TokenIdentity(name="MCP Validator", scoped=True)
    )
    assert "synthetic-token-not-real" not in line


async def test_a_401_at_startup_names_the_running_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refused startup is exactly the one a bug report is about, so it
    carries the same leading `version=` field the startup line does. The fake
    version proves the field is derived; the lookup raises for any
    distribution name but this one."""
    import superhumandoc_mcp

    monkeypatch.setattr(
        superhumandoc_mcp, "version", lambda name: {"superhumandoc-mcp": "4.5.6"}[name]
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401)

    with pytest.raises(SystemExit):
        await _identify(_config(), _client(handler))
    line = capsys.readouterr().err.strip()
    assert line.startswith("superhumandoc-mcp: version=4.5.6 ")
    assert len(line) > len("superhumandoc-mcp: version=4.5.6 ")
