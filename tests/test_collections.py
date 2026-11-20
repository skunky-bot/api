import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import create_access_token
from app.db.models import Collection, User, utcnow
from app.db.session import Base
from app.deps import get_db
from app.main import app
from app.services import collector_worker as worker

SOURCE = {"id": "solar", "url": "https://example.org/contacts", "enabled": True,
          "mode": "web-collection", "outreach_allowed": False}


@pytest.fixture
def collector(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'collector.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory.begin() as db:
        for username in ("operator-one", "operator-two"):
            db.add(User(username=username, email=f"{username}@example.com", hashed_password="unused"))

    def database():
        with session_factory() as db:
            yield db

    def headers(username):
        token = create_access_token(subject=username, expires_delta=timedelta(minutes=5))
        return {"Authorization": f"Bearer {token}"}

    monkeypatch.setitem(app.dependency_overrides, get_db, database)
    monkeypatch.setattr(worker, "SessionLocal", session_factory)
    monkeypatch.setattr(settings, "collector_enabled", True)
    with TestClient(app) as client:
        yield client, headers("operator-one"), headers("operator-two"), session_factory
    engine.dispose()


def collect_page(run):
    pipeline = Mock(
        search=AsyncMock(return_value=[{**SOURCE, "mode": "caller-supplied-html"}, SOURCE]),
        contacts=AsyncMock(return_value={"emails": ["sales@example.org"], "phones": ["+27115550123"]}),
    )
    fetcher = Mock(fetch=AsyncMock(return_value="<html>Contact page</html>"))
    asyncio.run(worker.process(run, pipeline, fetcher))
    pipeline.search.assert_awaited_once_with("solar cape", 5, collection_only=True)
    fetcher.fetch.assert_awaited_once_with(SOURCE["url"])


def test_one_time_collection_completes_and_results_are_private(collector):
    client, operator, other, _ = collector
    body = {"query": " solar cape ", "mode": "once"}
    assert client.post("/collections", json=body).status_code == 401
    assert client.post("/collections", json={**body, "url": "http://example.org"}, headers=operator).status_code == 422
    response = client.post("/collections", json=body, headers=operator)
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["status"] == "scheduled"
    run = worker.claim_next()
    assert run.collection_id == job["id"]
    assert worker.claim_next() is None
    collect_page(run)

    path = f"/collections/{job['id']}"
    complete = client.get(path, headers=operator).json()
    assert complete["status"] == "completed"
    assert complete["run_count"] == 1
    assert complete["result_count"] == 2
    assert complete["last_scanned"] == 1
    assert complete["last_run_at"].endswith("Z")
    assert complete["next_run_at"] is None
    assert worker.claim_next() is None
    assert client.get(path, headers=other).status_code == 404
    assert client.patch(path, json={"paused": True}, headers=other).status_code == 404
    assert client.get(f"{path}/contacts", headers=other).status_code == 404
    response = client.get(f"{path}/contacts", headers=operator)
    assert response.headers["cache-control"] == "no-store"
    assert all(contact["source_url"] == SOURCE["url"] for contact in response.json()["items"])


def test_continuous_collection_resumes_deduplicates_and_recovers_worker_lease(collector):
    client, operator, _, session_factory = collector
    body = {"query": "solar cape", "mode": "continuous"}
    assert client.post("/collections", json=body, headers=operator).status_code == 422
    job = client.post("/collections", json={**body, "interval_minutes": 15}, headers=operator).json()
    path = f"/collections/{job['id']}"
    collect_page(worker.claim_next())
    first = client.get(path, headers=operator).json()
    assert first["status"] == "scheduled"
    assert first["next_run_at"] > first["last_run_at"]
    assert worker.claim_next() is None

    with session_factory.begin() as db:
        db.execute(update(Collection).values(next_run_at=utcnow() - timedelta(seconds=1)))
    stale = worker.claim_next()
    with session_factory.begin() as db:
        db.execute(update(Collection).values(lease_until=utcnow() - timedelta(seconds=1)))
    retry = worker.claim_next()
    assert retry.collection_id == stale.collection_id and retry.token != stale.token
    worker.finish(stale, worker.Sweep())
    assert client.get(path, headers=operator).json()["status"] == "running"
    collect_page(retry)
    saved = client.get(path, headers=operator).json()
    assert saved["run_count"] == 2
    assert saved["result_count"] == 2
    rows = client.get(f"{path}/contacts", headers=operator).json()["items"]
    assert len(rows) == 2 and all(row["last_seen"] > row["first_seen"] for row in rows)

    paused = client.patch(path, json={"paused": True}, headers=operator).json()
    assert paused["status"] == "paused" and paused["next_run_at"] is None
    assert worker.claim_next() is None
    client.patch(path, json={"paused": False}, headers=operator).raise_for_status()
    active = worker.claim_next()
    client.patch(path, json={"paused": True}, headers=operator).raise_for_status()
    worker.finish(active, worker.Sweep())
    assert client.get(path, headers=operator).json()["status"] == "paused"
    assert client.get(path, headers=operator).json()["run_count"] == 2
