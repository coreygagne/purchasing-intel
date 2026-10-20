"""Turn raw provider output into numbered sources and price offers.

Each offer records exactly where its price came from (`price_basis`) and
the verbatim text it was read from (`evidence_quote`), so the UI can label
it as quoted, snippet-only, calculated or estimated.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import extract as ex
from .db import iso
from .fetch import FetchResult
from .providers.base import SearchHit, ShoppingListing
from .suppliers import (B2B_MARKETPLACE, CLASSIFIEDS, COUNTRY_CURRENCY, DISTRIBUTOR, GOVERNMENT, MANUFACTURER,
                        MARKETPLACE, RETAILER, REVIEW_TYPES, UNKNOWN, classify_source, domain_of,
                        lookup_by_name)

SELLER_PURPOSES = {"price", "suppliers", "wholesale", "cross_border", "input_url", "ai_suggested", "shopping"}
SELLER_TYPES = {MANUFACTURER, DISTRIBUTOR, RETAILER, MARKETPLACE, B2B_MARKETPLACE, CLASSIFIEDS, UNKNOWN}

PRICE_BASIS_LABELS = {
    "structured_data": "Quoted: supplier page data (schema.org)",
    "shopping_api": "Quoted: Google Shopping listing (via SerpApi)",
    "llm_verified": "Quoted: page text, AI-extracted, exact text verified",
    "snippet": "Seen in search snippet: may be outdated, verify on page",
    "none": "No price published",
}
CONFIDENCE = {"structured_data": "high", "shopping_api": "medium", "llm_verified": "medium", "snippet": "low", "none": "n/a"}


@dataclass
class Source:
    id: str
    url: str
    domain: str
    title: str
    snippet: str
    type: str
    name: str
    country: str | None
    country_basis: str
    in_directory: bool
    purposes: list[str]
    queries: list[str]
    provider: str
    retrieved_at: str
    published_date: str | None = None
    raw_content: str | None = None
    fetch: dict[str, Any] | None = None
    page_text: str | None = None

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw_content", None)
        d.pop("page_text", None)
        return d


@dataclass
class Offer:
    id: str
    source_id: str | None
    url: str
    supplier: str
    supplier_domain: str
    supplier_type: str
    supplier_in_directory: bool
    country: str | None
    country_basis: str
    product_title: str
    price: float | None
    price_high: float | None
    currency: str | None
    currency_basis: str
    price_text: str | None
    price_type: str  # listed | range | quote_required | unclear | none
    price_basis: str
    evidence_quote: str | None
    observed_at: str
    provider: str
    condition: str | None = None
    match_level: str = "unverified"
    match_notes: list[str] = field(default_factory=list)
    pack_qty: int | None = None
    pack_text: str | None = None
    availability: str | None = None
    shipping_text: str | None = None
    shipping_cost: float | None = None
    shipping_scope: str = "unknown"  # "canada" when the shipping terms are known to apply to Canada
    warranty: str | None = None
    moq: str | None = None
    bulk: str | None = None
    rating: dict[str, Any] | None = None
    specs: dict[str, str] = field(default_factory=dict)
    identifiers: dict[str, str] = field(default_factory=dict)
    is_reference: bool = False
    notes: list[str] = field(default_factory=list)
    # filled in by analysis
    price_cad: float | None = None
    fx_rate: float | None = None
    fx_date: str | None = None
    unit_price: float | None = None
    unit_price_cad: float | None = None
    delivered: dict[str, Any] | None = None
    comparable: bool = False
    exclusion_reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    confidence: str = "n/a"
    price_label: str = ""
    compare_value: float | None = None  # CAD value used for ranking (listing or per-unit price)

    def superseded(self) -> bool:
        return any(n.startswith("Superseded") for n in self.notes)


# ------------------------------------------------------------------ sources


_TRACKING_PARAM = re.compile(r"^(utm_[a-z]+|gclid|gclsrc|dclid|fbclid|msclkid|mc_cid|mc_eid|srsltid|_ga|ref|ref_src)$", re.I)


def canonical_url(url: str) -> str:
    """URL identity for de-duplication: drops the fragment and tracking parameters only."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not _TRACKING_PARAM.match(k)])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", query, ""))


