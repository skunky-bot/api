import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import web_fetch


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.3", "169.254.169.254", "100.64.1.1", "224.1.1.1", "::1",
    "::ffff:127.0.0.1", "fe80::1", "2002:7f00:1::", "64:ff9b::a00:1",
])
def test_collector_denies_non_public_addresses(address):
    assert not web_fetch.public_address(address)


@pytest.mark.parametrize("outcome,paths,error", [
    ("ok", ["/robots.txt", "/contacts"], None),
    ("robots", ["/robots.txt"], "disallows"),
    ("redirect", ["/robots.txt", "/contacts"], "HTTP 302"),
    ("oversize", ["/robots.txt", "/contacts"], "size limit"),
])
def test_collector_uses_pinned_https_and_honors_robots(monkeypatch, outcome, paths, error):
    resolve = AsyncMock(return_value="8.8.8.8")
    monkeypatch.setattr(web_fetch, "resolve_public_host", resolve)
    monkeypatch.setattr(web_fetch, "REQUEST_GAP", 0.0)
    visited = []

    def handle(request):
        assert request.url.host == "8.8.8.8"
        assert request.headers["Host"] == request.extensions["sni_hostname"] == "example.org"
        assert "X-Skunky-Token" not in request.headers
        assert "Cookie" not in request.headers
        visited.append(request.url.path)
        if request.url.path == "/robots.txt":
            rules = b"User-agent: *\nDisallow: /contact*\n" if outcome == "robots" else b"User-agent: *\nAllow: /\n"
            return httpx.Response(200, stream=httpx.ByteStream(rules), headers={"content-type": "text/plain"})
        if outcome == "redirect":
            return httpx.Response(302, headers={"location": "https://elsewhere.example/"})
        content = b"x" * (web_fetch.PAGE_LIMIT + 1) if outcome == "oversize" else b"<p>Contact</p>"
        return httpx.Response(200, stream=httpx.ByteStream(content), headers={"content-type": "text/html"})

    async def fetch():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await web_fetch.PageFetcher(client).fetch("https://example.org/contacts")

    if error:
        with pytest.raises(web_fetch.SourceError, match=error):
            asyncio.run(fetch())
    else:
        assert asyncio.run(fetch()) == "<p>Contact</p>"
    assert visited == paths
    resolve.assert_awaited_once_with("example.org")
