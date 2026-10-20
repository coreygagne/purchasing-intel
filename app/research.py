"""Research workflow: request -> real search -> evidence -> comparison -> saved.

`run_research` does the network work; `analyze` is pure and can be re-run on
a stored comparison (e.g. when import assumptions change) without searching
again.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

import httpx

from . import analysis as an
from . import extract as ex
from .config import Settings
from .db import Database, iso
from .evidence import Offer, OfferBuilder, Source, apply_match, build_sources, is_seller_source, add_source
from .fetch import PageFetcher
from .fx import FxRate, FxService
from .import_costs import clean_assumptions, general_notes, LINKS
from .providers import ProviderError, ProviderSet, ShoppingListing, build_providers
from .providers.base import SearchHit
from .suppliers import B2B_MARKETPLACE, DISTRIBUTOR, MANUFACTURER, RETAILER

log = logging.getLogger(__name__)

Progress = Callable[[str, int], None]

GENERIC_WORDS = {
    "heavy", "duty", "the", "best", "cheap", "industrial", "commercial", "replacement", "new", "used", "pack",
    "box", "case", "set", "kit", "for", "with", "and", "high", "low", "large", "small", "medium", "outdoor",
    "indoor", "portable", "electric", "cordless", "steel", "stainless", "plastic", "rubber", "safety", "black",
    "white", "red", "blue", "yellow", "green", "grade", "pro", "professional", "premium", "standard", "buy",
    # common product words that are not brands
    "impact", "wrench", "drill", "driver", "saw", "grinder", "battery", "charger", "gloves", "glove", "cord",
    "extension", "cable", "hose", "pump", "motor", "filter", "bearing", "belt", "valve", "fitting", "light", "lamp",
    "heater", "fan", "ladder", "respirator", "mask", "boots", "jacket", "helmet", "vest", "oil", "grease",
    "lubricant", "paint", "tape", "bolt", "nut", "screw", "washer", "chain", "rope", "sling", "shackle", "hook",
    "hoist", "tarp", "bucket", "cleaner", "degreaser", "sealant", "adhesive", "welding", "welder", "generator",
    "compressor", "sensor", "switch", "breaker", "relay", "fuse", "wire", "tire", "wheel", "socket", "ratchet",
    "pliers", "hammer", "knife", "blade", "bit", "bits", "replacement", "part", "parts", "kit", "nitrile",
}

DEPTHS = {
    "quick": {"purposes": ["price", "reviews", "wholesale"], "search_depth": "basic", "max_results": 8},
    "standard": {"purposes": ["price", "suppliers", "wholesale", "reviews", "issues", "specs"],
                 "search_depth": "basic", "max_results": 8},
    "deep": {"purposes": ["price", "suppliers", "wholesale", "reviews", "issues", "specs", "alternatives",
                          "cross_border"], "search_depth": "advanced", "max_results": 10},
}

QUERY_TEMPLATES = {
    "price": ("{q} price", "canada"),
    "suppliers": ("{q} supplier distributor Canada", "canada"),
    "wholesale": ("{q} wholesale bulk price MOQ", None),
    "reviews": ("{q} review", None),
    "issues": ("{q} problems complaints recall", None),
    "specs": ("{q} specifications datasheet", None),
    "alternatives": ("{q} alternative equivalent comparable", None),
    "cross_border": ("{q} price USD buy", None),
}

FATAL_KINDS = {"auth", "quota", "not_configured"}
AI_PLAN_TIMEOUT_S = 60
AI_EXTRACT_TIMEOUT_S = 150


def _ai_error(exc: Exception) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "the AI step took too long and was skipped; results below are from search and page data only"
    return str(exc) or type(exc).__name__


class ResearchError(Exception):
    def __init__(self, message: str, *, kind: str = "failed", details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.kind = kind
        self.details = details or []


@dataclass
class ResearchRequest:
    query: str
    depth: str = "standard"
    quantity: int | None = None
    comparison_id: int | None = None


@dataclass
class PlannedQuery:
    query: str
    purpose: str
    country: str | None
    status: str = "pending"
    result_count: int = 0
    error: dict[str, Any] | None = None
    provider: str | None = None


@dataclass
class Identity:
    input: str
    input_type: str
    name: str
    model_tokens: list[str]
    brand_words: list[str]
    source: str
    reference_url: str | None = None
    category: str | None = None
    key_specs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _brand_words(text: str, extra: list[str] | None = None) -> list[str]:
    """Brand names used to recognise manufacturer websites.

    The first word only counts as a brand when the request also has a model number
    ("Milwaukee 2767-20"); in a plain description ("nitrile gloves") it is just a word.
    Brands from page data or the AI planner (checked against the request) are always used.
    """
    words: list[str] = []
    first = re.findall(r"[A-Za-z][A-Za-z&'\-]{2,}", text)
    if first and first[0].lower() not in GENERIC_WORDS and ex.model_tokens(text):
        words.append(first[0])
    for w in extra or []:
        if w and w.lower() not in (x.lower() for x in words):
            words.append(w)
    return words


def _clean_title(name: str, tokens_hint: str = "") -> str:
    """Drop a trailing " | Store name" / " - Store name" segment without cutting model numbers."""
    parts = [p.strip() for p in re.split(r"\s+[|–—]\s+|\s+-\s+", name) if p.strip()]
    if len(parts) <= 1:
        return name.strip()
    if not ex.model_tokens(parts[-1]) and len(parts[-1]) <= 40:
        parts = parts[:-1]  # trailing store / site name
    return " ".join(parts).strip()


def plan_queries(name: str, depth: str, extra: list[str] | None = None) -> list[PlannedQuery]:
    cfg = DEPTHS.get(depth, DEPTHS["standard"])
    q = re.sub(r"\s+", " ", name).strip()[:200]
    plan = [PlannedQuery(QUERY_TEMPLATES[p][0].format(q=q), p, QUERY_TEMPLATES[p][1]) for p in cfg["purposes"]]
    for e in (extra or [])[:3]:
        plan.append(PlannedQuery(e[:200], "ai_suggested", "canada"))
    return plan


class ResearchEngine:
    def __init__(self, settings: Settings, db: Database, llm: Any | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, anthropic_client: Any | None = None):
        self.settings = settings
        self.db = db
        self.llm = llm
        self.transport = transport  # tests inject a mock transport here
        self.anthropic_client = anthropic_client  # and a stub Anthropic client for Anthropic web search

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, timeout=self.settings.search_timeout_s,
                                 follow_redirects=False)

    async def run(self, req: ResearchRequest, progress: Progress | None = None) -> dict[str, Any]:
        progress = progress or (lambda step, pct: None)
        started = time.monotonic()
        query = req.query.strip()
        if not query:
            raise ResearchError("Enter a product name, model number, description or URL.", kind="bad_input")
        depth = req.depth if req.depth in DEPTHS else "standard"
        cfg = DEPTHS[depth]
        async with self._client() as client:
            providers = build_providers(self.settings, client, self.anthropic_client)
            if providers.web is None:
                raise ResearchError("No search provider is configured.", kind="not_configured")
            fetcher = PageFetcher(client, user_agent=self.settings.fetch_user_agent,
                                  timeout_s=self.settings.fetch_timeout_s, max_bytes=self.settings.fetch_max_bytes,
                                  respect_robots=self.settings.respect_robots_txt,
                                  allow_unresolved=self.settings.fetch_trust_proxy_dns)
            llm_usage: dict[str, Any] = {}

            # 1. Understand the request ------------------------------------------------
            progress("Understanding the request", 5)
            identity, ref_fetch = await self._identify(query, fetcher, providers)
            if self.llm is not None:
                try:
                    plan_info = await asyncio.wait_for(self.llm.plan(identity.name, identity.input_type),
                                                       timeout=AI_PLAN_TIMEOUT_S)
                    identity.category = plan_info.get("category")
                    identity.key_specs = plan_info.get("key_specs", [])[:8]
                    brand = plan_info.get("brand")
                    if brand and brand.lower() in identity.name.lower():
                        identity.brand_words = _brand_words(identity.name, [brand])
                    extra_queries = plan_info.get("search_queries", [])
                    llm_usage["plan"] = plan_info.get("_usage")
                except Exception as exc:  # noqa: BLE001 - AI is optional; report and continue
                    identity.notes.append(f"AI request planning unavailable: {_ai_error(exc)}")
                    extra_queries = []
            else:
                extra_queries = []

            # 2. Search -----------------------------------------------------------------
            plan = plan_queries(identity.name, depth, extra_queries)
            progress(f"Searching the web ({len(plan)} queries via {providers.web.name})", 15)
            hits = await self._search_all(providers, plan, cfg)
            listings: list[ShoppingListing] = []
            shopping_status: dict[str, Any] | None = None
            if providers.shopping is not None:
                progress("Checking Google Shopping (Canada)", 35)
                try:
                    listings = await providers.shopping.shopping(identity.name)
                    shopping_status = {"query": identity.name, "status": "ok", "result_count": len(listings)}
                except ProviderError as exc:
                    shopping_status = {"query": identity.name, "status": "failed", "error": exc.to_dict()}

            # 3. Evidence -----------------------------------------------------------------
            sources = build_sources(hits, identity.brand_words)
            builder = OfferBuilder(identity.brand_words)
            if ref_fetch is not None:
                ref_src = add_source(sources, url=identity.reference_url or query, title=identity.name,
                                     snippet="Page you provided", purpose="input_url", provider="page fetch",
                                     brand_words=identity.brand_words)
                ref_src.fetch = {"ok": ref_fetch.ok, "status": ref_fetch.status, "error": ref_fetch.error,
                                 "fetched_at": ref_fetch.fetched_at, "structured": False}
                if ref_fetch.ok and ref_fetch.html:
                    ref_src.page_text = ex.page_text(ref_fetch.html, 15000)
                    found = builder.from_structured(ref_src, ex.structured_products(ref_fetch.html),
                                                    identity.model_tokens, ref_fetch.fetched_at, is_reference=True)
                    ref_src.fetch["structured"] = found
            builder.from_shopping(listings, sources)

            progress("Reading supplier pages for price data", 50)
            fetch_attempts, fetch_failures = await self._fetch_and_extract(sources, builder, identity, fetcher)

            if self.llm is not None:
                progress("AI is reading page text (every extracted fact is checked against the source)", 70)
                try:
                    llm_out = await asyncio.wait_for(self.llm.extract(identity, sources, builder),
                                                     timeout=AI_EXTRACT_TIMEOUT_S)
                    llm_usage["extract"] = llm_out.get("_usage")
                    llm_summary = llm_out
                except Exception as exc:  # noqa: BLE001 - search results are kept without AI
                    identity.notes.append(f"AI evidence reading unavailable: {_ai_error(exc)}")
                    llm_summary = None
            else:
                llm_summary = None

            # 4. FX + analysis --------------------------------------------------------------
            progress("Converting currencies (Bank of Canada)", 82)
            fx_service = FxService(self.db, client)
            currencies = {o.currency for o in builder.offers if o.currency and o.price is not None}
            fx = await fx_service.rates(currencies)

            progress("Comparing offers", 90)
            meta = {
                "query": query, "depth": depth, "quantity": req.quantity, "researched_at": iso(),
                "duration_s": round(time.monotonic() - started, 1),
                "providers": {"web": providers.web.name,
                              "shopping": providers.shopping.name if providers.shopping else None,
                              "llm": self.settings.anthropic_model if self.llm is not None else None,
                              "fx": "Bank of Canada Valet"},
                "queries": [asdict(p) for p in plan] + ([{"query": shopping_status["query"], "purpose": "shopping",
                                                           "country": "ca", "status": shopping_status["status"],
                                                           "result_count": shopping_status.get("result_count", 0),
                                                           "error": shopping_status.get("error"),
                                                           "provider": "SerpApi"}] if shopping_status else []),
                "credits": {**providers.credits(), **({"llm_usage": llm_usage} if llm_usage else {})},
                "fetch": {"attempted": fetch_attempts, "failed": fetch_failures,
                          "robots_respected": self.settings.respect_robots_txt},
                "fx_errors": fx_service.errors,
            }
            result = analyze(identity=asdict(identity), sources=sources, offers=builder.offers, fx=fx,
                             assumptions={}, meta=meta, home_province=self.settings.home_province,
                             llm_summary=llm_summary)
            progress("Done", 100)
            return result

    # ---------------------------------------------------------------- helpers
    async def _identify(self, query: str, fetcher: PageFetcher, providers: ProviderSet):
        input_type = ex.classify_input(query)
        if input_type != "url":
            tokens = ex.model_tokens(query)
            return Identity(query, input_type, query, tokens, _brand_words(query), "your request"), None
        url = query.strip()
        fr = await fetcher.fetch(url) if self.settings.fetch_pages else None
        notes: list[str] = []
        name, source, brand, mpn = None, "", None, None
        if fr is not None and fr.ok and fr.html:
            products = ex.structured_products(fr.html)
            named = [p for p in products if p.name]
            if named:
                p = named[0]
                name, brand, mpn, source = p.name, p.brand, p.mpn, "product page data (schema.org)"
            else:
                name, source = ex.page_title(fr.html), "page title"
        else:
            notes.append(f"Could not read the page you provided ({fr.error if fr else 'page fetching disabled'}).")
            if providers.tavily is not None:
                try:
                    text = await providers.tavily.extract(url)
                    if text:
                        # Use the page's main heading only; other lines are usually navigation
                        heading = next((ln.lstrip("#").strip() for ln in text.splitlines()
                                        if re.match(r"^#{1,2}\s+\S", ln.strip())), None)
                        if heading and len(heading) > 5:
                            name, source = heading[:150], "page heading via Tavily Extract"
                except ProviderError as exc:
                    notes.append(f"Tavily Extract also failed: {exc.user_message}")
        if not name:
            name, source = ex.words_from_url(url), "words in the URL (page could not be read)"
            notes.append("Product identified only from the URL text - results may be imprecise.")
        if brand and brand.lower() not in name.lower():
            name = f"{brand} {name}"
        name = _clean_title(name)
        tokens = ex.model_tokens(name)
        if mpn and mpn.lower() not in (t.lower() for t in tokens) and ex.model_tokens(mpn):
            tokens.append(mpn)
        ident = Identity(query, "url", name, tokens, _brand_words(name, [brand] if brand else []), source,
                         reference_url=url, notes=notes)
        return ident, fr

    async def _search_all(self, providers: ProviderSet, plan: list[PlannedQuery], cfg: dict[str, Any]) -> list[SearchHit]:
        sem = asyncio.Semaphore(4)
        fatal: list[ProviderError] = []
        include_raw = self.llm is not None

        async def one(pq: PlannedQuery) -> list[SearchHit]:
            if fatal:
                pq.status, pq.error = "skipped", {"message": "skipped after a fatal provider error"}
                return []
            async with sem:
                pq.provider = providers.web.name
                try:
                    res = await providers.web.search(pq.query, purpose=pq.purpose, max_results=cfg["max_results"],
                                                     depth=cfg["search_depth"], country=pq.country,
                                                     include_raw=include_raw)
                    pq.status, pq.result_count = "ok", len(res)
                    return res
                except ProviderError as exc:
                    pq.status, pq.error = "failed", exc.to_dict()
                    if exc.kind in FATAL_KINDS:
                        fatal.append(exc)
                    return []

        results = await asyncio.gather(*(one(pq) for pq in plan))
        hits = [h for r in results for h in r]
        if not any(pq.status == "ok" for pq in plan):
            errs = [pq.error for pq in plan if pq.error]
            first = fatal[0] if fatal else None
            msg = first.user_message if first else (errs[0]["message"] if errs else "all searches failed")
            kinds = {e.get("kind") for e in errs if e}
            kind = first.kind if first else (kinds.pop() if len(kinds) == 1 else "search_failed")
            raise ResearchError(f"Search failed: {msg}", kind=kind, details=errs)
        return hits

    async def _fetch_and_extract(self, sources: list[Source], builder: OfferBuilder, identity: Identity,
                                 fetcher: PageFetcher) -> tuple[int, int]:
        sellers = [s for s in sources if is_seller_source(s) and "input_url" not in s.purposes
                   and "shopping" not in s.purposes]
        def priority(s: Source) -> tuple[int, int, int]:
            exact = ex.match_offer(identity.model_tokens, f"{s.title} {s.snippet}").level == "exact"
            preferred = s.type in (DISTRIBUTOR, RETAILER, MANUFACTURER, B2B_MARKETPLACE)
            return (0 if exact else 1, 0 if preferred else 1, int(s.id[1:]))
        ordered = sorted(sellers, key=priority)
        to_fetch = ordered[: self.settings.fetch_max_pages] if self.settings.fetch_pages else []
        sem = asyncio.Semaphore(5)

        async def go(s: Source):
            async with sem:
                return s, await fetcher.fetch(s.url)

        fetched = await asyncio.gather(*(go(s) for s in to_fetch))
        failures = 0
        done_ids = set()
        for s, fr in fetched:
            s.fetch = {"ok": fr.ok, "status": fr.status, "error": fr.error, "fetched_at": fr.fetched_at,
                       "structured": False}
            if fr.ok and fr.html:
                s.page_text = ex.page_text(fr.html, 15000)
                found = builder.from_structured(s, ex.structured_products(fr.html), identity.model_tokens,
                                                fr.fetched_at)
                s.fetch["structured"] = found
                if found:
                    done_ids.add(s.id)
            else:
                failures += 1
        for s in sellers:
            builder.from_snippet(s)
        dedupe_snippet_offers(builder.offers, done_ids)
        return len(to_fetch), failures


def dedupe_snippet_offers(offers: list[Offer], structured_source_ids: set[str]) -> None:
    """Drop snippet offers that merely repeat a page-data price for the same source.

    Snippet offers that *disagree* with the page data are kept so the
    disagreement is shown as a conflict; snippet "quote required" or unclear
    entries are dropped when the page itself gave a price.
    """
    structured = {(o.source_id, round(o.price, 2)) for o in offers
                  if o.price_basis == "structured_data" and o.price is not None}
    unclear = {o.source_id for o in offers if o.price_basis == "structured_data" and o.price_type == "unclear"}
    keep = []
    for o in offers:
        if o.price_basis in ("snippet", "none") and o.source_id in structured_source_ids:
            if o.price is None or (o.source_id, round(o.price, 2)) in structured or o.source_id in unclear:
                continue  # repeats page data, or the page shows several prices so a snippet price is ambiguous
        keep.append(o)
    offers[:] = keep
    for i, o in enumerate(offers, start=1):
        o.id = f"O{i}"


# ---------------------------------------------------------------- analysis


def analyze(*, identity: dict[str, Any], sources: list[Source], offers: list[Offer], fx: dict[str, FxRate],
            assumptions: dict[str, Any], meta: dict[str, Any], home_province: str,
            llm_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pure analysis over collected evidence. Safe to re-run on a stored result."""
    tokens = identity.get("model_tokens") or []
    clean = clean_assumptions(assumptions)
    quantity = meta.get("quantity")
    by_id = {s.id: s for s in sources}
    for o in offers:
        o.flags = []
    apply_match(offers, tokens, by_id)
    an.apply_costs(offers, fx, clean, quantity)
    conflicts = an.detect_conflicts(offers)
    an.assess_comparability(offers, tokens, quantity)
    an.set_compare_values(offers)
    conflicts += an.outlier_flags(offers)
    rec = an.recommend(offers, tokens)
    quality = an.quality_evidence(sources, offers, tokens)
    if llm_summary and llm_summary.get("quality"):
        quality["summary"] = llm_summary["quality"]
    chs = an.channels(offers, sources)
    fx_meta = meta.get("fx_errors", {})
    fetch_meta = meta.get("fetch", {})
    gaps = an.gaps(offers, sources, tokens, rec, fx_meta, fetch_meta.get("failed", 0), fetch_meta.get("attempted", 0))
    gaps = identity.get("notes", []) + gaps
    alternatives = [{"offer_id": o.id, "title": o.product_title, "supplier": o.supplier, "url": o.url,
                     "match_level": o.match_level, "notes": o.match_notes}
                    for o in offers if o.match_level in ("variant", "different", "compatible")][:15]
    if llm_summary and llm_summary.get("alternatives"):
        alternatives_ai = llm_summary["alternatives"]
    else:
        alternatives_ai = []

    offers_sorted = sorted(offers, key=lambda o: (not o.comparable, o.price_cad is None,
                                                  an._cmp_value(o) if an._cmp_value(o) is not None else 1e18))
    source_counts: dict[str, int] = {}
    for s in sources:
        source_counts[s.type] = source_counts.get(s.type, 0) + 1
    product_key = ex.product_key_for(identity.get("name", ""), tokens)
    return {
        "schema_version": 1,
        **meta,
        "identity": identity,
        "product_key": product_key,
        "assumptions": clean,
        "sources": [s.public() for s in sources],
        "source_counts": source_counts,
        "offers": [asdict(o) for o in offers_sorted],
        "recommendations": rec,
        "quality": quality,
        "channels": chs,
        "opportunities": an.channel_opportunities(chs, quantity),
        "alternatives": alternatives,
        "spec_differences": an.spec_differences(offers),
        "alternatives_ai": alternatives_ai,
        "fx": {cur: asdict(r) for cur, r in fx.items() if cur != "CAD"},
        "import_notes": general_notes(home_province),
        "import_links": LINKS,
        "conflicts": conflicts,
        "gaps": gaps,
        "limits": an.LIMITS,
        "counts": {"sources": len(sources), "offers": len(offers),
                   "priced": sum(1 for o in offers if o.price is not None),
                   "comparable": sum(1 for o in offers if o.comparable)},
    }


