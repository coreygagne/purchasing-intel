"""A simulated internet for tests ONLY.

Every product, supplier page and price here is a fictional TEST FIXTURE
("Acme TX-4400"). The application never loads this module; tests inject it
through httpx.MockTransport so the real provider/fetch code paths run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import httpx

PRODUCT = "Acme TX-4400 torque widget"


def jsonld_page(name: str, price: str | None, currency: str | None, *, mpn: str = "TX-4400",
                availability: str = "https://schema.org/InStock", condition: str = "https://schema.org/NewCondition",
                rating: tuple[float, int] | None = None, extra_text: str = "") -> str:
    product: dict[str, Any] = {"@context": "https://schema.org", "@type": "Product", "name": name,
                               "brand": {"@type": "Brand", "name": "Acme"}, "mpn": mpn, "sku": "SKU-998877"}
    if price is not None:
        product["offers"] = {"@type": "Offer", "price": price, "priceCurrency": currency,
                             "availability": availability, "itemCondition": condition}
    if rating:
        product["aggregateRating"] = {"@type": "AggregateRating", "ratingValue": rating[0], "reviewCount": rating[1]}
    return (f"<html><head><title>{name}</title><script type=\"application/ld+json\">{json.dumps(product)}</script>"
            f"</head><body><h1>{name}</h1><p>{extra_text}</p></body></html>")


def tavily_result(url: str, title: str, content: str, raw: str | None = None) -> dict[str, Any]:
    return {"url": url, "title": title, "content": content, "score": 0.8, "raw_content": raw}


DEFAULT_RESULTS: dict[str, list[dict[str, Any]]] = {
    "price": [
        tavily_result("https://www.grainger.ca/en/product/ACME-TX-4400", "Acme TX-4400 Torque Widget | Grainger Canada",
                      "Acme TX-4400 torque widget, 1/2 in drive. Sign in to see your price."),
        tavily_result("https://www.kmstools.com/acme-tx-4400-torque-widget", "Acme TX-4400 Torque Widget - KMS Tools",
                      "Acme TX-4400 torque widget $349.99 In stock. 3-year limited warranty. Free shipping"),
        tavily_result("https://www.amazon.com/Acme-TX-4400/dp/B0TEST", "Amazon.com: Acme TX-4400 Torque Widget",
                      "Acme TX-4400 Torque Widget US$219.00 FREE delivery"),
        tavily_result("https://www.princessauto.com/en/acme-tx-4400-refurb", "Acme TX-4400 Torque Widget (Refurbished)",
                      "Factory reconditioned Acme TX-4400. $199.99"),
    ],
    "suppliers": [
        tavily_result("https://www.tenaquip.com/product/acme-tx-4400", "ACME TX-4400 TORQUE WIDGET | Tenaquip",
                      "Acme TX-4400 torque widget. Request a quote for pricing."),
        tavily_result("https://www.homedepot.ca/product/acme-tx-4400-kit/100200", "Acme TX-4410 Torque Widget Kit",
                      "Acme TX-4410 kit with case $429.00"),
    ],
    "wholesale": [
        tavily_result("https://www.alibaba.com/product-detail/torque-widget_160.html",
                      "Wholesale torque widget TX4400 compatible - Alibaba.com",
                      "US$45.00-62.00 / piece. Min. order: 200 pieces. Bulk pricing available."),
    ],
    "reviews": [
        tavily_result("https://www.protoolreviews.com/acme-tx-4400-review/", "Acme TX-4400 Review - Pro Tool Reviews",
                      "The Acme TX-4400 is well-built and reliable in our testing. Some users report the clutch overheats under continuous use."),
        tavily_result("https://www.reddit.com/r/Tools/comments/abc/acme_tx4400/", "Acme TX-4400 after 2 years : r/Tools",
                      "Mine failed after 18 months, warranty replaced it quickly. Still highly recommend it."),
    ],
    "issues": [
        tavily_result("https://recalls-rappels.canada.ca/en/alert-recall/acme-widgets", "Acme widgets recall notice",
                      "Health Canada: no recall has been issued for the TX-4400; a recall was issued for the older TX-3000 model."),
    ],
    "specs": [
        tavily_result("https://www.acmetools-example.com/tx-4400", "TX-4400 Specifications - Acme",
                      "Acme TX-4400: 1/2 in drive, 400 ft-lb max torque, 2-year warranty."),
    ],
}


@dataclass
class FakeWeb:
    tavily_status: int = 200
    tavily_body: Any = None  # override whole body
    tavily_fail_purposes: set[str] = field(default_factory=set)
    tavily_timeout: bool = False
    tavily_results: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: json.loads(json.dumps(DEFAULT_RESULTS)))
    serp_body: Any = None
    serp_status: int = 200
    fx_ok: bool = True
    fx_rate: str = "1.3800"
    pages: dict[str, tuple[int, str]] = field(default_factory=dict)
    robots: dict[str, tuple[int, str]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    extra_handlers: list[Callable[[httpx.Request], httpx.Response | None]] = field(default_factory=list)

    def __post_init__(self):
        if not self.pages:
            self.pages = {
                "https://www.kmstools.com/acme-tx-4400-torque-widget":
                    (200, jsonld_page("Acme TX-4400 Torque Widget", "339.99", "CAD", rating=(4.6, 87),
                                      extra_text="3-year limited warranty. Free shipping on orders over $99.")),
                "https://www.grainger.ca/en/product/ACME-TX-4400": (403, "Forbidden"),
                "https://www.amazon.com/Acme-TX-4400/dp/B0TEST": (503, "Robot check"),
                "https://www.princessauto.com/en/acme-tx-4400-refurb":
                    (200, jsonld_page("Acme TX-4400 Torque Widget - Refurbished", "199.99", "CAD",
                                      condition="https://schema.org/RefurbishedCondition")),
                "https://www.homedepot.ca/product/acme-tx-4400-kit/100200":
                    (200, jsonld_page("Acme TX-4410 Torque Widget Kit", "429.00", "CAD", mpn="TX-4410")),
                "https://www.tenaquip.com/product/acme-tx-4400": (200, "<html><body>Request a quote</body></html>"),
            }

    def purpose_of(self, query: str) -> str:
        q = query.lower()
        for purpose, needle in (("suppliers", "supplier distributor"), ("wholesale", "wholesale"),
                                ("issues", "problems"), ("specs", "specifications"), ("reviews", " review"),
                                ("alternatives", "alternative"), ("cross_border", "usd"), ("price", " price")):
            if needle in q:
                return purpose
        return "other"

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(f"{request.method} {url}")
        for h in self.extra_handlers:
            r = h(request)
            if r is not None:
                return r
        host = request.url.host
        if host == "api.tavily.com":
            if self.tavily_timeout:
                raise httpx.ReadTimeout("timed out", request=request)
            body = json.loads(request.content or b"{}")
            if request.headers.get("authorization") != "Bearer tvly-test-key":
                return httpx.Response(401, json={"detail": {"error": "Unauthorized: missing or invalid API key."}})
            purpose = self.purpose_of(body.get("query", ""))
            if purpose in self.tavily_fail_purposes:
                return httpx.Response(500, json={"detail": {"error": "Internal error"}})
            if self.tavily_status != 200:
                return httpx.Response(self.tavily_status, json={"detail": {"error": "simulated failure"}})
            if self.tavily_body is not None:
                return httpx.Response(200, json=self.tavily_body)
            return httpx.Response(200, json={"query": body["query"], "results": self.tavily_results.get(purpose, []),
                                             "response_time": 0.5})
        if host == "serpapi.com":
            if self.serp_body is None:
                return httpx.Response(401, json={"error": "Invalid API key."})
            return httpx.Response(self.serp_status, json=self.serp_body)
        if host == "www.bankofcanada.ca":
            if not self.fx_ok:
                return httpx.Response(503, text="unavailable")
            series = request.url.path.split("/")[3]
            return httpx.Response(200, json={"observations": [{"d": "2026-10-19", series: {"v": self.fx_rate}}]})
        if request.url.path == "/robots.txt":
            origin = f"{request.url.scheme}://{host}"
            status, text = self.robots.get(origin, (404, ""))
            return httpx.Response(status, text=text)
        key = url.split("#")[0]
        if key in self.pages:
            status, html = self.pages[key]
            return httpx.Response(status, text=html, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, text="not found", headers={"content-type": "text/html"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


SERP_SHOPPING = {
    "search_metadata": {"status": "Success"},
    "shopping_results": [
        {"position": 1, "title": "Acme TX-4400 Torque Widget", "product_link": "https://www.google.com/shopping/product/1",
         "source": "Canadian Tire", "price": "$329.99", "extracted_price": 329.99, "rating": 4.4, "reviews": 120,
         "delivery": "Free delivery"},
        {"position": 2, "title": "Acme TX-4400 Torque Widget", "link": "https://www.ebay.ca/itm/123",
         "source": "eBay - toolseller99", "price": "$289.00", "extracted_price": 289.0,
         "second_hand_condition": "used"},
    ],
}
