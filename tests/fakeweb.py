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
    serp_body: Any = None           # Google Shopping (and Google web search unless serp_web_body is set)
    serp_maps_body: Any = None      # Google Maps local results
    serp_web_body: Any = None
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
        """Which fixture set a query gets, from its wording (the research plan's phrasing)."""
        q = query.lower()
        if " site:" in q:
            return "site"  # SerpApi site-restricted search: answered from all fixture sets, filtered by site
        for purpose, needle in (("wholesale", "trade account"), ("other", "wholesale manufacturer"),
                                ("wholesale", "wholesale"), ("issues", "problems"), ("specs", "specifications"),
                                ("reviews", " review"), ("alternatives", "alternative"), ("cross_border", "usd"),
                                ("suppliers", "supplier distributor"), ("suppliers", "distributor canada"), ("suppliers", " supplier "),
                                ("price", " price")):
            if needle in q:
                return purpose
        return "other"

    def site_results(self, domains: list[str]) -> list[dict[str, Any]]:
        """A site-restricted search: every fixture result on those sites (as a real include_domains search)."""
        out, seen = [], set()
        for rows in self.tavily_results.values():
            for r in rows:
                host = (urlparse(r["url"]).hostname or "").removeprefix("www.")
                if any(host == d or host.endswith("." + d) for d in domains) and r["url"] not in seen:
                    seen.add(r["url"])
                    out.append(r)
        return out

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
            if body.get("include_domains"):
                results = self.site_results(body["include_domains"])
            else:
                results = self.tavily_results.get(purpose, [])
            return httpx.Response(200, json={"query": body["query"], "results": results, "response_time": 0.5})
        if host == "serpapi.com":
            if self.serp_body is None:
                return httpx.Response(401, json={"error": "Invalid API key."})
            engine = parse_qs(urlparse(url).query).get("engine", [""])[0]
            if engine == "google_maps":
                return httpx.Response(self.serp_status, json=self.serp_maps_body or {"local_results": []})
            if engine == "google_shopping":
                return httpx.Response(self.serp_status, json=self.serp_body)
            return httpx.Response(self.serp_status, json=self.serp_web_body or self.serp_body)
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


# A fictional Thunder Bay supplier: a Google Maps listing, its own site with a contact page, and a product page
# that only a search restricted to its site finds. 555-01xx phone numbers are reserved for fiction.
LOCAL_SITE = "https://www.northerntoolsupply-example.ca/"
SERP_MAPS = {"local_results": [
    {"title": "Northern Tool Supply Ltd", "address": "123 Memorial Ave, Thunder Bay, ON P7B 3Z9",
     "phone": "(807) 555-0142", "website": LOCAL_SITE, "type": "Tool store", "rating": 4.5, "reviews": 37,
     "data_cid": "1234567890"},
]}


def with_local_supplier(fw: FakeWeb) -> FakeWeb:
    fw.serp_maps_body = SERP_MAPS
    fw.pages[LOCAL_SITE] = (200, '<html><body><a href="/contact-us">Contact us</a> Call 807-555-0142</body></html>')
    fw.pages[LOCAL_SITE + "contact-us"] = (200, '<html><body><a href="mailto:sales@northerntoolsupply-example.ca">'
                                                "Email sales</a> 123 Memorial Ave, Thunder Bay, ON P7B 3Z9</body></html>")
    fw.tavily_results["local_site"] = [tavily_result(
        LOCAL_SITE + "acme-tx-4400", "Acme TX-4400 Torque Widget - Northern Tool Supply",
        "Acme TX-4400 torque widget. Call for trade pricing on orders of 5 or more.")]
    return fw
