"""Contract test for orchestrated preview, without network calls."""
import os
import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.routers import pipeline

client = TestClient(app)


def test_pipeline_preview(monkeypatch):
    auth = client.post("/auth/login", data={
        "username": os.environ["BOOTSTRAP_ADMIN_USERNAME"],
        "password": os.environ["BOOTSTRAP_ADMIN_PASSWORD"],
    })
    assert auth.status_code == 200
    jwt = auth.json()["access_token"]

    for k, v in {
        "SKUNKY_SEARCH_URL": "http://search",
        "SKUNKY_SCAN_URL": "http://scan",
        "SKUNKY_COLLECT_URL": "http://collect",
        "SKUNKY_SERVICE_TOKEN": "internal-test",
    }.items():
        monkeypatch.setenv(k, v)

    visited = []

    def handler(request):
        assert request.headers["X-Skunky-Token"] == "internal-test"
        visited.append(request.url.host)
        if request.url.host == "search":
            return httpx.Response(200, json={"sources": [
                {"id": "example-docs", "url": "https://example.com/", "enabled": True}
            ]})
        if request.url.host == "scan":
            return httpx.Response(200, json={
                "source_id": "example-docs", "source_url": "https://example.com/",
                "emails": ["info@example.com"], "phones": [],
                "provenance": "caller-supplied-html",
            })
        if request.url.host == "collect":
            return httpx.Response(200, json={
                "source_id": "example-docs", "source_url": "https://example.com/",
                "emails": ["info@example.com"], "phones": [],
                "consent_status": "unverified", "outreach_allowed": False, "persisted": False,
            })
        raise AssertionError(f"Unexpected host: {request.url.host}")

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(pipeline.httpx, "AsyncClient",
                        lambda **kw: original_client(transport=transport, **kw))

    response = client.post("/pipeline/preview", headers={"Authorization": f"Bearer {jwt}"}, json={
        "query": "demo", "source_id": "example-docs",
        "source_url": "https://example.com/",
        "html": "<a href='mailto:info@example.com'>Contact</a>"
    })
    assert response.status_code == 200, response.text
    assert visited == ["search", "scan", "collect"]
    assert response.json()["result"]["emails"] == ["info@example.com"]
    assert response.json()["persisted"] is False
    assert response.json()["network_fetched"] is False


def test_preview_requires_authentication():
    response = client.post("/pipeline/preview", json={
        "query": "demo", "source_id": "example-docs",
        "source_url": "https://example.com/", "html": "hello"
    })
    assert response.status_code == 401