def build_sources(hits: list[SearchHit], brand_words: list[str]) -> list[Source]:
    by_url: dict[str, Source] = {}
    order: list[str] = []
    for h in hits:
        key = canonical_url(h.url)
        if key in by_url:
            s = by_url[key]
            if h.purpose not in s.purposes:
                s.purposes.append(h.purpose)
            if h.query not in s.queries:
                s.queries.append(h.query)
            if len(h.snippet) > len(s.snippet):
                s.snippet = h.snippet
            if h.raw_content and not s.raw_content:
                s.raw_content = h.raw_content
            continue
        cls = classify_source(h.url, h.title, brand_words)
        by_url[key] = Source(
            id="", url=h.url, domain=domain_of(h.url), title=h.title.strip() or domain_of(h.url),
            snippet=h.snippet.strip(), type=cls.type, name=cls.name, country=cls.country,
            country_basis=cls.country_basis, in_directory=cls.in_directory, purposes=[h.purpose],
            queries=[h.query], provider=h.provider, retrieved_at=iso(), published_date=h.published_date,
            raw_content=h.raw_content,
        )
        order.append(key)
    sources = [by_url[k] for k in order]
    for i, s in enumerate(sources, start=1):
        s.id = f"S{i}"
    return sources


def add_source(sources: list[Source], *, url: str, title: str, snippet: str, purpose: str, provider: str,
               brand_words: list[str]) -> Source:
    cls = classify_source(url, title, brand_words)
    s = Source(id=f"S{len(sources) + 1}", url=url, domain=domain_of(url), title=title or domain_of(url),
               snippet=snippet, type=cls.type, name=cls.name, country=cls.country, country_basis=cls.country_basis,
               in_directory=cls.in_directory, purposes=[purpose], queries=[], provider=provider, retrieved_at=iso())
    sources.append(s)
    return s


def is_seller_source(s: Source) -> bool:
    return s.type in SELLER_TYPES and bool(SELLER_PURPOSES & set(s.purposes))


# ------------------------------------------------------------------- offers


DOLLAR_CURRENCIES = {"CAD", "USD", "AUD", "NZD", "HKD", "SGD", "MXN", "TWD"}


def _resolve_currency(match: ex.PriceMatch | None, stated: str | None, country: str | None,
                      region_default: str | None = None) -> tuple[str | None, str]:
    """Currency of a price. 'stated' when the source says it; otherwise a labelled inference or unknown."""
    if stated:
        return stated.upper(), "stated"
    if match and match.currency:
        return match.currency, "stated"
    symbol = match.symbol if match else ""
    if symbol not in ("", "$"):
        return None, "unknown"
    if region_default:
        return region_default, "inferred from Google Shopping Canada region"
    cur = COUNTRY_CURRENCY.get(country or "")
    if cur and (symbol == "" or cur in DOLLAR_CURRENCIES):
        return cur, "inferred from seller country"
    return None, "unknown"


def _base_offer(oid: str, src: Source | None, *, url: str, supplier: str | None, title: str, provider: str,
                brand_words: list[str]) -> dict[str, Any]:
    if src is not None:
        cls_name, cls_type, country, basis, in_dir = src.name, src.type, src.country, src.country_basis, src.in_directory
    else:
        c = classify_source(url, title, brand_words)
        cls_name, cls_type, country, basis, in_dir = c.name, c.type, c.country, c.country_basis, c.in_directory
    return dict(id=oid, source_id=src.id if src else None, url=url,
                supplier=supplier or cls_name, supplier_domain=domain_of(url), supplier_type=cls_type,
                supplier_in_directory=in_dir, country=country, country_basis=basis, product_title=title.strip()[:300],
                observed_at=iso(), provider=provider)


