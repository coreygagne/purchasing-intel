"""Polite, guarded fetching of individual product pages.

Used to read schema.org structured data (price, currency, availability,
ratings) directly from supplier pages. Respects robots.txt by default,
limits size and time, and reports every failure instead of hiding it.

Because URLs come from users and from search results, every request and
every redirect hop is checked first: http(s) only, ports 80/443 only, and the
host must resolve to public internet addresses (no localhost, private LAN,
link-local or cloud-metadata addresses).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .db import iso

MAX_REDIRECTS = 5


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | None
    html: str | None
    error: str | None
    fetched_at: str
    final_url: str | None = None
    # True when *our side* couldn't connect (DNS, network, timeout) - the only case where a fetch may be retried
    # another way. A site's own answer (403, 404, robots.txt "no") is never retried.
    network_failure: bool = False
    text: str | None = None   # plain page text when read via a fallback that returns text, not HTML
    title: str | None = None
    via: str | None = None


class BlockedURL(Exception):
    pass


class Unresolvable(BlockedURL):
    """The host name could not be resolved from this server (a network problem, not a safety block)."""


async def resolve_host(host: str) -> list[str]:
    """IP addresses for `host` (module-level so tests can substitute a resolver)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def _public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    return addr.is_global and not addr.is_multicast


_INTERNAL_SUFFIXES = (".local", ".internal", ".lan", ".corp", ".home", ".intranet", ".localdomain", ".arpa",
                      ".localhost", ".test", ".invalid")


def _public_looking_name(host: str) -> bool:
    h = host.lower().rstrip(".")
    return "." in h and not h.endswith(_INTERNAL_SUFFIXES) and h != "localhost"


