"""Live checks against the real Tavily and SerpApi APIs. They use real credits (about 16 Tavily credits and 5 SerpApi
searches in total) and only run with PI_NETWORK_TESTS=1 plus the provider's key, e.g.

    PI_NETWORK_TESTS=1 TAVILY_API_KEY=tvly-... SERPAPI_API_KEY=... python -m pytest -q tests/test_live_providers.py

They check that the providers' current response formats still parse, and that one full research completes on
Tavily alone. Keys come from the environment or .env (never from the test file).
"""

import dataclasses
import os

import httpx
import pytest

from app.config import load_settings
from app.db import Database
from app.providers.base import ProviderError
from app.providers.serpapi import SerpApiProvider
from app.providers.tavily import TavilyProvider
from app.research import ResearchEngine, ResearchRequest

SETTINGS = load_settings()
LIVE = bool(os.environ.get("PI_NETWORK_TESTS"))
ITEM = "Milwaukee 2767-20"

needs_tavily = pytest.mark.skipif(not (LIVE and SETTINGS.tavily_api_key),
                                  reason="live Tavily check: set PI_NETWORK_TESTS=1 and TAVILY_API_KEY")
needs_serpapi = pytest.mark.skipif(not (LIVE and SETTINGS.serpapi_api_key),
                                   reason="live SerpApi check: set PI_NETWORK_TESTS=1 and SERPAPI_API_KEY")


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30)


@needs_tavily
async def test_live_tavily_search_parses_and_counts_credits():
    p = TavilyProvider(SETTINGS.tavily_api_key, client())
    hits = await p.search(f"{ITEM} price", purpose="price", max_results=5, country="canada")
    assert hits, "Tavily returned no results for a common item"
    assert all(h.url.startswith("http") and h.title for h in hits)
    assert any(h.snippet for h in hits)
    assert p.credits_used >= 1


@needs_tavily
async def test_live_tavily_rejects_a_bad_key_as_auth():
    p = TavilyProvider("tvly-invalid-key-for-test", client())
    with pytest.raises(ProviderError) as e:
        await p.search(f"{ITEM} price", purpose="price", max_results=1)
    assert e.value.kind == "auth"


@needs_serpapi
async def test_live_serpapi_google_shopping_canada_parses():
    p = SerpApiProvider(SETTINGS.serpapi_api_key, client(), location=SETTINGS.serpapi_location)
    listings = await p.shopping(ITEM)
    assert listings, "Google Shopping (Canada) returned no listings for a common item"
    assert all(item.url.startswith("http") and item.title for item in listings)
    assert any(item.price_value is not None for item in listings), "no listing had extracted_price"


@needs_tavily
async def test_live_tavily_site_restricted_search_stays_on_site():
    p = TavilyProvider(SETTINGS.tavily_api_key, client())
    hits = await p.search(f"{ITEM} price", purpose="lead", max_results=5, country="canada", domains=["homedepot.ca"])
    assert all("homedepot.ca" in h.url for h in hits), [h.url for h in hits]


@needs_serpapi
async def test_live_serpapi_google_maps_thunder_bay_parses():
    from app.discovery import HOME
    p = SerpApiProvider(SETTINGS.serpapi_api_key, client())
    found = await p.local("hardware store", HOME["maps_ll"])
    assert found, "Google Maps returned no hardware stores near Thunder Bay"
    assert all(b.name for b in found)
    assert any(b.address and "Thunder Bay" in b.address for b in found), [b.address for b in found]
    assert any(b.phone for b in found) and any(b.website for b in found)


@needs_serpapi
async def test_live_serpapi_web_search_parses():
    p = SerpApiProvider(SETTINGS.serpapi_api_key, client())
    hits = await p.search(f"{ITEM} price", purpose="price", max_results=5)
    assert hits and all(h.url.startswith("http") for h in hits)


@needs_tavily
async def test_live_full_research_on_tavily(tmp_path):
    """Request -> real Tavily search -> evidence -> comparison -> saved (AI and fallback fetch off)."""
    settings = dataclasses.replace(SETTINGS, search_provider="tavily", anthropic_api_key=None,
                                   database_path=tmp_path / "live.db")
    db = Database(settings.database_path)
    res = await ResearchEngine(settings, db).run(ResearchRequest(ITEM, "quick"))
    assert res["providers"]["web"] == "Tavily"
    assert all(q["status"] == "ok" for q in res["queries"]), res["queries"]
    assert res["counts"]["sources"] > 0
    assert res["plan"]["rounds"] and res["coverage"]["channels"] and res["vendors"]
    cid = db.save_comparison(title=ITEM, query=ITEM, normalized=ITEM.lower(), product_key=res["product_key"],
                             result=res)
    assert db.get_comparison(cid)["result"]["identity"]["name"] == res["identity"]["name"]
