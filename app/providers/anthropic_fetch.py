"""Fetch a URL through Anthropic's server-side `web_fetch` tool.

A fallback for networks where this server can't reach a site directly (DNS or
firewall). The tool returns the fetched document's content itself, and the
app parses that content - the model only issues the fetch, and nothing it
writes is used as data.

Used only after a direct attempt failed for a network reason on our side; a
site that refuses us (403, robots.txt) is respected, never routed around.
Cost: the fetched content counts as input tokens (capped by max_content_tokens).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import anthropic

from ..db import iso
from ..fetch import BlockedURL, FetchResult, check_url

VIA = "Anthropic web fetch"
TOOL_TYPE = "web_fetch_20250910"  # returns the document content directly (no code-execution wrapping)


@dataclass
class FetchedDoc:
    url: str
    text: str
    retrieved_at: str | None
    title: str | None = None


class AnthropicFetchError(Exception):
    pass


def _make_client(api_key: str, base_url: str, timeout_s: float) -> Any:
    return anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=1)


class AnthropicFetcher:
    name = VIA

    def __init__(self, api_key: str, *, model: str, base_url: str, client: Any | None = None, timeout_s: float = 45.0):
        self.client = client or _make_client(api_key, base_url, timeout_s)
        self.model = model
        self.requests = 0
        self.tokens = {"input_tokens": 0, "output_tokens": 0}

    async def fetch(self, url: str, max_content_tokens: int = 6000) -> FetchedDoc:
        try:
            resp = await self.client.messages.create(
                model=self.model, max_tokens=2000, output_config={"effort": "low"},
                tools=[{"type": TOOL_TYPE, "name": "web_fetch", "max_uses": 1,
                        "max_content_tokens": max_content_tokens}],
                messages=[{"role": "user", "content": f"Fetch this URL with the web_fetch tool, then reply only "
                                                      f"'done': {url}"}],
            )
        except anthropic.AuthenticationError as exc:
            raise AnthropicFetchError("Anthropic API key rejected") from exc
        except anthropic.RateLimitError as exc:
            raise AnthropicFetchError("Anthropic rate limit reached") from exc
        except anthropic.APIStatusError as exc:
            raise AnthropicFetchError(f"Anthropic API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise AnthropicFetchError("cannot reach api.anthropic.com") from exc
        usage = getattr(resp, "usage", None)
        if usage is not None:
            self.tokens["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
            self.tokens["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
            stu = getattr(usage, "server_tool_use", None)
            self.requests += int(getattr(stu, "web_fetch_requests", 0) or 0) if stu else 0
        for block in resp.content:
            if getattr(block, "type", "") != "web_fetch_tool_result":
                continue
            content = block.content
            if getattr(content, "type", "") == "web_fetch_tool_result_error":
                raise AnthropicFetchError(f"web fetch error: {content.error_code}")
            doc = getattr(content, "content", None)
            source = getattr(doc, "source", None)
            text = getattr(source, "data", None)
            if getattr(source, "type", "") == "text" and isinstance(text, str):
                return FetchedDoc(getattr(content, "url", None) or url, text, getattr(content, "retrieved_at", None),
                                  getattr(doc, "title", None))
            raise AnthropicFetchError("fetched document was not text (e.g. a PDF)")
        if getattr(resp, "stop_reason", None) == "refusal":
            raise AnthropicFetchError("the model declined to fetch this URL")
        raise AnthropicFetchError("no fetch result returned")


class AnthropicPageReader:
    """Reads pages through AnthropicFetcher when this server's own network couldn't reach them.

    The same rules as a direct read apply: the site's robots.txt (fetched the same way) is obeyed, and when it
    can't be read the page is not read. At most `max_pages` pages per research, to bound cost.
    """

    def __init__(self, fetcher: AnthropicFetcher, *, user_agent: str, max_pages: int, respect_robots: bool = True,
                 max_content_tokens: int = 8000):
        self.fetcher = fetcher
        self.user_agent = user_agent
        self.max_pages = max_pages
        self.respect_robots = respect_robots
        self.max_content_tokens = max_content_tokens
        self.pages_attempted = 0
        self._robots: dict[str, RobotFileParser | str] = {}  # origin -> parser, or why it couldn't be read
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def remaining(self) -> int:
        return max(0, self.max_pages - self.pages_attempted)

    async def _robots_allows(self, url: str) -> tuple[bool, str | None]:
        if not self.respect_robots:
            return True, None
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        async with self._locks.setdefault(origin, asyncio.Lock()):
            entry = self._robots.get(origin)
            if entry is None:
                try:
                    doc = await self.fetcher.fetch(f"{origin}/robots.txt", max_content_tokens=4000)
                    entry = RobotFileParser()
                    entry.parse(doc.text.splitlines())
                except AnthropicFetchError as exc:
                    entry = f"robots.txt could not be read via {VIA} ({exc})"
                self._robots[origin] = entry
        if isinstance(entry, str):
            return False, entry
        if entry.can_fetch(self.user_agent, url):
            return True, None
        return False, "disallowed by the site's robots.txt"

    async def read(self, url: str) -> FetchResult:
        try:
            # Anthropic resolves the name; still refuse IP literals/internal names and non-standard ports
            await check_url(url, allow_unresolved=True)
        except BlockedURL as exc:
            return FetchResult(url, False, None, None, f"Not fetched: {exc}", iso(), via=VIA)
        if self.remaining <= 0:
            return FetchResult(url, False, None, None, f"{VIA} limit reached ({self.max_pages} pages per research)",
                               iso(), via=VIA)
        self.pages_attempted += 1
        allowed, reason = await self._robots_allows(url)
        if not allowed:
            return FetchResult(url, False, None, None, f"Not fetched: {reason}", iso(), via=VIA)
        try:
            doc = await self.fetcher.fetch(url, self.max_content_tokens)
        except AnthropicFetchError as exc:
            return FetchResult(url, False, None, None, f"{VIA} failed: {exc}", iso(), via=VIA)
        return FetchResult(url, True, None, None, None, doc.retrieved_at or iso(), final_url=doc.url, text=doc.text,
                           title=doc.title, via=VIA)