def reanalyze(result: dict[str, Any], assumptions: dict[str, Any], home_province: str,
              quantity: int | None = None) -> dict[str, Any]:
    """Recompute costs/recommendations for a stored result (no new searching)."""
    sources = [Source(**{k: v for k, v in s.items() if k in Source.__dataclass_fields__}) for s in result["sources"]]
    offers = []
    for o in result["offers"]:
        offers.append(Offer(**{k: v for k, v in o.items() if k in Offer.__dataclass_fields__}))
    fx = {cur: FxRate(**r) for cur, r in (result.get("fx") or {}).items()}
    meta_keys = ["query", "depth", "quantity", "researched_at", "duration_s", "providers", "queries", "credits",
                 "fetch", "fx_errors"]
    meta = {k: result.get(k) for k in meta_keys}
    if quantity is not None:
        meta["quantity"] = quantity or None
    identity = dict(result["identity"])
    llm_summary = {"quality": result.get("quality", {}).get("summary"),
                   "alternatives": result.get("alternatives_ai")}
    # drop notes already merged into gaps last time
    for o in offers:
        o.notes = [n for n in o.notes if not n.startswith("Superseded")]
    return analyze(identity=identity, sources=sources, offers=offers, fx=fx, assumptions=assumptions, meta=meta,
                   home_province=home_province, llm_summary=llm_summary)