async def check_url(url: str, *, allow_unresolved: bool = False) -> None:
    """Raise BlockedURL unless `url` is a public http(s) address on a standard port.

    `allow_unresolved`: on proxy-only networks the server can't resolve public names itself; then a
    public-looking host name (not an IP, not an internal suffix) is allowed and the proxy resolves it."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURL("only http(s) links can be read")
    if parts.username or parts.password:
        raise BlockedURL("links with embedded credentials are not read")
    host = parts.hostname
    if not host:
        raise BlockedURL("link has no host name")
    try:
        port = parts.port
    except ValueError as exc:
        raise BlockedURL("invalid port") from exc
    if port not in (None, 80, 443):
        raise BlockedURL(f"port {port} is not allowed (only 80/443)")
    try:
        ips = [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        try:
            ips = await resolve_host(host)
        except (OSError, UnicodeError) as exc:
            if allow_unresolved and _public_looking_name(host):
                return
            if _public_looking_name(host):
                raise Unresolvable(f"could not resolve {host}") from exc
            raise BlockedURL(f"could not resolve {host}") from exc
    if not ips or not all(_public(ip) for ip in ips):
        raise BlockedURL(f"{host} points to a private or internal network address")


class PageFetcher:
    def __init__(self, client: httpx.AsyncClient, *, user_agent: str, timeout_s: float,
                 max_bytes: int, respect_robots: bool = True, allow_unresolved: bool = False):
        self.client = client
        self.allow_unresolved = allow_unresolved
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        # origin -> (cached at, parser, allow_all, unreachable)
        self._robots: dict[str, tuple[float, RobotFileParser | None, bool, bool]] = {}
        self._robots_lock = asyncio.Lock()

    async def _get(self, url: str, *, accept: str) -> tuple[httpx.Response, bytes, str]:
        """GET with manual, checked redirects. Returns (response, body, final_url)."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            await check_url(current, allow_unresolved=self.allow_unresolved)
            async with self.client.stream(
                "GET", current, timeout=self.timeout_s, follow_redirects=False,
                headers={"User-Agent": self.user_agent, "Accept": accept, "Accept-Language": "en-CA,en;q=0.9"},
            ) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                chunks, size = [], 0
                if resp.status_code < 400:
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > self.max_bytes:
                            break
                return resp, b"".join(chunks)[: self.max_bytes], current
        raise BlockedURL("too many redirects")

    async def _allowed(self, url: str) -> tuple[bool, str | None, bool]:
        """(allowed, reason, network_failure) for `url` under the site's robots.txt."""
        if not self.respect_robots:
            return True, None, False
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        async with self._robots_lock:
            cached = self._robots.get(origin)
        if cached is None or time.time() - cached[0] > 86400:
            parser: RobotFileParser | None = RobotFileParser()
            allow_all = unreachable = False
            try:
                resp, body, _ = await self._get(f"{origin}/robots.txt", accept="text/plain")
                if resp.status_code >= 500:
                    parser, allow_all = None, False  # treat server errors as "don't crawl"
                elif resp.status_code >= 400:
                    parser, allow_all = None, True   # no robots.txt -> allowed
                else:
                    parser.parse(body.decode("utf-8", errors="replace").splitlines())
            except (httpx.TransportError, Unresolvable):
                parser, allow_all, unreachable = None, False, True
            except (httpx.HTTPError, BlockedURL):
                parser, allow_all = None, False
            cached = (time.time(), parser, allow_all, unreachable)
            async with self._robots_lock:
                self._robots[origin] = cached
        _, parser, allow_all, unreachable = cached
        if parser is None:
            if allow_all:
                return True, None, False
            if unreachable:
                return False, "robots.txt could not be reached (network error)", True
            return False, "robots.txt could not be read", False
        if parser.can_fetch(self.user_agent, url):
            return True, None, False
        return False, "disallowed by the site's robots.txt", False

    async def fetch(self, url: str) -> FetchResult:
        try:
            # overall deadline, so a slow-drip server can't stall a research job
            return await asyncio.wait_for(self._fetch(url), timeout=self.timeout_s * 3 + 2)
        except asyncio.TimeoutError:
            return FetchResult(url, False, None, None, f"gave up after {self.timeout_s * 3 + 2:.0f}s", iso(),
                               network_failure=True)

    async def _fetch(self, url: str) -> FetchResult:
        try:
            await check_url(url, allow_unresolved=self.allow_unresolved)
        except BlockedURL as exc:
            return FetchResult(url, False, None, None, f"Not fetched: {exc}", iso(),
                               network_failure=isinstance(exc, Unresolvable))
        allowed, reason, unreachable = await self._allowed(url)
        if not allowed:
            return FetchResult(url, False, None, None, f"Not fetched: {reason}", iso(), network_failure=unreachable)
        try:
            resp, body, final = await self._get(url, accept="text/html,application/xhtml+xml")
        except BlockedURL as exc:
            return FetchResult(url, False, None, None, f"Not fetched: {exc}", iso(),
                               network_failure=isinstance(exc, Unresolvable))
        except httpx.TimeoutException:
            return FetchResult(url, False, None, None, f"timed out after {self.timeout_s:.0f}s", iso(),
                               network_failure=True)
        except httpx.TransportError as exc:
            return FetchResult(url, False, None, None, f"network error: {type(exc).__name__}", iso(),
                               network_failure=True)
        except httpx.HTTPError as exc:
            return FetchResult(url, False, None, None, f"network error: {type(exc).__name__}", iso())
        if resp.status_code >= 400:
            msg = {401: "login required", 403: "blocked by the site (403)", 404: "page not found (404)",
                   429: "rate limited by the site (429)"}.get(resp.status_code, f"HTTP {resp.status_code}")
            return FetchResult(url, False, resp.status_code, None, msg, iso(), final)
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and "xml" not in ctype:
            return FetchResult(url, False, resp.status_code, None, f"not an HTML page ({ctype or 'unknown type'})",
                               iso(), final)
        html = body.decode(resp.encoding or "utf-8", errors="replace")
        return FetchResult(url, True, resp.status_code, html, None, iso(), final)