def _text_fields(title: str, body: str = "") -> dict[str, Any]:
    """Terms found in a listing. Pack size and condition come from the product title only:
    body text mentions stock counts ("3 units left"), related products and usage ("used by pros")."""
    text = f"{title} {body}"
    pack = ex.pack_quantity(title)
    ship = ex.shipping_text(text)
    return dict(pack_qty=pack[0] if pack else None, pack_text=pack[1] if pack else None,
                availability=ex.availability_text(text), shipping_text=ship,
                shipping_cost=ex.shipping_cost_from_text(ship), warranty=ex.warranty_text(text),
                moq=ex.moq_text(text), bulk=ex.bulk_signal(text), condition=ex.detect_condition(title))


class OfferBuilder:
    def __init__(self, brand_words: list[str], tokens: list[str] | None = None):
        self.brand_words = brand_words
        self.tokens = tokens or []
        self.offers: list[Offer] = []
        self.unclear_sources: set[str] = set()  # pages showing several prices for the product

    def _next_id(self) -> str:
        return f"O{len(self.offers) + 1}"

    def from_shopping(self, listings: list[ShoppingListing], sources: list[Source]) -> None:
        for l in listings:
            src = add_source(sources, url=l.url, title=l.title, snippet=" · ".join(
                x for x in [l.price_text, l.supplier, l.delivery] if x), purpose="shopping",
                provider=l.provider, brand_words=self.brand_words)
            match = ex.parse_price_text(l.price_text or "") if l.price_text else None
            supplier = l.supplier or src.name
            if src.domain.endswith(("google.com", "google.ca")):
                # Google product page link: the seller is the listing's "source"
                info = lookup_by_name(l.supplier or "")
                src.name = supplier
                if info:
                    src.type, src.country, src.country_basis, src.in_directory = info.type, info.country, "directory", True
                else:
                    src.type, src.country, src.country_basis, src.in_directory = UNKNOWN, None, "unknown", False
            currency, cbasis = _resolve_currency(match, None, src.country, region_default="CAD")
            base = _base_offer(self._next_id(), src, url=l.url, supplier=supplier, title=l.title,
                               provider=l.provider, brand_words=self.brand_words)
            base.update(supplier_type=src.type, country=src.country, country_basis=src.country_basis,
                        supplier_in_directory=src.in_directory)
            fields = _text_fields(l.title, l.delivery or "")
            if l.delivery:
                fields["shipping_text"] = l.delivery
                fields["shipping_cost"] = ex.shipping_cost_from_text(l.delivery) if re.match(r"(?i)free", l.delivery) else _delivery_cost(l.delivery)
                fields["shipping_scope"] = "canada"  # Google Shopping Canada shows delivery terms for Canada
            if l.condition:
                fields["condition"] = ex.detect_condition(l.condition) or l.condition.lower()
            price = l.price_value if l.price_value is not None else (match.amount if match else None)
            offer = Offer(**base, **fields, price=price, price_high=match.high if match else None,
                          currency=currency, currency_basis=cbasis, price_text=l.price_text,
                          price_type="listed" if price is not None else "none",
                          price_basis="shopping_api" if price is not None else "none",
                          evidence_quote=l.price_text)
            if l.rating is not None:
                offer.rating = {"value": l.rating, "count": l.reviews, "best": 5.0,
                                "basis": "Google Shopping product rating (aggregated by Google)"}
            if not l.extra.get("direct_link"):
                offer.notes.append("Link opens Google's product page; seller page not linked directly.")
            self.offers.append(offer)

    def from_structured(self, src: Source, products: list[ex.StructuredProduct], target_tokens: list[str],
                        fetched_at: str, is_reference: bool = False) -> bool:
        """Add offers from schema.org data on a fetched page. Returns True if any price was found."""
        with_offers = [p for p in products if p.offers]
        if not with_offers:
            return False
        # Prefer the product whose identifiers match the request
        def score(p: ex.StructuredProduct) -> int:
            text = " ".join(x for x in [p.name, p.sku, p.mpn] if x)
            levels = {"exact": 3, "variant": 2, "unverified": 1, "compatible": 0, "different": 0}
            return levels.get(ex.match_offer(target_tokens, text).level, 0)
        product = sorted(with_offers, key=score, reverse=True)[0]
        priced = [o for o in product.offers if o.price is not None]
        if not priced:
            return False
        title = product.name or src.title
        so = priced[0]
        distinct = {(round(o.price, 2), o.currency, o.aggregate) for o in priced}
        base = _base_offer(self._next_id(), src, url=src.url, supplier=None, title=title, provider="page fetch",
                           brand_words=self.brand_words)
        base["observed_at"] = fetched_at
        if so.seller and src.type == MARKETPLACE and len(distinct) == 1:
            base["supplier"] = f"{src.name} (seller: {so.seller})"
        fields = _text_fields(title, src.snippet)
        fields["condition"] = so.condition or fields["condition"]
        if so.availability:
            fields["availability"] = re.sub(r"(?<!^)(?=[A-Z])", " ", so.availability).lower()
        if src.country == "CA":
            fields["shipping_scope"] = "canada"
        notes: list[str] = []
        if len(distinct) > 1:
            # Variant/seller offers under one product: which price is "the" item is unclear - don't rank it.
            shown = "; ".join(f"{o.currency or '?'} {o.price:,.2f}" + (f" ({o.sku or o.name})" if (o.sku or o.name) else "")
                              for o in priced[:5])
            self.unclear_sources.add(src.id)
            offer = Offer(**base, **fields, price=None, price_high=None, currency=None, currency_basis="unknown",
                          price_text=shown, price_type="unclear", price_basis="structured_data",
                          evidence_quote=f"schema.org offers on page: {shown}", is_reference=is_reference,
                          notes=[f"The page lists {len(priced)} prices for this product (variants, kits or sellers); "
                                 "open it to see which one matches."])
        else:
            currency, cbasis = _resolve_currency(None, so.currency, src.country)
            if so.aggregate:
                price_type = "range"
                notes.append("'From' price across several offers on the page (may include other sellers, "
                             "variants or conditions).")
            else:
                price_type = "range" if so.price_high else "listed"
            offer = Offer(**base, **fields, price=so.price, price_high=so.price_high, currency=currency,
                          currency_basis=cbasis, price_text=so.raw_price or None, price_type=price_type,
                          price_basis="structured_data",
                          evidence_quote=f'schema.org price "{so.raw_price}" {so.currency or ""}'.strip(),
                          is_reference=is_reference, notes=notes)
        offer.identifiers = {k: v for k, v in {"sku": product.sku, "mpn": product.mpn, "gtin": product.gtin,
                                                "brand": product.brand}.items() if v}
        offer.specs = dict(product.specs)
        if product.rating_value is not None:
            offer.rating = {"value": product.rating_value, "count": product.rating_count,
                            "best": product.rating_best or 5.0,
                            "basis": "Customer rating published on the supplier's page"}
        self.offers.append(offer)
        return True

    def from_snippet(self, src: Source) -> None:
        """Price text visible in the search result itself (lowest confidence)."""
        text = f"{src.title}. {src.snippet}"
        quote = ex.quote_required(text)
        prices = ex.listing_prices(src.snippet, self.tokens) or ex.listing_prices(src.title, self.tokens)
        base = _base_offer(self._next_id(), src, url=src.url, supplier=None, title=src.title,
                           provider=src.provider, brand_words=self.brand_words)
        fields = _text_fields(src.title, src.snippet)
        if src.country == "CA":
            fields["shipping_scope"] = "canada"
        if not prices:
            if quote:
                self.offers.append(Offer(**base, **fields, price=None, price_high=None, currency=None,
                                         currency_basis="unknown", price_text=quote, price_type="quote_required",
                                         price_basis="none", evidence_quote=quote))
            return
        distinct = {(round(p.amount, 2), p.currency) for p in prices}
        if len(distinct) > 1:
            shown = ", ".join(p.raw for p in prices[:4])
            self.offers.append(Offer(**base, **fields, price=None, price_high=None, currency=None,
                                     currency_basis="unknown", price_text=shown, price_type="unclear",
                                     price_basis="snippet", evidence_quote=src.snippet[:300],
                                     notes=[f"Several prices in the snippet ({shown}); open the page to see which applies."]))
            return
        p = prices[0]
        currency, cbasis = _resolve_currency(p, None, src.country)
        self.offers.append(Offer(**base, **fields, price=p.amount, price_high=p.high, currency=currency,
                                 currency_basis=cbasis, price_text=p.raw,
                                 price_type="range" if p.is_range else "listed", price_basis="snippet",
                                 evidence_quote=_around(src.snippet or src.title, p.raw)))

    def from_llm(self, src: Source, item: dict[str, Any], context: str) -> None:
        """Offer read from page text by the language model. The caller has verified that `context`
        (the quote plus the text just before it) is verbatim source text containing the price.
        Title, supplier, pack size and condition are taken from the source, never from the model."""
        base = _base_offer(self._next_id(), src, url=src.url, supplier=None, title=src.title,
                           provider="Claude (verified)", brand_words=self.brand_words)
        p = ex.parse_price_text(item["price_text"])
        stated = (item.get("currency_stated") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", stated) or stated not in context.upper():
            stated = ""  # only trust a currency the quoted text actually shows
        currency, cbasis = _resolve_currency(p, stated or None, src.country)
        fields = _text_fields(src.title, context)  # pack size from the page title only
        fields["condition"] = fields["condition"] or ex.detect_condition(context)
        if item.get("condition") in ("used", "refurbished", "open box") and not fields["condition"]:
            fields["condition"] = item["condition"]  # only ever more cautious than the text
        for key in ("shipping_text", "warranty", "moq", "availability"):
            if item.get(key) and ex_text_in(item[key], src):
                fields[key] = item[key]
        if fields.get("shipping_text"):
            fields["shipping_cost"] = ex.shipping_cost_from_text(fields["shipping_text"])
        if src.country == "CA":
            fields["shipping_scope"] = "canada"
        self.offers.append(Offer(**base, **fields, price=p.amount if p else None, price_high=p.high if p else None,
                                 currency=currency, currency_basis=cbasis, price_text=item["price_text"],
                                 price_type="range" if p and p.is_range else "listed", price_basis="llm_verified",
                                 evidence_quote=context))


def ex_text_in(text: str, src: Source) -> bool:
    hay = _squash(" ".join(x for x in [src.title, src.snippet, src.raw_content or "", src.page_text or ""] if x))
    return _squash(text) in hay


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _delivery_cost(text: str) -> float | None:
    m = re.search(r"\$\s?(\d+(?:\.\d\d)?)\s*(?:delivery|shipping)", text, re.I)
    return float(m.group(1)) if m else None


def _around(text: str, needle: str, width: int = 120) -> str:
    i = text.find(needle)
    if i < 0:
        return text[: width * 2]
    start, end = max(0, i - width), min(len(text), i + len(needle) + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


_SEARCH_PAGE_RE = re.compile(r"(/s\?|/search\b|/sch/|/shop\?|/shop/[^/?]*\?|[?&](q|k|_nkw|query|search_query|keyword|"
                             r"searchterm|text)=)", re.I)


def is_search_results_url(url: str) -> bool:
    """A site's own search-results page lists many products/sellers; a price there is ambiguous."""
    return bool(_SEARCH_PAGE_RE.search(url or ""))


def apply_match(offers: list[Offer], tokens: list[str], sources_by_id: dict[str, Source]) -> None:
    for o in offers:
        if o.price_basis == "llm_verified":
            # the page title names the main product; the price may belong to an accessory on the same page
            text = o.evidence_quote or ""
        else:
            text = " ".join([o.product_title] + list(o.identifiers.values()))
            if o.price_basis == "snippet" and o.source_id in sources_by_id:
                text += " " + (o.evidence_quote or "")
        m = ex.match_offer(tokens, text)
        o.match_level, o.match_notes = m.level, m.notes
        o.price_label = PRICE_BASIS_LABELS.get(o.price_basis, o.price_basis)
        if o.price_type == "quote_required":
            o.price_label = "Quote required"
        o.confidence = CONFIDENCE.get(o.price_basis, "n/a")
        if is_search_results_url(o.url) and o.confidence in ("high", "medium"):
            o.confidence = "low"


def is_review_type(t: str) -> bool:
    return t in REVIEW_TYPES or t == GOVERNMENT
