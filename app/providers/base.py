"""Provider interface and the error taxonomy shared by all search backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class ProviderError(Exception):
    """A search provider call failed. `kind` drives the message shown to users."""

    KINDS = {
        "not_configured": "API key not configured",
        "auth": "API key rejected",
        "quota": "plan / credit limit reached",
        "rate_limit": "rate limited",
        "timeout": "timed out",
        "network": "network unreachable",
        "bad_request": "request rejected",
        "bad_response": "unexpected response format",
        "upstream": "provider server error",
    }

    def __init__(self, provider: str, kind: str, detail: str = "", status: int | None = None):
        self.provider = provider
        self.kind = kind if kind in self.KINDS else "upstream"
        self.detail = detail
        self.status = status
        super().__init__(self.user_message)

    @property
    def retryable(self) -> bool:
        return self.kind in {"rate_limit", "timeout", "network", "upstream"}

    @property
    def user_message(self) -> str:
        base = f"{self.provider}: {self.KINDS[self.kind]}"
        if self.status:
            base += f" (HTTP {self.status})"
        return f"{base} - {self.detail}" if self.detail else base

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "kind": self.kind, "status": self.status,
                "message": self.user_message, "retryable": self.retryable}


@dataclass
class SearchHit:
    provider: str
    query: str
    purpose: str
    url: str
    title: str
    snippet: str
    rank: int
    raw_content: str | None = None
    score: float | None = None
    published_date: str | None = None
    # set by the research plan: buying channel, market and round of the search that found it
    channel: str | None = None
    market: str | None = None
    round: int = 1


@dataclass
class ShoppingListing:
    provider: str
    query: str
    title: str
    supplier: str | None
    url: str
    price_text: str | None
    price_value: float | None
    old_price_text: str | None = None
    rating: float | None = None
    reviews: int | None = None
    delivery: str | None = None
    condition: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class WebSearchProvider(Protocol):
    name: str
    credits_used: float

    async def search(self, query: str, *, purpose: str, max_results: int, depth: str,
                     country: str | None, include_raw: bool, domains: list[str] | None = None) -> list[SearchHit]: ...


@dataclass
class LocalBusiness:
    """A business from a map listing (Google Maps via SerpApi). Fields are as the listing shows them."""
    name: str
    address: str | None
    phone: str | None
    website: str | None
    category: str | None
    rating: float | None
    reviews: int | None
    listing_url: str | None
    query: str
    provider: str
    retrieved_at: str = ""


class ShoppingProvider(Protocol):
    name: str
    credits_used: float

    async def shopping(self, query: str) -> list[ShoppingListing]: ...


def classify_http_error(provider: str, exc: Exception) -> ProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(provider, "timeout", "no response in time; try again")
    if isinstance(exc, httpx.ProxyError):
        return ProviderError(provider, "network", "the network/proxy refused the connection (check firewall or allowed hosts)")
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return ProviderError(provider, "network", "could not connect (check internet access / firewall)")
    if isinstance(exc, httpx.HTTPError):
        return ProviderError(provider, "network", type(exc).__name__)
    return ProviderError(provider, "upstream", str(exc)[:200])