def observation_rows(result: dict[str, Any], comparison_id: int, search_id: int | None) -> list[dict[str, Any]]:
    rows = []
    for o in result["offers"]:
        if o.get("price") is None or any(n.startswith("Superseded") for n in o.get("notes", [])):
            continue
        rows.append({
            "comparison_id": comparison_id, "search_id": search_id, "product_key": result["product_key"],
            "product_title": o["product_title"], "supplier": o["supplier"], "supplier_domain": o["supplier_domain"],
            "supplier_country": o["country"], "price": o["price"], "price_high": o.get("price_high"),
            "currency": o["currency"], "currency_basis": o["currency_basis"], "price_cad": o.get("price_cad"),
            "fx_rate": o.get("fx_rate"), "fx_date": o.get("fx_date"), "pack_qty": o.get("pack_qty"),
            "unit_price": o.get("unit_price"), "price_basis": o["price_basis"], "price_type": o["price_type"],
            "condition": o.get("condition"), "match_level": o.get("match_level"), "url": o["url"],
            "observed_at": o["observed_at"],
            "specs_json": json.dumps(o["specs"]) if o.get("specs") else None,
            "moq": o.get("moq"), "shipping": o.get("shipping_text"), "warranty": o.get("warranty"),
            "availability": o.get("availability"), "source_provider": o.get("provider"),
        })
    return rows
