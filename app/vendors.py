"""Supplier records: who sells the item, where they are, how to reach them and what they showed.

Built only from stored evidence, so it re-runs on saved comparisons: search results and supplier pages
(contacts copied as written, with where and when they were seen), Google Maps listings, business-directory
listings and the offers found. Nothing is inferred: a supplier with no published price for the item is a
quote opportunity, and a missing phone number stays missing.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from . import extract as ex
from .evidence import Offer, Source, is_seller_source
from .suppliers import (AUCTION, B2B_MARKETPLACE, BUSINESS_DIRECTORY, CLASSIFIEDS, COMPLAINTS, DEALS, DIRECTORY,
                        DISTRIBUTOR, FORUM, GOVERNMENT, MANUFACTURER, MARKETPLACE, PROPERTY_SITE, RETAILER, REVIEW,
                        SEARCH, UNKNOWN, VIDEO, domain_of, is_platform_domain, lookup_by_name)

NOT_SUPPLIERS = {REVIEW, FORUM, VIDEO, COMPLAINTS, GOVERNMENT, DEALS, SEARCH}
TIERS = ("local", "regional", "canada", "us", "international")
TIER_LABELS = {"local": "Thunder Bay", "regional": "Northwestern Ontario / Ontario", "canada": "Elsewhere in Canada",
               "us": "United States", "international": "International", None: "Location not stated"}
# supplier types that can quote trade or volume pricing
TRADE_TYPES = {DISTRIBUTOR, MANUFACTURER, B2B_MARKETPLACE}
_PLATFORM_TYPES = {MARKETPLACE, BUSINESS_DIRECTORY, CLASSIFIEDS, AUCTION, PROPERTY_SITE}
_TRADE_WORDS = re.compile(r"\b(trade (?:account|pricing|customers?)|contractor pricing|volume (?:discount|pricing)|"
                          r"bulk (?:pricing|orders?|discount)|wholesale|request (?:a )?quote|rfq|account pricing|"
                          r"tiered pricing|price breaks?)\b", re.I)
# directory and social pages about one business (not search-results pages or feeds listing many)
_DIRECTORY_BUSINESS = re.compile(
    r"yellowpages\.ca/bus/|canada411\.ca/business/|yelp\.(?:ca|com)/biz/|"
    r"facebook\.com/(?!(?:groups|marketplace|events|search|people|watch|share|sharer|login|hashtag|photo|story|"
    r"permalink|reel|profile\.php|pages/category)\b)[A-Za-z0-9.\-]{3,}/?(?:about/?)?(?:[?#]|$)", re.I)


def directory_business_name(s: Source) -> str | None:
    """The business a directory or social page is about, from its title ("MGM Electric - Electrical Equipment &
    Supply Stores - Thunder Bay" -> "MGM Electric"); None for search-results pages listing many businesses."""
    if s.type != BUSINESS_DIRECTORY or not _DIRECTORY_BUSINESS.search(s.url):
        return None
    name = re.split(r"\s+[-|–]\s+", s.title)[0].strip()
    return name or None


def _norm_name(name: str) -> str:
    n = re.sub(r"\b(ltd|limited|inc|incorporated|corp|corporation|co|company|the)\b\.?", " ", (name or "").lower())
    return re.sub(r"[^a-z0-9]", "", n)


def _domain_for(info_name: str) -> str | None:
    for dom, info in DIRECTORY.items():
        if info.name == info_name:
            return dom
    return None


def _contact(value: str, basis: str, url: str | None, seen_at: str | None) -> dict[str, Any]:
    return {"value": value, "basis": basis, "url": url, "seen_at": seen_at}


class _Vendor:
    def __init__(self, key: str, name: str, domain: str | None):
        self.key, self.name, self.domain = key, name, domain
        self.type: str = UNKNOWN
        self.country: str | None = None
        self.website: str | None = f"https://{domain}/" if domain else None
        self.tier: str | None = None
        self.tier_basis: str | None = None
        self.tier_strength = 0  # 3 map/own-page address, 2 snippet address, 1 mention, 0 country only
        self.channels: set[str] = set()
        self.markets: set[str] = set()
        self.address: dict[str, Any] | None = None
        self.phones: list[dict[str, Any]] = []
        self.emails: list[dict[str, Any]] = []
        self.offers: list[Offer] = []
        self.source_ids: list[str] = []
        self.trade: list[dict[str, Any]] = []
        self.badges: list[str] = []
        self.rating: dict[str, Any] | None = None
        self.map_listing: str | None = None
        self.category: str | None = None
        self.seen: list[str] = []

    def set_tier(self, tier: str | None, basis: str | None, strength: int) -> None:
        if tier and (self.tier is None or strength > self.tier_strength):
            self.tier, self.tier_basis, self.tier_strength = tier, basis, strength

    def add_phone(self, value: str, basis: str, url: str | None, seen_at: str | None) -> None:
        key = ex.phone_key(value)
        if value and key not in (ex.phone_key(p["value"]) for p in self.phones) and len(self.phones) < 3:
            self.phones.append(_contact(value, basis, url, seen_at))

    def add_email(self, value: str, basis: str, url: str | None, seen_at: str | None) -> None:
        if value and value.lower() not in (e["value"].lower() for e in self.emails) and len(self.emails) < 3:
            self.emails.append(_contact(value, basis, url, seen_at))

    def add_contacts(self, found: dict[str, Any], basis: str, url: str | None, seen_at: str | None,
                     strength: int, home_city: str) -> None:
        for p in found.get("phones") or []:
            self.add_phone(p, basis, url, seen_at)
        for e in found.get("emails") or []:
            self.add_email(e, basis, url, seen_at)
        addrs = found.get("addresses") or []
        if addrs and (self.address is None or strength > self.address.get("_strength", 0)):
            self.address = {**_contact(addrs[0], basis, url, seen_at), "_strength": strength}
            tier, tbasis = ex.location_tier(addrs[0], home_city)
            if tier:
                self.set_tier(tier, f"{tbasis} ({basis})", strength)


def build_vendors(sources: list[Source], offers: list[Offer], local_businesses: list[dict[str, Any]] | None = None,
                  contact_pages: list[dict[str, Any]] | None = None, *, home_city: str = "Thunder Bay",
                  quantity: int | None = None) -> list[dict[str, Any]]:
    vendors: dict[str, _Vendor] = {}
    by_name: dict[str, str] = {}

    def get(domain: str | None, name: str) -> _Vendor:
        nn = _norm_name(name)
        key = domain or f"name:{nn}"
        if key not in vendors and nn and nn in by_name:
            key = by_name[nn]  # same business seen by name (map listing, Google Shopping seller)
        if key not in vendors:
            vendors[key] = _Vendor(key, name, domain)
        v = vendors[key]
        if nn and nn not in by_name:
            by_name[nn] = key
        return v

    src_by_id = {s.id: s for s in sources}
    # 1. web sources: sellers and single-business directory listings
    for s in sources:
        if s.type in NOT_SUPPLIERS:
            continue
        if s.type == BUSINESS_DIRECTORY:
            name = directory_business_name(s)
            if not name:
                continue
            v = get(None, name)
            v.channels.add("directory")
            v.source_ids.append(s.id)
            v.seen.append(s.retrieved_at)
            found = ex.contacts_in_text(f"{s.title}. {s.snippet}")
            v.add_contacts(found, f"directory listing ({s.domain})", s.url, s.retrieved_at, 2, home_city)
            if v.tier is None and home_city.lower() in f"{s.title} {s.snippet}".lower():
                v.set_tier("local", f"directory listing in {home_city} ({s.domain})", 2)
            continue
        if "shopping" in s.purposes and s.domain.endswith(("google.com", "google.ca")):
            continue  # Google product pages: the seller is the offer's supplier (step 3)
        if not is_seller_source(s):
            continue  # found by a review/spec search: not evidence that they sell it
        v = get(s.domain, s.name)
        v.type, v.country = s.type, s.country
        v.channels.update(c for c in s.channels if c not in ("reviews", "issues", "specs"))
        v.markets.update(s.markets)
        v.source_ids.append(s.id)
        v.seen.append(s.retrieved_at)
        v.badges = list(dict.fromkeys(v.badges + list(s.badges or [])))[:3]
        if s.contacts and s.type not in _PLATFORM_TYPES:
            own = s.contacts.get("basis") == "the supplier's own page"
            v.add_contacts(s.contacts, s.contacts.get("basis") or "page", s.contacts.get("url") or s.url,
                           s.contacts.get("seen_at"), 3 if own else 2, home_city)
        if s.location and s.type not in _PLATFORM_TYPES:
            basis = s.location.get("basis") or ""
            v.set_tier(s.location.get("tier"), basis, 3 if "page" in basis else (2 if "text" in basis else 1))
        m = _TRADE_WORDS.search(f"{s.title}. {s.snippet}")
        if m:
            v.trade.append({"text": m.group(0), "source_id": s.id, "url": s.url})

    # 2. map listings (Google Maps): name, address, phone and website as the listing shows them
    for b in local_businesses or []:
        dom = domain_of(b["website"]) if b.get("website") else None
        if is_platform_domain(dom):
            dom = None  # e.g. a Facebook page as "website": key by name, never pool with other businesses
        v = get(dom, b["name"])
        if v.name == (dom or "") or v.name.startswith(dom or "\0"):
            v.name = b["name"]  # a real business name beats a bare domain
        basis = "Google Maps listing"
        url, seen = b.get("listing_url"), b.get("retrieved_at")
        if b.get("website"):
            v.website = b["website"]
        if b.get("phone"):
            v.add_phone(b["phone"], basis, url, seen)
        if b.get("address"):
            v.address = {**_contact(b["address"], basis, url, seen), "_strength": 3}
            tier, tbasis = ex.location_tier(b["address"], home_city)
            if tier:  # an address that doesn't name a town or postal code doesn't place the business
                v.set_tier(tier, f"{tbasis} ({basis})", 3)
        if b.get("rating") is not None:
            v.rating = {"value": b["rating"], "count": b.get("reviews"), "best": 5.0,
                        "basis": "Google Maps rating (all reviews of the business, not of this item)"}
        v.map_listing = url
        v.category = b.get("category")
        v.channels.add("local_suppliers")
        v.markets.add("local")
        v.seen.append(seen or "")

    # 3. offers: products, prices and trade terms (Google Shopping sellers are matched by name)
    for o in offers:
        if o.supplier_type in NOT_SUPPLIERS or o.superseded():
            continue
        src = src_by_id.get(o.source_id or "")
        if o.supplier_domain.endswith(("google.com", "google.ca")):
            info = lookup_by_name(o.supplier)
            dom = _domain_for(info.name) if info else None
            v = get(dom, info.name if info else o.supplier)
        else:
            v = get(o.supplier_domain, src.name if src else o.supplier)
        if v.type == UNKNOWN and o.supplier_type != UNKNOWN:
            v.type = o.supplier_type
        v.country = v.country or o.country
        v.offers.append(o)
        if "shopping" in (src.purposes if src else []):
            v.channels.add("retail")
        for text in (o.moq, o.bulk):
            if text:
                v.trade.append({"text": text, "offer_id": o.id, "url": o.url})

    # 4. the suppliers' own pages read for contacts
    for cp in contact_pages or []:
        v = vendors.get(cp["domain"]) or vendors.get(by_name.get(_norm_name(cp.get("name") or ""), ""))
        if v is None or not cp.get("ok"):
            continue
        v.add_contacts(cp, "the supplier's own website", cp.get("contact_url") or cp["url"], cp.get("fetched_at"), 3,
                       home_city)

    out = [_record(v, quantity) for v in vendors.values()]
    out = [r for r in out if r]
    out.sort(key=lambda r: (TIERS.index(r["tier"]) if r["tier"] in TIERS else 9,
                            {"published": 0, "quote_required": 1, "no_price_seen": 2}[r["price_status"]],
                            r["name"].lower()))
    for i, r in enumerate(out, start=1):
        r["id"] = f"V{i}"
    return out


def _record(v: _Vendor, quantity: int | None) -> dict[str, Any] | None:
    if v.tier is None:
        if v.country == "CA":
            v.tier, v.tier_basis = "canada", "Canadian seller (location in Canada not stated)"
        elif v.country == "US":
            v.tier, v.tier_basis = "us", "US seller"
        elif v.country:
            v.tier, v.tier_basis = "international", f"seller country {v.country}"
    # a published price is an asking price: a sold price or a running bid isn't something they'll sell at
    priced = [o for o in v.offers if o.price is not None and o.price_kind == "asking"]
    other = [o for o in v.offers if o.price is not None and o.price_kind != "asking"]
    comparable = [o for o in priced if o.comparable and o.compare_value is not None]
    quotes = [o for o in v.offers if o.price_type == "quote_required"]
    if priced:
        status = "published"
    elif quotes:
        status = "quote_required"
    else:
        status = "no_price_seen"
    best = min(comparable, key=lambda o: o.compare_value) if comparable else (
        min(priced, key=lambda o: o.price_cad or 1e18) if priced else None)
    lowest = None
    if best is not None:
        lowest = {"offer_id": best.id, "price": best.price, "currency": best.currency, "price_cad": best.price_cad,
                  "compare_value": best.compare_value if best in comparable else None,
                  "price_label": best.price_label, "price_kind": best.price_kind, "comparable": best in comparable,
                  "observed_at": best.observed_at, "url": best.url}
    sells_trade = v.type in TRADE_TYPES or bool(v.trade)
    reasons = []
    if status == "quote_required":
        reasons.append("they show 'request a quote' for this item")
    elif status == "no_price_seen" and v.type not in (MARKETPLACE, BUSINESS_DIRECTORY, AUCTION, PROPERTY_SITE):
        reasons.append("only sold or bid prices were seen" if other else "no published price for this item was found")
    if sells_trade and status == "published" and (quantity or 0) >= 2:
        reasons.append(f"trade or volume pricing at {quantity} units may beat the published price")
    if v.tier == "local" and status != "quote_required" and not reasons:
        reasons.append("local supplier: ask for their price and stock")
    products = list(dict.fromkeys(o.product_title for o in v.offers if o.product_title))[:3]
    if not (v.offers or v.source_ids or v.map_listing):
        return None
    address = dict(v.address) if v.address else None
    if address:
        address.pop("_strength", None)
    return {
        "id": "", "name": v.name, "domain": v.domain, "website": v.website, "type": v.type, "country": v.country,
        "tier": v.tier, "tier_basis": v.tier_basis,
        "tier_label": ("Canada (location not stated)" if v.tier == "canada" and v.tier_strength == 0
                       else TIER_LABELS.get(v.tier, TIER_LABELS[None])),
        "channels": sorted(v.channels), "markets": sorted(v.markets),
        "address": address, "phones": v.phones, "emails": v.emails,
        "has_contact": bool(v.phones or v.emails),
        "products": products, "offer_ids": [o.id for o in v.offers], "priced_offers": len(priced),
        "sold_or_bid_prices": [{"offer_id": o.id, "price": o.price, "currency": o.currency, "price_kind": o.price_kind,
                                "observed_at": o.observed_at, "url": o.url} for o in other][:3],
        "price_status": status, "lowest": lowest,
        "trade_signals": _dedupe_trade(v.trade)[:4], "sells_trade": sells_trade,
        "quote_opportunity": bool(reasons), "quote_reasons": reasons,
        "rating": v.rating, "badges": v.badges, "map_listing": v.map_listing, "map_category": v.category,
        "source_ids": v.source_ids[:10], "first_seen": min((s for s in v.seen if s), default=None),
    }


def _dedupe_trade(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for t in items:
        k = t["text"].lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def vendor_summary(vendors: list[dict[str, Any]]) -> dict[str, Any]:
    by_tier: dict[str, int] = defaultdict(int)
    for v in vendors:
        by_tier[v["tier"] or "unknown"] += 1
    return {
        "total": len(vendors),
        "by_tier": dict(by_tier),
        "local": sum(1 for v in vendors if v["tier"] == "local"),
        "with_contact": sum(1 for v in vendors if v["has_contact"]),
        "with_published_price": sum(1 for v in vendors if v["price_status"] == "published"),
        "quote_required": sum(1 for v in vendors if v["price_status"] == "quote_required"),
        "quote_opportunities": sum(1 for v in vendors if v["quote_opportunity"]),
        "trade": sum(1 for v in vendors if v["sells_trade"]),
    }

