"""Authenticated stateless preview orchestration: search → scan → collect.

No arbitrary URLs are fetched, no data is persisted, no outbound messaging occurs.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from app.deps import get_current_user

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class PreviewIn(BaseModel):
    query: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=100)
    source_url: HttpUrl
    html: str = Field(min_length=1, max_length=200_000)
    region: str = Field(default="ZA", pattern=r"^[A-Z]{2}$")


def services() -> tuple[str, str, str, str]:
    env_names = ("SKUNKY_SEARCH_URL", "SKUNKY_SCAN_URL", "SKUNKY_COLLECT_URL", "SKUNKY_SERVICE_TOKEN")
    values = tuple(os.getenv(k, "").strip() for k in env_names)
    if not all(values):
        raise HTTPException(503, "Pipeline services are not configured")
    for service_url in values[:3]:
        parsed = urlsplit(service_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(503, "Invalid pipeline service configuration")
    return values


@router.post("/preview")
async def preview(body: PreviewIn, _user=Depends(get_current_user)) -> dict:
    search_url, scan_url, collect_url, token = services()
    headers = {"X-Skunky-Token": token}
    source_url = str(body.source_url)
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            found = await client.post(
                f"{search_url.rstrip('/')}/v1/search",
                headers=headers,
                json={"query": body.query, "limit": 50},
            )
            found.raise_for_status()
            sources = found.json()["sources"]
            selected = next((s for s in sources if s["id"] == body.source_id and s["enabled"]), None)
            if not selected or selected["url"].rstrip("/") != source_url.rstrip("/"):
                raise HTTPException(422, "Source is not approved for this preview")
            scanned = await client.post(
                f"{scan_url.rstrip('/')}/v1/extract",
                headers=headers,
                json={"source_id": body.source_id, "source_url": source_url, "html": body.html},
            )
            scanned.raise_for_status()
            extracted = scanned.json()
            normalized = await client.post(
                f"{collect_url.rstrip('/')}/v1/normalize",
                headers=headers,
                json={**extracted, "region": body.region},
            )
            normalized.raise_for_status()
            result = normalized.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Internal pipeline service unavailable") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(502, "Invalid response from internal pipeline service") from exc

    return {
        "mode": "preview",
        "source": {"id": body.source_id, "url": source_url},
        "result": result,
        "network_fetched": False,
        "persisted": False,
    }
