"""Estimated Anthropic spend, from the token and search counts the API reports for each research.

These are estimates at Anthropic's published list prices (US$, checked 2026-10-21), not a bill: the Anthropic
Console shows the actual charges, and a spend limit set there is the hard backstop. Tavily and SerpApi are
plan-based (free tiers) and are counted in credits/searches, not dollars.
"""

from __future__ import annotations

from typing import Any

PRICES_CHECKED = "2026-10-21"
# model: (US$ per million input tokens, US$ per million output tokens)
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),  # for prompts up to 100K tokens; each call this app makes is far smaller
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-fable-5-1": (10.00, 50.00),
}
WEB_SEARCH_USD = 0.01  # Anthropic web search: US$10 per 1,000 searches


def token_cost(model: str | None, usage: dict[str, Any] | None) -> float | None:
    """Cost of one usage record, or None if the model's price isn't known."""
    if not usage:
        return 0.0
    price = PRICES_PER_MTOK.get(model or "")
    if price is None:
        return None
    return ((usage.get("input_tokens") or 0) * price[0] + (usage.get("output_tokens") or 0) * price[1]) / 1e6


def estimate_usd(credits: dict[str, Any]) -> float | None:
    """Estimated Anthropic spend for one research's `credits` record; None if any part can't be priced."""
    total = (credits.get("anthropic_web_searches") or 0) * WEB_SEARCH_USD
    parts = [token_cost(credits.get("anthropic_search_model"), credits.get("anthropic_search_tokens"))]
    for usage in (credits.get("llm_usage") or {}).values():
        if usage:
            parts.append(token_cost(usage.get("model"), usage))
    if any(p is None for p in parts):
        return None
    return round(total + sum(p for p in parts if p), 4)
