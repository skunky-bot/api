import os
from urllib.parse import urlsplit

import httpx


def service_config() -> tuple[str, str, str, str]:
    names = ("SKUNKY_SEARCH_URL", "SKUNKY_SCAN_URL", "SKUNKY_COLLECT_URL", "SKUNKY_SERVICE_TOKEN")
    search, scan, collect, token = (os.getenv(name, "").strip() for name in names)
    if not all((search, scan, collect, token)):
        raise ValueError("Pipeline services are not configured")
    for url in (search, scan, collect):
        try:
            parsed = urlsplit(url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or "@" in parsed.netloc or parsed.query or parsed.fragment):
                raise ValueError("Invalid internal base URL")
            httpx.URL(url)
        except (ValueError, httpx.InvalidURL) as exc:
            raise ValueError("Invalid pipeline service configuration") from exc
    return search, scan, collect, token


class Pipeline:
    def __init__(self, client: httpx.AsyncClient, config: tuple[str, str, str, str]):
        self.client = client
        self.search_url, self.scan_url, self.collect_url, token = config
        self.headers = {"X-Skunky-Token": token}

    async def _post(self, base: str, path: str, body: dict) -> dict:
        response = await self.client.post(f"{base.rstrip('/')}{path}", headers=self.headers, json=body)
        response.raise_for_status()
        return response.json()

    async def search(self, query: str, limit: int, *, collection_only: bool = False) -> list[dict]:
        body = {"query": query, "limit": limit}
        if collection_only:
            body["collection_only"] = True
        result = await self._post(self.search_url, "/v1/search", body)
        sources = result["sources"]
        if not isinstance(sources, list) or any(not isinstance(source, dict) for source in sources):
            raise ValueError("Invalid search response")
        return sources

    async def contacts(
        self, source_id: str, url: str, html: str, region: str, *, provenance: str | None = None,
    ) -> dict:
        extracted = await self._post(self.scan_url, "/v1/extract", {
            "source_id": source_id, "source_url": url, "html": html,
        })
        body = {**extracted, "region": region}
        if provenance is not None:
            body["provenance"] = provenance
        return await self._post(self.collect_url, "/v1/normalize", body)
