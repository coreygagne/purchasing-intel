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
from .anthropic_search import AnthropicSearchProvider
from .base import ProviderError, SearchHit, ShoppingListing
from .serpapi import SerpApiProvider
from .tavily import TavilyProvider

__all__ = ["ProviderError", "SearchHit", "ShoppingListing", "ProviderSet", "build_providers",
           "provider_status", "SETUP_INSTRUCTIONS"]

SETUP_INSTRUCTIONS = {
    "summary": "No search provider is connected yet, so no research can run. Nothing is simulated.",
    "steps": [
        "Get an Anthropic API key: sign in at https://console.anthropic.com, open API Keys and choose Create Key. "
        "While you're there, set a monthly spend limit for the workspace so costs can't run away.",
        "Paste the key in the box below and choose Save. It is checked with Anthropic and saved only on this "
        "computer (in the app's .env file).",
        "Optional, to cut search costs: a free Tavily key from https://app.tavily.com (1,000 free credits a month), "
        "saved the same way.",
    ],
    "docs": "Step-by-step help: GETTING-STARTED.md. Costs and options: README.md > 'Search providers, keys and costs'.",
}


@dataclass
class ProviderSet:
    web: Any | None
    shopping: SerpApiProvider | None
    tavily: TavilyProvider | None

    def credits(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.tavily:
            out["tavily_credits"] = self.tavily.credits_used
        serp = self.shopping or (self.web if isinstance(self.web, SerpApiProvider) else None)
        if serp:
            out["serpapi_searches"] = serp.credits_used
        if isinstance(self.web, AnthropicSearchProvider):
            out["anthropic_web_searches"] = self.web.credits_used
            out["anthropic_search_tokens"] = dict(self.web.tokens)
            out["anthropic_search_model"] = self.web.model
        return out


def _web_order(settings: Settings) -> list[str]:
    available = [name for name, ok in (("tavily", settings.tavily_api_key), ("serpapi", settings.serpapi_api_key),
                                       ("anthropic", settings.anthropic_api_key)) if ok]
    if settings.search_provider in available:
        return [settings.search_provider]
    return available


def build_providers(settings: Settings, client: httpx.AsyncClient, anthropic_client: Any | None = None) -> ProviderSet:
    tavily = TavilyProvider(settings.tavily_api_key, client, settings.search_timeout_s) if settings.tavily_api_key else None
    serp = (SerpApiProvider(settings.serpapi_api_key, client, settings.search_timeout_s, settings.serpapi_location)
            if settings.serpapi_api_key else None)
    order = _web_order(settings)
    web: Any | None = None
    if order:
        if order[0] == "tavily":
            web = tavily
        elif order[0] == "serpapi":
            web = serp
        else:
            web = AnthropicSearchProvider(settings.anthropic_api_key or "", model=settings.anthropic_model,
                                          base_url=settings.anthropic_base_url,
                                          effort=settings.anthropic_search_effort, client=anthropic_client)
    return ProviderSet(web=web, shopping=serp, tavily=tavily)


def provider_status(settings: Settings) -> dict[str, Any]:
    providers = [
        {"name": "Tavily", "role": "Web search (suppliers, reviews, specs, wholesale)",
         "configured": bool(settings.tavily_api_key), "env": "TAVILY_API_KEY", "required": "one of Tavily or SerpApi"},
        {"name": "SerpApi", "role": "Google Shopping Canada listings (structured prices); also web search if Tavily is absent",
         "configured": bool(settings.serpapi_api_key), "env": "SERPAPI_API_KEY", "required": "optional"},
        {"name": "Claude (Anthropic)", "role": "Optional: understands plain-language requests, extracts prices/specs from page text, summarizes reviews. Every extracted fact is verified against source text. Also provides Anthropic web search when no other search key is set.",
         "configured": settings.llm_enabled, "env": "ANTHROPIC_API_KEY", "required": "optional",
         "model": settings.anthropic_model if settings.llm_enabled else None},
        {"name": "Bank of Canada Valet", "role": "Daily FX rates for currency conversion (free, no key)",
         "configured": True, "env": None, "required": "built in"},
    ]
    order = _web_order(settings)
    ready = bool(order)
    names = {"tavily": "Tavily", "serpapi": "SerpApi (Google)", "anthropic": "Anthropic web search"}
    return {"ready": ready, "providers": providers, "web_search": names[order[0]] if order else None,
            "setup": None if ready else SETUP_INSTRUCTIONS}
