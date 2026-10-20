"""SerpApi (https://serpapi.com) - Google Shopping (Canada) listings, and Google
web results as an alternative web provider.

Endpoint: GET https://serpapi.com/search.json?engine=...&api_key=...
Each successful search consumes one search from the monthly plan (verify
current plans on serpapi.com).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import ProviderError, SearchHit, ShoppingListing, classify_http_error

log = logging.getLogger(__name__)

SEARCH_URL = "https://serpapi.com/search.json"


class SerpApiProvider:
    name = "SerpApi"

    def __init__(self, api_key: str, client: httpx.AsyncClient, timeout_s: float = 25.0,
                 location: str | None = None):
        if not api_key:
            raise ProviderError(self.name, "not_configured", "set SERPAPI_API_KEY")
        self.api_key = api_key
        self.client = client
        self.timeout_s = timeout_s
        self.location = location
        self.credits_used = 0.0

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "api_key": self.api_key, "gl": "ca", "hl": "en"}
        if self.location:
            params["location"] = self.location
        try:
            resp = await self.client.get(SEARCH_URL, params=params, timeout=self.timeout_s)
        except Exception as exc:  # noqa: BLE001
            raise classify_http_error(self.name, exc) from exc
        try:
            data = resp.json()
        except ValueError as exc:
            if resp.status_code >= 400:
                raise ProviderError(self.name, "upstream", resp.text[:200], resp.status_code) from exc
            raise ProviderError(self.name, "bad_response", "response was not JSON") from exc
        err = data.get("error") if isinstance(data, dict) else None
        code = resp.status_code
        if err:
            low = str(err).lower()
            if "hasn't returned any results" in low or "no results" in low:
                self.credits_used += 1
                return {}
            if code == 401 or "api key" in low:
                raise ProviderError(self.name, "auth", str(err)[:200], code)
            if "run out of searches" in low or ("plan" in low and "limit" in low):
                raise ProviderError(self.name, "quota", str(err)[:200], code)
            if code == 429 or "throughput" in low or "rate" in low:
                raise ProviderError(self.name, "rate_limit", str(err)[:200], code)
            if code == 400:
                raise ProviderError(self.name, "bad_request", str(err)[:200], code)
            raise ProviderError(self.name, "upstream", str(err)[:200], code if code >= 400 else None)
        if code >= 400:
            raise ProviderError(self.name, "upstream", "", code)
        if not isinstance(data, dict):
            raise ProviderError(self.name, "bad_response", "response was not a JSON object")
        self.credits_used += 1
        return data

    async def shopping(self, query: str) -> list[ShoppingListing]:
        data = await self._get({"engine": "google_shopping", "q": query})
        out: list[ShoppingListing] = []
        items = list(data.get("shopping_results") or []) + list(data.get("inline_shopping_results") or [])
        for r in items:
            if not isinstance(r, dict):
                continue
            url = r.get("link") or r.get("product_link")
            if not url or not r.get("title"):
                continue
            price = r.get("extracted_price")
            out.append(ShoppingListing(
                provider=self.name, query=query, title=str(r["title"]), supplier=r.get("source"),
                url=str(url), price_text=r.get("price"),
                price_value=float(price) if isinstance(price, (int, float)) else None,
                old_price_text=r.get("old_price"),
                rating=float(r["rating"]) if isinstance(r.get("rating"), (int, float)) else None,
                reviews=int(r["reviews"]) if isinstance(r.get("reviews"), (int, float)) else None,
                delivery=r.get("delivery") if isinstance(r.get("delivery"), str) else None,
                condition=r.get("second_hand_condition") if isinstance(r.get("second_hand_condition"), str) else None,
                extra={"direct_link": bool(r.get("link")), "tag": r.get("tag")},
            ))
        return out

    async def search(self, query: str, *, purpose: str, max_results: int = 8, depth: str = "basic",
                     country: str | None = None, include_raw: bool = False) -> list[SearchHit]:
        params = {"engine": "google", "q": query, "num": max(1, min(max_results, 20))}
        try:
            data = await self._get(params)
        except ProviderError as exc:
            if exc.kind != "bad_request":
                raise
            # `num` is optional; if the API rejects it, retry once without it
            log.warning("SerpApi rejected the request (%s); retrying without num", exc)
            data = await self._get({k: v for k, v in params.items() if k != "num"})
        hits: list[SearchHit] = []
        for i, r in enumerate(data.get("organic_results") or []):
            if not isinstance(r, dict) or not r.get("link"):
                continue
            snippet = str(r.get("snippet") or "")
            rich = r.get("rich_snippet")
            if isinstance(rich, dict):
                for part in rich.values():
                    if isinstance(part, dict) and part.get("extensions"):
                        snippet += " " + " · ".join(str(x) for x in part["extensions"])
            hits.append(SearchHit(provider=self.name, query=query, purpose=purpose, url=str(r["link"]),
                                  title=str(r.get("title") or ""), snippet=snippet.strip(), rank=i + 1,
                                  published_date=r.get("date") if isinstance(r.get("date"), str) else None))
        return hits
