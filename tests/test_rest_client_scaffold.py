"""Scaffold for the REST layer's tests.

Nothing calls Superhuman Docs yet — that is the `upstream-api` topic's tool
bodies, not this wave. Once they exist, their tests run against a mocked
`httpx2` transport rather than a live API, so the interesting behaviour
(mutation polling, backoff, error translation, value post-processing, metadata
caching) is exercised without a network call or an API token. This file is
structure plus one self-check that the mock actually intercepts requests —
not coverage of behaviour that does not exist yet.
"""

import httpx2
import pytest


async def test_mock_transport_intercepts_requests() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/probe"
        return httpx2.Response(200, json={"ok": True})

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(
        transport=transport, base_url="https://example.invalid"
    ) as client:
        response = await client.get("/probe")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_mock_transport_rejects_unexpected_requests() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"unexpected request: {request.url}")

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(
        transport=transport, base_url="https://example.invalid"
    ) as client:
        with pytest.raises(AssertionError, match="unexpected request"):
            await client.get("/unhandled")
