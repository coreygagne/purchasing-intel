"""Research plan: what to search for, where, and through which buying channels - then follow the leads.

Local first (Thunder Bay), then Northwestern Ontario / Ontario, the rest of Canada, the US and overseas,
across the buying channels that fit the item's category. Later rounds follow leads found earlier: suppliers
that carry the category but showed no price for the item, brands' dealer networks, manufacturer sites and
alternative names. Research stops when a round adds no new suppliers or prices, or when the depth's query
budget is used. Expensive or high-risk purchases get a deeper search.

Search phrasing and channel choices are planning only: nothing here is evidence. Evidence comes from what
the searches and supplier pages actually return.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from . import extract as ex

HOME = {"company": "Midcontinent Terminal", "city": "Thunder Bay", "province": "ON", "region": "Northwestern Ontario",
        "maps_ll": "@48.3809,-89.2477,12z"}

MARKETS = ("local", "regional", "canada", "us", "international")
MARKET_LABELS = {"local": "Thunder Bay (local)", "regional": "Northwestern Ontario / Ontario",
                 "canada": "Rest of Canada", "us": "United States", "international": "International",
                 "any": "Not market-specific"}

CHANNELS: dict[str, str] = {
    "local_suppliers": "Local suppliers and dealers",
    "directory": "Business directories",
    "retail": "Retailers",
    "distributor": "Distributors and trade suppliers",
    "dealer": "Authorized dealers and dealer locators",
    "manufacturer": "Manufacturer / factory-direct",
    "wholesale": "Wholesale, trade and bulk pricing",
    "b2b": "B2B marketplaces (e.g. Alibaba)",
    "used": "Used and refurbished listings",
    "auction": "Auctions, liquidation and surplus",
    "completed_sales": "Completed sales (sold prices)",
    "property_listings": "Comparable property listings",
    "property_sales": "Completed property sales",
    "reviews": "Reviews and trade discussions",
    "issues": "Problems, complaints and recalls",
    "specs": "Specifications and manufacturer data",
    "ai_suggested": "Extra searches suggested by the AI planner",
    "lead": "Follow-up on leads from earlier rounds",
}
# evidence purposes (see evidence.SELLER_PURPOSES): which channels can produce offers
CHANNEL_PURPOSE = {"reviews": "reviews", "issues": "issues", "specs": "specs"}
ALWAYS = ("wholesale", "manufacturer")  # always investigated (except where the category rules them out)

B2B_DOMAINS = ["alibaba.com", "made-in-china.com", "globalsources.com"]
USED_DOMAINS = ["kijiji.ca", "ebay.ca", "ebay.com"]
AUCTION_DOMAINS = ["rbauction.com", "ironplanet.com", "govdeals.ca", "gcsurplus.ca", "govdeals.com"]
EQUIPMENT_DOMAINS = ["machinerytrader.com", "equipmenttrader.com", "kijiji.ca", "rbauction.com", "ironplanet.com"]
VEHICLE_DOMAINS = ["autotrader.ca", "kijiji.ca", "carpages.ca"]
PROPERTY_DOMAINS = ["realtor.ca", "spacelist.ca", "loopnet.com", "remax.ca", "royallepage.ca"]
DIRECTORY_DOMAINS = ["yellowpages.ca", "canada411.ca"]


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    supplier_terms: tuple[str, ...]      # how businesses that sell it describe themselves
    channels: tuple[str, ...]            # relevant channels
    not_relevant: dict[str, str]         # channel -> why it doesn't apply
    high_risk: bool = False
    used_domains: tuple[str, ...] = tuple(USED_DOMAINS)
    auction_domains: tuple[str, ...] = tuple(AUCTION_DOMAINS)


_NO_RESALE = "there's no meaningful secondary market for this kind of item"
CATEGORIES: dict[str, Category] = {
    "property": Category(
        "property", "Property / real estate", ("commercial real estate", "real estate brokerage"),
        ("local_suppliers", "property_listings", "property_sales", "auction", "issues"),
        {"wholesale": "not applicable to property", "manufacturer": "not applicable to property",
         "b2b": "not applicable to property", "retail": "not applicable to property",
         "distributor": "not applicable to property", "dealer": "not applicable to property",
         "used": "property is always resale - covered by comparable listings and sales",
         "completed_sales": "covered by completed property sales",
         "reviews": "not applicable to property", "specs": "not applicable to property"},
        high_risk=True),
    "vehicle": Category(
        "vehicle", "Vehicles and trucks", ("truck dealer", "car dealership"),
        ("local_suppliers", "dealer", "manufacturer", "used", "auction", "completed_sales", "wholesale", "reviews",
         "issues", "specs"),
        {"b2b": "B2B marketplaces don't sell road-legal vehicles for Canada",
         "retail": "vehicles are sold through dealers, not retailers",
         "distributor": "vehicles are sold through dealers, not distributors"},
        high_risk=True, used_domains=tuple(VEHICLE_DOMAINS)),
    "machinery": Category(
        "machinery", "Industrial machinery and equipment", ("heavy equipment dealer", "industrial equipment supplier"),
        ("local_suppliers", "dealer", "manufacturer", "distributor", "used", "auction", "completed_sales",
         "wholesale", "b2b", "reviews", "issues", "specs"),
        {"retail": "industrial machinery isn't sold through general retailers"},
        high_risk=True, used_domains=tuple(EQUIPMENT_DOMAINS)),
    "electrical": Category(
        "electrical", "Electrical supplies", ("electrical supply", "electrical wholesaler"),
        ("local_suppliers", "distributor", "dealer", "manufacturer", "wholesale", "retail", "b2b", "used", "auction",
         "reviews", "issues", "specs"),
        {"completed_sales": "completed-sale prices are rarely published for electrical stock"}),
    "ppe": Category(
        "ppe", "Safety equipment and PPE", ("safety supply", "workwear store"),
        ("local_suppliers", "distributor", "manufacturer", "wholesale", "retail", "b2b", "reviews", "issues", "specs"),
        {"used": "used PPE isn't acceptable for safety and hygiene", "auction": "used PPE isn't acceptable",
         "completed_sales": _NO_RESALE},
        high_risk=True),
    "tools": Category(
        "tools", "Tools", ("tool supply", "industrial supply", "hardware store"),
        ("local_suppliers", "retail", "distributor", "dealer", "manufacturer", "wholesale", "used", "auction",
         "completed_sales", "b2b", "reviews", "issues", "specs"), {}),
    "parts": Category(
        "parts", "Parts and components", ("industrial supply", "parts supplier"),
        ("local_suppliers", "distributor", "dealer", "manufacturer", "wholesale", "retail", "b2b", "used", "auction",
         "reviews", "issues", "specs"),
        {"completed_sales": "completed-sale prices are rarely published for parts"}),
    "consumables": Category(
        "consumables", "Consumables and supplies", ("industrial supply", "janitorial supply"),
        ("local_suppliers", "distributor", "wholesale", "retail", "manufacturer", "b2b", "reviews", "specs"),
        {"used": _NO_RESALE, "auction": _NO_RESALE, "completed_sales": _NO_RESALE}),
    "electronics": Category(
        "electronics", "IT and electronics", ("computer store", "electronics store"),
        ("local_suppliers", "retail", "distributor", "manufacturer", "wholesale", "used", "auction",
         "completed_sales", "reviews", "issues", "specs"),
        {"b2b": "brand-name electronics from B2B marketplaces carry counterfeit and warranty risk"}),
    "general": Category(
        "general", "General purchase", (),
        ("local_suppliers", "retail", "distributor", "manufacturer", "wholesale", "b2b", "used", "auction",
         "completed_sales", "reviews", "issues", "specs"), {}),
}
# Checked in order. Property and vehicles need phrases that only mean property or a vehicle ("warehouse for
# lease", "pickup truck"): their nouns are common in product names ("building wire", "home standby generator",
# "pallet truck", "lot of 50 shackles", "semi-gloss paint"), so product categories are checked before vehicles.
_CATEGORY_WORDS = [
    ("property", r"\b(real estate|acres?|acreage|vacant land|land for (?:sale|lease)|lots? for sale|"
                 r"(?:house|home|building|warehouse|condo|property|land|lot) for (?:sale|lease|rent)|"
                 r"(?:warehouse|office|retail|commercial|industrial|yard|storage) (?:space|property|building|land|lot|unit)|"
                 r"commercial real estate|property (?:listing|purchase|lease)|sq\.? ?ft (?:building|warehouse|space))\b"),
    ("electrical", r"\b(cable|wire|teck|awg|kcmil|mcm|breaker|transformer|conduit|switchgear|panelboard|vfd|"
                   r"contactor|receptacle|luminaire|light fixture|electrical)\b"),
    ("ppe", r"\b(gloves?|respirators?|masks?|hard ?hats?|helmets?|vests?|hi-?vis|boots|harness|lanyard|earplugs?|"
            r"ear ?muffs?|goggles|safety glasses|coveralls|ppe|face shield)\b"),
    ("machinery", r"\b(excavator|loader|crane|forklift|reach stacker|telehandler|skid steer|backhoe|dozer|bulldozer|"
                  r"boom lift|scissor lift|man ?lift|generator|compressor|welder|conveyor|grader|sweeper|machine|"
                  r"machinery|equipment|hoist|winch|pallet (?:truck|jack)|pallet racking|racking)\b"),
    ("tools", r"\b(drill|impact|wrench|saw|grinder|ratchet|socket set|hammer|driver|tools?|torque|hand truck|dolly|"
              r"charger)\b"),
    ("parts", r"\b(bearings?|seals?|gaskets?|filters?|belts?|hoses?|fittings?|valves?|pumps?|couplings?|sprockets?|"
              r"shackles?|slings?|bolts?|nuts?|screws?|fasteners?|tires?|tyres?|parts?)\b"),
    ("consumables", r"\b(rags?|absorbents?|tape|lubricant|grease|oil|fuel|diesel|paper|cleaners?|degreaser|"
                    r"chemicals?|salt|bags?|wipes|batter(?:y|ies)|paint|sealant|adhesive)\b"),
    ("electronics", r"\b(laptops?|computers?|monitors?|printers?|phones?|tablets?|radios?|cameras?|routers?|"
                    r"servers?)\b"),
    ("vehicle", r"\b(pick-?up(?: truck)?|dump truck|semi[- ]truck|semi[- ]tractor|tractor[- ]trailer|cargo van|"
                r"cube van|suv|f-?[1-5]50|silverado|sierra \d{4}|ram [1-5]500|(?:used|new|work|service|delivery|fleet) "
                r"(?:truck|car|van|vehicle)s?|(?:truck|car|van|vehicle)s? for sale|vehicle|automobile)\b"),
]
# things whose failure can hurt people or cost a lot: always searched more deeply
_HIGH_RISK_WORDS = re.compile(r"\b(lifting|rigging|sling|shackle|hoist|crane|fall protection|harness|respirator|"
                              r"high voltage|kv\b|pressure vessel|boiler)\b", re.I)
EXPENSIVE_CAD = 5000.0


def categorize(name: str, hint: str | None = None) -> Category:
    """Category from the request (and the AI planner's category label, if any). Unknown -> general."""
    for text in (name, hint or ""):
        low = text.lower()
        for key, pattern in _CATEGORY_WORDS:
            if re.search(pattern, low):
                return CATEGORIES[key]
    return CATEGORIES["general"]


@dataclass
class PlannedQuery:
    query: str
    purpose: str
    country: str | None
    channel: str = "retail"
    market: str = "canada"
    round: int = 1
    domains: list[str] | None = None
    status: str = "pending"
    result_count: int = 0
    error: dict[str, Any] | None = None
    provider: str | None = None
    lead: str | None = None  # what this follow-up search is following up


DEPTH_BUDGET = {  # web searches per round; local (Google Maps) searches; most rounds
    "quick": {"rounds": [8, 3], "maps": 1, "search_depth": "basic", "max_results": 8},
    "standard": {"rounds": [14, 8], "maps": 2, "search_depth": "basic", "max_results": 8},
    "deep": {"rounds": [20, 12, 8], "maps": 3, "search_depth": "advanced", "max_results": 10},
}


def alt_spellings(name: str) -> list[str]:
    """Common trade spellings of the same thing (search terms only)."""
    out = []
    swaps = [(r"\bMCM\b", "kcmil"), (r"\bkcmil\b", "MCM"), (r"\b(\d)-conductor\b", r"\1C"), (r"\b(\d)C\b", r"\1-conductor"),
             (r"\bteck\b", "TECK90"), (r"\bhard hat\b", "safety helmet"), (r"\bhi-vis\b", "high visibility")]
    for pattern, repl in swaps:
        alt = re.sub(pattern, repl, name, flags=re.I)
        if alt.lower() != name.lower():
            out.append(alt)
    return list(dict.fromkeys(out))[:2]


def _q(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:200]


def initial_plan(name: str, category: Category, depth: str, *, brand: str | None = None,
                 alt_names: list[str] | None = None, ai_queries: list[str] | None = None,
                 used_ok: bool = True, budget: int | None = None) -> list[PlannedQuery]:
    """Round 1: broad discovery across markets and channels, local first, within the depth's budget."""
    q = _q(name)
    term = category.supplier_terms[0] if category.supplier_terms else f"{q} supplier"
    city, region = HOME["city"], HOME["region"]
    rel = set(category.channels)
    if not used_ok:
        rel -= {"used", "auction", "completed_sales"}
    cands: list[tuple[int, PlannedQuery]] = []

    def add(prio: int, channel: str, market: str, query: str, country: str | None = None,
            domains: list[str] | None = None) -> None:
        if channel not in rel and channel not in ("directory", "ai_suggested"):
            return
        cands.append((prio, PlannedQuery(_q(query), CHANNEL_PURPOSE.get(channel, channel), country, channel, market,
                                         1, domains)))

    if category.key == "property":
        add(1, "property_listings", "local", f"{q} for sale {city} Ontario", "canada", PROPERTY_DOMAINS)
        add(2, "property_sales", "local", f"{q} sold {city} recent sales", "canada")
        add(3, "local_suppliers", "local", f"{term} {city}", "canada")
        add(4, "property_listings", "regional", f"{q} for sale {region}", "canada")
        add(5, "auction", "local", f"tax sale OR power of sale {city} {q}", "canada")
        add(6, "issues", "local", f"{q} {city} zoning assessment", "canada")
        add(7, "property_sales", "local", f"{city} {q} sale price per square foot", "canada")
    else:
        # local first
        add(1, "local_suppliers", "local", f"{q} {city}", "canada")
        if term:
            add(2, "local_suppliers", "local", f"{term} {city} Ontario", "canada")
        add(3, "retail", "canada", f"{q} price", "canada")
        add(4, "wholesale", "canada", f"{q} wholesale bulk price", "canada")
        if brand:
            add(5, "manufacturer", "any", f"{q} official site" if brand.lower() in q.lower() else f"{brand} {q} official site")
        else:
            add(5, "manufacturer", "any", f"{q} manufacturer factory direct")
        if brand:
            add(6, "dealer", "canada", f"{brand} authorized dealer {city} OR Ontario", "canada")
        else:
            add(6, "distributor", "canada", f"{q} distributor Canada", "canada")
        add(7, "reviews", "any", f"{q} review")
        add(8, "distributor", "regional", f"{q} supplier {region} OR Ontario", "canada")
        add(9, "directory", "local", f"{term} {city}", "canada", DIRECTORY_DOMAINS)
        add(10, "issues", "any", f"{q} problems complaints recall")
        add(11, "used", "canada", f"used {q} for sale Ontario", "canada", list(category.used_domains))
        add(12, "b2b", "international", f"{q} wholesale manufacturer", None, B2B_DOMAINS)
        add(13, "retail", "us", f"{q} price USD", "united states")
        add(14, "auction", "canada", f"{q} auction surplus liquidation", "canada", list(category.auction_domains))
        add(15, "completed_sales", "any", f"{q} sold price")
        add(16, "specs", "any", f"{q} specifications datasheet")
        add(17, "distributor", "us", f"{q} distributor USA", "united states")
        add(18, "wholesale", "canada", f"{q} trade account contractor pricing volume discount", "canada")
        add(19, "manufacturer", "international", f"{q} manufacturer export Canada")
        add(20, "dealer", "canada", f"{q} authorized distributor Canada", "canada")
    for i, alt in enumerate(alt_names or []):
        add(5.5 + i * 0.1, "retail", "canada", f"{alt} price", "canada")
    for i, extra in enumerate(ai_queries or []):
        add(9.5 + i * 0.1, "ai_suggested", "canada", extra, "canada")
    cap = budget if budget is not None else DEPTH_BUDGET.get(depth, DEPTH_BUDGET["standard"])["rounds"][0]
    chosen = [pq for _, pq in sorted(cands, key=lambda t: t[0])]
    # the channels that must always be investigated stay in, whatever the budget
    must = [pq for pq in chosen if pq.channel in ALWAYS or pq.channel == "local_suppliers"]
    rest = [pq for pq in chosen if pq not in must]
    picked = must + rest[:max(0, cap - len(must))]
    order = {id(pq): i for i, pq in enumerate(chosen)}
    return _dedupe(sorted(picked, key=lambda pq: order[id(pq)]))


def _norm(pq: PlannedQuery) -> tuple[str, tuple[str, ...]]:
    return re.sub(r"\W+", " ", pq.query.lower()).strip(), tuple(sorted(pq.domains or []))


def _dedupe(plan: list[PlannedQuery], seen: set | None = None) -> list[PlannedQuery]:
    seen = seen if seen is not None else set()
    out = []
    for pq in plan:
        key = _norm(pq)
        if key in seen:
            continue
        seen.add(key)
        out.append(pq)
    return out


@dataclass
class Lead:
    kind: str        # "supplier" | "local_business" | "brand" | "manufacturer" | "alt_name"
    value: str       # domain, business name, brand or name
    label: str
    market: str = "canada"
    priority: int = 5


_STOP = {"the", "and", "for", "with", "new", "type", "price", "buy", "sale", "cable", "wire", "supply", "supplies"}


def _item_words(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if (len(w) >= 3 or w.isdigit()) and w not in _STOP}


def _about_item(text: str, name: str, tokens: list[str]) -> bool:
    """Does a page's title/snippet name the item? Its model number, or most of the request's distinctive words."""
    low = text.lower()
    if tokens:
        return any(t.lower() in low for t in tokens)
    words = _item_words(name)
    if not words:
        return False
    hit = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", low))
    return hit >= max(1, (len(words) + 1) // 2)


def find_leads(sources: list[Any], local_businesses: list[dict[str, Any]], *, name: str, brand: str | None,
               category: Category, alt_names: list[str] | None = None,
               covered_domains: set[str] | None = None, local_names: list[str] | None = None,
               covered_names: set[str] | None = None) -> list[Lead]:
    """Leads worth a focused follow-up search, local first.

    - A local business from a map listing is followed on its own website; one with no website (or only a
      Facebook-type page), and a business named on a directory page, is searched by name with the item.
    - A supplier lead is a seller page that names the item but showed no price for it (it may carry it or
      quote it). Pages that don't name the item (news, other products) aren't leads.
    - Manufacturer sites get a where-to-buy search; a brand gets a dealer search near Thunder Bay."""
    from .suppliers import DISTRIBUTOR, MANUFACTURER, RETAILER, UNKNOWN, domain_of, is_platform_domain
    covered = covered_domains or set()
    named = {n.lower() for n in (covered_names or set())}
    tokens = ex.model_tokens(name)
    leads: list[Lead] = []
    for b in local_businesses:
        dom = domain_of(b["website"]) if b.get("website") else None
        # a Facebook page or similar isn't the business's own site: searching that domain finds everyone else
        # a map result can lie outside Thunder Bay: its own address says where (local leads go first)
        tier = ex.location_tier(b.get("address") or "", HOME["city"])[0]
        market, prio = ("local", 1) if tier in (None, "local") else (tier, 3)
        if dom and not is_platform_domain(dom):
            if dom not in covered:
                leads.append(Lead("local_business", dom, b.get("name") or dom, market, prio))
        elif b.get("name") and b["name"].lower() not in named:
            leads.append(Lead("local_name", b["name"], b["name"], market, prio + 1))
    for n in local_names or []:
        if n.lower() not in named:
            leads.append(Lead("local_name", n, n, "local", 2))
    for s in sources:
        if s.domain in covered or s.type not in (DISTRIBUTOR, RETAILER, UNKNOWN, MANUFACTURER):
            continue
        text = f"{s.title} {s.snippet}"
        local = HOME["city"].lower() in text.lower()
        if s.type == MANUFACTURER:
            leads.append(Lead("manufacturer", s.domain, s.name, "any", 3))
        elif not ex.find_prices(s.snippet or "") and _about_item(text, name, tokens):
            leads.append(Lead("supplier", s.domain, s.name, "local" if local else "canada", 2 if local else 4))
    if brand:
        leads.append(Lead("brand", brand, f"{brand} dealer network", "local", 2))
    for alt in alt_names or []:
        leads.append(Lead("alt_name", alt, f"alternative name '{alt}'", "canada", 6))
    seen, out = set(), []
    for lead in sorted(leads, key=lambda l: l.priority):
        key = (lead.kind, lead.value.lower())
        if key not in seen:
            seen.add(key)
            out.append(lead)
    return out


def follow_up_plan(leads: list[Lead], name: str, category: Category, round_no: int, budget: int,
                   seen: set) -> list[PlannedQuery]:
    """Focused searches for the best leads: the item on a supplier's own site, a brand's local dealers, a
    manufacturer's where-to-buy pages, alternative names."""
    q = _q(name)
    city = HOME["city"]
    plan: list[PlannedQuery] = []
    for lead in leads:
        if len(plan) >= budget:
            break
        if lead.kind == "local_name":
            pq = PlannedQuery(f"{lead.value} {city} {q}" if lead.market == "local" else f"{lead.value} {q}", "lead",
                              "canada", "local_suppliers" if lead.market == "local" else "distributor", lead.market,
                              round_no, lead=lead.label)
        elif lead.kind in ("local_business", "supplier"):
            pq = PlannedQuery(f"{q} price", "lead", "canada", "local_suppliers" if lead.market == "local" else "distributor",
                              lead.market, round_no, [lead.value], lead=lead.label)
        elif lead.kind == "manufacturer":
            pq = PlannedQuery(f"where to buy {q} dealer distributor", "lead", None, "dealer", "any", round_no,
                              [lead.value], lead=lead.label)
        elif lead.kind == "brand":
            pq = PlannedQuery(f"{lead.value} dealer {city} Ontario", "lead", "canada", "dealer", "local", round_no,
                              lead=lead.label)
        else:
            pq = PlannedQuery(f"{lead.value} price Canada", "lead", "canada", "retail", "canada", round_no,
                              lead=lead.label)
        plan.extend(_dedupe([pq], seen))
    return plan


def snippet_value_estimate(sources: list[Any]) -> float | None:
    """Rough item value in CAD from Canadian sellers' search snippets, to decide how deep to search (never shown
    as a price). Used, auction, review and other non-seller pages don't count; neither do foreign currencies."""
    from .suppliers import DISTRIBUTOR, MANUFACTURER, MARKETPLACE, RETAILER, UNKNOWN
    vals = []
    for s in sources:
        if s.type not in (DISTRIBUTOR, MANUFACTURER, RETAILER, MARKETPLACE, UNKNOWN) or s.country != "CA":
            continue
        if set(s.purposes) <= {"reviews", "issues", "specs", "used", "auction", "completed_sales"}:
            continue  # found only by review, spec, used or auction searches
        for p in ex.find_prices(s.snippet or "")[:1]:
            if p.currency in (None, "CAD") and not p.per:
                vals.append(p.amount)
    return statistics.median(vals) if len(vals) >= 3 else None


DEEPER = {"quick": "standard", "standard": "deep"}


def depth_decision(depth: str, category: Category, name: str, value_estimate: float | None,
                   quantity: int | None, stated_budget: float | None) -> tuple[list[int], str | None]:
    """Round budgets for this research, and why it was deepened (if it was): an expensive or higher-risk
    purchase is searched one level deeper than chosen (quick -> standard -> deep)."""
    rounds = list(DEPTH_BUDGET.get(depth, DEPTH_BUDGET["standard"])["rounds"])
    if depth not in DEEPER:
        return rounds, None
    reasons = []
    total = (value_estimate or 0) * (quantity or 1)
    if stated_budget and stated_budget >= EXPENSIVE_CAD:
        reasons.append(f"your budget (about CAD {stated_budget:,.0f})")
    elif total >= EXPENSIVE_CAD:
        reasons.append(f"its likely cost (about CAD {total:,.0f}, estimated from search snippets)")
    if category.high_risk or _HIGH_RISK_WORDS.search(name):
        reasons.append(f"it's a higher-risk category ({category.label.lower()})")
    if not reasons:
        return rounds, None
    deeper = DEEPER[depth]
    return (list(DEPTH_BUDGET[deeper]["rounds"]),
            f"Searched at {deeper} depth instead of {depth} because of " + " and ".join(reasons) + ".")


def local_queries(name: str, category: Category, n: int) -> list[str]:
    """Map searches for businesses near Thunder Bay: how sellers of this category describe themselves, then the
    item itself. The town is in the query as well as the map position: SerpApi says results aren't guaranteed to
    stay near the position given, and recommends naming the place."""
    terms = list(category.supplier_terms) + [_q(name)]
    place = f"{HOME['city']} {HOME['province']}"
    return [f"{t} {place}" for t in dict.fromkeys(terms)][:max(0, n)]


def channel_table(category: Category, used_ok: bool = True) -> list[dict[str, str]]:
    """Every channel with whether it applies to this item (and why not)."""
    out = []
    for key, label in CHANNELS.items():
        if key in ("ai_suggested", "lead"):
            continue
        if key in category.channels and (used_ok or key not in ("used", "auction", "completed_sales")):
            out.append({"channel": key, "label": label, "relevant": True, "reason": ""})
        elif key in category.not_relevant:
            out.append({"channel": key, "label": label, "relevant": False, "reason": category.not_relevant[key]})
        elif not used_ok and key in ("used", "auction", "completed_sales"):
            out.append({"channel": key, "label": label, "relevant": False, "reason": "you asked for new only"})
    return out
