"""Polite fetching of individual product pages.

Used to read schema.org structured data (price, currency, availability,
ratings) directly from supplier pages. Respects robots.txt by default,
limits size and time, and reports every failure instead of hiding it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .db import iso


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | None
    html: str | None
    error: str | None
    fetched_at: str
    final_url: str | None = None


class PageFetcher:
    def __init__(self, client: httpx.AsyncClient, *, user_agent: str, timeout_s: float,
                 max_bytes: int, respect_robots: bool = True):
        self.client = client
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        self._robots: dict[str, tuple[float, RobotFileParser | None, bool]] = {}
        self._robots_lock = asyncio.Lock()

    async def _allowed(self, url: str) -> tuple[bool, str | None]:
        if not self.respect_robots:
            return True, None
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        async with self._robots_lock:
            cached = self._robots.get(origin)
        if cached is None or time.time() - cached[0] > 86400:
            parser: RobotFileParser | None = RobotFileParser()
            allow_all = False
            try:
                r = await self.client.get(f"{origin}/robots.txt", timeout=self.timeout_s,
                                          headers={"User-Agent": self.user_agent}, follow_redirects=True)
                if r.status_code >= 500:
                    parser, allow_all = None, False  # treat server errors as "don't crawl"
                elif r.status_code >= 400:
                    parser, allow_all = None, True   # no robots.txt -> allowed
                else:
                    parser.parse(r.text.splitlines())
            except httpx.HTTPError:
                parser, allow_all = None, False
            cached = (time.time(), parser, allow_all)
            async with self._robots_lock:
                self._robots[origin] = cached
        _, parser, allow_all = cached
        if parser is None:
            return (True, None) if allow_all else (False, "robots.txt could not be read")
        if parser.can_fetch(self.user_agent, url):
            return True, None
        return False, "disallowed by the site's robots.txt"

    async def fetch(self, url: str) -> FetchResult:
        allowed, reason = await self._allowed(url)
        if not allowed:
            return FetchResult(url, False, None, None, f"Not fetched: {reason}", iso())
        try:
            async with self.client.stream(
                "GET", url, timeout=self.timeout_s, follow_redirects=True,
                headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml",
                         "Accept-Language": "en-CA,en;q=0.9"},
            ) as resp:
                if resp.status_code >= 400:
                    msg = {401: "login required", 403: "blocked by the site (403)", 404: "page not found (404)",
                           429: "rate limited by the site (429)"}.get(resp.status_code, f"HTTP {resp.status_code}")
                    return FetchResult(url, False, resp.status_code, None, msg, iso(), str(resp.url))
                ctype = resp.headers.get("content-type", "")
                if "html" not in ctype and "xml" not in ctype:
                    return FetchResult(url, False, resp.status_code, None, f"not an HTML page ({ctype or 'unknown type'})", iso(), str(resp.url))
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > self.max_bytes:
                        break
                body = b"".join(chunks)[: self.max_bytes]
                html = body.decode(resp.encoding or "utf-8", errors="replace")
                return FetchResult(url, True, resp.status_code, html, None, iso(), str(resp.url))
        except httpx.TimeoutException:
            return FetchResult(url, False, None, None, f"timed out after {self.timeout_s:.0f}s", iso())
        except httpx.HTTPError as exc:
            return FetchResult(url, False, None, None, f"network error: {type(exc).__name__}", iso())
