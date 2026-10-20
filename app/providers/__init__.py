"""Search provider registry.

Picks real providers based on which API keys are configured. There is no
offline or demo fallback: with no key configured, research is refused and the
UI shows setup instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Settings
from .base import ProviderError, SearchHit, ShoppingListing
from .serpapi import SerpApiProvider
from .tavily import TavilyProvider

__all__ = ["ProviderError", "SearchHit", "ShoppingListing", "ProviderSet", "build_providers",
           "provider_status", "SETUP_INSTRUCTIONS"]

SETUP_INSTRUCTIONS = {
    "summary": "No search provider is configured, so no research can run. Nothing is simulated.",
    "steps": [
        "Create a free Tavily account at https://app.tavily.com and copy the API key (starts with 'tvly-').",
        "Copy .env.example to .env in the project folder.",
        "Set TAVILY_API_KEY=<your key> in .env (optional: SERPAPI_API_KEY for Google Shopping Canada prices).",
        "Restart the server (./run.sh). The status badge turns green when a provider is ready.",
    ],
    "docs": "See README.md > 'Search providers, keys and costs'.",
}


@dataclass
class ProviderSet:
    web: Any | None
    shopping: SerpApiProvider | None
    tavily: TavilyProvider | None

    def credits(self) -> dict[str, float]:
        out: dict[str, float] = {}
        if self.tavily:
            out["tavily_credits"] = self.tavily.credits_used
        serp = self.shopping or (self.web if isinstance(self.web, SerpApiProvider) else None)
        if serp:
            out["serpapi_searches"] = serp.credits_used
        return out


def build_providers(settings: Settings, client: httpx.AsyncClient) -> ProviderSet:
    tavily = TavilyProvider(settings.tavily_api_key, client, settings.search_timeout_s) if settings.tavily_api_key else None
    serp = (SerpApiProvider(settings.serpapi_api_key, client, settings.search_timeout_s, settings.serpapi_location)
            if settings.serpapi_api_key else None)
    web = tavily or serp
    return ProviderSet(web=web, shopping=serp, tavily=tavily)


def provider_status(settings: Settings) -> dict[str, Any]:
    providers = [
        {"name": "Tavily", "role": "Web search (suppliers, reviews, specs, wholesale)",
         "configured": bool(settings.tavily_api_key), "env": "TAVILY_API_KEY", "required": "one of Tavily or SerpApi"},
        {"name": "SerpApi", "role": "Google Shopping Canada listings (structured prices); also web search if Tavily is absent",
         "configured": bool(settings.serpapi_api_key), "env": "SERPAPI_API_KEY", "required": "optional"},
        {"name": "Claude (Anthropic)", "role": "Optional: understands plain-language requests, extracts prices/specs from page text, summarizes reviews. Every extracted fact is verified against source text.",
         "configured": settings.llm_enabled, "env": "ANTHROPIC_API_KEY", "required": "optional",
         "model": settings.anthropic_model if settings.llm_enabled else None},
        {"name": "Bank of Canada Valet", "role": "Daily FX rates for currency conversion (free, no key)",
         "configured": True, "env": None, "required": "built in"},
    ]
    ready = bool(settings.tavily_api_key or settings.serpapi_api_key)
    return {"ready": ready, "providers": providers, "setup": None if ready else SETUP_INSTRUCTIONS}
