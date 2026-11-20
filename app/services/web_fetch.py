"""Read one registry page and its robots policy over pinned public HTTPS."""

import asyncio
import ipaddress
import socket
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
from protego import Protego

USER_AGENT = "SkunkScrapeCollector"
PAGE_LIMIT = 200_000
ROBOTS_LIMIT = 500 * 1024
REQUEST_GAP = 2.0
MAX_WAIT = 20.0
PUBLIC_IPV6 = ipaddress.ip_network("2000::/3")
TRANSITION_IPV6 = (ipaddress.ip_network("2002::/16"), ipaddress.ip_network("2001::/32"))


class SourceError(Exception):
    pass


def public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast or address.is_reserved or address.is_link_local:
        return False
    if address.version == 6:
        return address in PUBLIC_IPV6 and not any(address in subnet for subnet in TRANSITION_IPV6)
    return True


async def resolve_public_host(host: str) -> str:
    records = await asyncio.get_running_loop().getaddrinfo(f"{host}.", 443, type=socket.SOCK_STREAM)
    addresses = [record[4][0] for record in records]
    if not addresses or not all(public_address(address) for address in addresses):
        raise SourceError("Source must resolve exclusively to public addresses")
    return addresses[0]


def registry_url(raw: str) -> httpx.URL:
    try:
        parsed = urlsplit(raw)
        url = httpx.URL(raw)
        host = url.raw_host.decode("ascii").removesuffix(".")
        if (parsed.scheme != "https" or url.scheme != "https" or parsed.port not in (None, 443)
                or "@" in parsed.netloc or "#" in raw or "." not in host or "\\" in raw
                or any(ord(character) < 33 for character in raw)):
            raise ValueError("Invalid source URL")
        # A source must be an HTTPS hostname, with a certificate for that name.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return url.copy_with(host=host)
    except (ValueError, httpx.InvalidURL):
        pass
    raise SourceError("Registry URL must use a public HTTPS hostname on port 443")


def retry_delay(value: str) -> float:
    if value.isascii() and value.isdecimal():
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return 60.0


class PageFetcher:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.last_request: dict[str, float] = {}
        self.retry_at: dict[str, float] = {}
        self.crawl_delays: dict[str, float] = {}

    async def _get(
        self, url: httpx.URL, address: str, *, robots: bool = False, delay: float = REQUEST_GAP,
    ) -> str | None:
        clock = asyncio.get_running_loop().time
        host = url.raw_host.decode("ascii")
        delay = max(delay, self.crawl_delays.get(host, 0))
        ready_at = max(self.last_request.get(host, 0) + delay, self.retry_at.get(host, 0))
        wait = ready_at - clock()
        if wait > MAX_WAIT:
            raise SourceError("Source requires a longer wait before another request")
        if wait > 0:
            await asyncio.sleep(wait)
        self.last_request[host] = clock()

        # Dial the checked address while preserving host routing and TLS hostname verification.
        request = httpx.Request("GET", url.copy_with(host=address), headers={
            "Host": host, "User-Agent": f"{USER_AGENT}/1.0", "Accept-Encoding": "identity",
        }, extensions={"sni_hostname": host})
        response = await self.client.send(request, stream=True, follow_redirects=False)
        try:
            if response.status_code in (429, 503):
                self.retry_at[host] = clock() + retry_delay(response.headers.get("retry-after", ""))
            if robots and response.status_code in (404, 410):
                return None
            if response.status_code != 200:
                resource = "robots.txt" if robots else "Page"
                raise SourceError(f"{resource} returned HTTP {response.status_code}")

            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            expected_types = ("text/plain", "") if robots else ("text/html", "application/xhtml+xml")
            if mime not in expected_types:
                raise SourceError("Source returned an unexpected content type")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise SourceError("Source returned an unsupported content encoding")

            maximum = ROBOTS_LIMIT if robots else PAGE_LIMIT
            body = bytearray()
            async for chunk in response.aiter_raw():
                if len(body) + len(chunk) > maximum:
                    raise SourceError("Source response exceeds its size limit")
                body.extend(chunk)
            encoding = "utf-8-sig" if robots else response.encoding or "utf-8"
            try:
                return body.decode(encoding, errors="replace")
            except (LookupError, UnicodeError):
                return body.decode("utf-8", errors="replace")
        finally:
            await response.aclose()
            self.client.cookies.clear()

    async def fetch(self, raw_url: str) -> str:
        url = registry_url(raw_url)
        host = url.raw_host.decode("ascii")
        try:
            address = await asyncio.wait_for(resolve_public_host(host), timeout=5)
            robots_url = url.copy_with(path="/robots.txt", query=None)
            robots_text = await asyncio.wait_for(self._get(robots_url, address, robots=True), timeout=30)
            delay = REQUEST_GAP
            if robots_text:
                rules = Protego.parse(robots_text)
                if not rules.can_fetch(str(url), USER_AGENT):
                    raise SourceError("robots.txt disallows this page")
                delay = max(delay, rules.crawl_delay(USER_AGENT) or 0)
                rate = rules.request_rate(USER_AGENT)
                if rate and rate.requests > 0:
                    delay = max(delay, rate.seconds / rate.requests)
            self.crawl_delays[host] = delay
            html = await asyncio.wait_for(self._get(url, address, delay=delay), timeout=30)
        except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
            raise SourceError("Could not read the source over public HTTPS") from exc
        if not html or len(html) > PAGE_LIMIT:
            raise SourceError("Source did not return usable HTML within the size limit")
        return html
