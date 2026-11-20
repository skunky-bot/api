"""Authenticated stateless preview orchestration: search → scan → collect.

No arbitrary URLs are fetched, no data is persisted, no outbound messaging occurs.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from app.deps import get_current_user
from app.services.pipeline import Pipeline, service_config

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class PreviewIn(BaseModel):
    query: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=100)
    source_url: HttpUrl
    html: str = Field(min_length=1, max_length=200_000)
    region: str = Field(default="ZA", pattern=r"^[A-Z]{2}$")


@router.post("/preview")
async def preview(body: PreviewIn, _user=Depends(get_current_user)) -> dict:
    try:
        config = service_config()
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    source_url = str(body.source_url)
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False, trust_env=False) as client:
            pipeline = Pipeline(client, config)
            sources = await pipeline.search(body.query, limit=50)
            selected = next((s for s in sources if s["id"] == body.source_id and s["enabled"]), None)
            if not selected or selected["url"].rstrip("/") != source_url.rstrip("/"):
                raise HTTPException(422, "Source is not approved for this preview")
            result = await pipeline.contacts(body.source_id, source_url, body.html, body.region)
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
