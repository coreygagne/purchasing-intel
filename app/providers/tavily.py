"""Tavily web search (https://tavily.com) - primary web search provider.

Endpoint: POST https://api.tavily.com/search with `Authorization: Bearer <key>`.
Credits (as published at the time of writing - verify on tavily.com):
basic search = 1 credit, advanced = 2 credits; extract = 1 credit per 5 URLs.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import ProviderError, SearchHit, classify_http_error

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"


class TavilyProvider:
    name = "Tavily"

    def __init__(self, api_key: str, client: httpx.AsyncClient, timeout_s: float = 25.0):
        if not api_key:
            raise ProviderError(self.name, "not_configured", "set TAVILY_API_KEY")
        self.api_key = api_key
        self.client = client
        self.timeout_s = timeout_s
        self.credits_used = 0.0

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        detail = ""
        try:
            body = resp.json()
            detail = str(body.get("detail", {}).get("error") if isinstance(body.get("detail"), dict)
                         else body.get("detail") or body.get("error") or "")[:200]
        except (ValueError, AttributeError):
            detail = resp.text[:200]
        code = resp.status_code
        if code in (401, 403):
            raise ProviderError(self.name, "auth", detail or "check TAVILY_API_KEY", code)
        if code in (432, 433):
            raise ProviderError(self.name, "quota", detail or "monthly credits or pay-as-you-go limit exhausted", code)
        if code == 429:
            raise ProviderError(self.name, "rate_limit", detail or "too many requests; wait and retry", code)
        if code == 400:
            raise ProviderError(self.name, "bad_request", detail, code)
        raise ProviderError(self.name, "upstream", detail, code)

    async def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self.client.post(url, json=body, headers=self._headers(), timeout=self.timeout_s)
        except Exception as exc:  # noqa: BLE001 - classified below
            raise classify_http_error(self.name, exc) from exc
        self._raise_for_status(resp)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(self.name, "bad_response", "response was not JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError(self.name, "bad_response", "response was not a JSON object")
        return data

    async def search(self, query: str, *, purpose: str, max_results: int = 8, depth: str = "basic",
                     country: str | None = None, include_raw: bool = False) -> list[SearchHit]:
        body: dict[str, Any] = {
            "query": query,
            "search_depth": "advanced" if depth == "advanced" else "basic",
            "max_results": max(1, min(max_results, 20)),
            "include_answer": False,
            "include_raw_content": bool(include_raw),
            "include_images": False,
            "topic": "general",
        }
        if country:
            body["country"] = country
        try:
            data = await self._post(SEARCH_URL, body)
        except ProviderError as exc:
            if exc.kind != "bad_request" or "country" not in body:
                raise
            # an optional boost the API rejects shouldn't fail the search; retry once without it
            log.warning("Tavily rejected the request with country=%r (%s); retrying without it", country, exc)
            body.pop("country")
            data = await self._post(SEARCH_URL, body)
        usage = data.get("usage")
        if isinstance(usage, dict) and isinstance(usage.get("credits"), (int, float)):
            self.credits_used += float(usage["credits"])
        else:
            self.credits_used += 2.0 if body["search_depth"] == "advanced" else 1.0
        results = data.get("results")
        if not isinstance(results, list):
            raise ProviderError(self.name, "bad_response", "missing 'results' list")
        hits: list[SearchHit] = []
        for i, r in enumerate(results):
            if not isinstance(r, dict) or not r.get("url"):
                continue
            hits.append(SearchHit(
                provider=self.name, query=query, purpose=purpose, url=str(r["url"]),
                title=str(r.get("title") or ""), snippet=str(r.get("content") or ""), rank=i + 1,
                raw_content=r.get("raw_content") if isinstance(r.get("raw_content"), str) else None,
                score=r.get("score") if isinstance(r.get("score"), (int, float)) else None,
                published_date=r.get("published_date") if isinstance(r.get("published_date"), str) else None,
            ))
        return hits

    async def extract(self, url: str) -> str | None:
        """Text content of one URL (used when a pasted URL cannot be fetched directly)."""
        data = await self._post(EXTRACT_URL, {"urls": [url], "extract_depth": "basic"})
        self.credits_used += 1.0  # billed per 5 successful URLs; counted conservatively
        for r in data.get("results") or []:
            if isinstance(r, dict) and isinstance(r.get("raw_content"), str):
                return r["raw_content"]
        return None
