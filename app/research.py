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
from . import discovery as disc
from . import extract as ex
from . import market as mk
from . import guides
from . import vendors as vd
from .coverage import coverage_report
from .picks import recommend_plainly
from .rfq import rfq_drafts
from .config import Settings
from .costs import PRICES_CHECKED, estimate_usd
from .db import Database, iso
from .evidence import Offer, OfferBuilder, Source, apply_match, build_sources, is_seller_source, add_source
from .fetch import FetchResult, PageFetcher
from .fx import FxRate, FxService
from .import_costs import COMPLIANCE, LINKS, clean_assumptions, general_notes, import_checklist
from .discovery import PlannedQuery
from .providers import LocalBusiness, ProviderError, ProviderSet, ShoppingListing, build_providers
from .providers.anthropic_fetch import VIA, AnthropicFetcher, AnthropicPageReader
from .providers.base import SearchHit
from .suppliers import B2B_MARKETPLACE, DISTRIBUTOR, MANUFACTURER, RETAILER, UNKNOWN, domain_of, is_platform_domain

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

DEPTHS = tuple(disc.DEPTH_BUDGET)
# product pages read per research, as a multiple of FETCH_MAX_PAGES (deeper research finds more sellers)
FETCH_SCALE = {"quick": 1.0, "standard": 1.5, "deep": 2.0}
CONTACT_PAGES = {"quick": 2, "standard": 5, "deep": 8}  # local/regional suppliers' own pages read for contacts

FATAL_KINDS = {"auth", "quota", "not_configured"}
AI_PLAN_TIMEOUT_S = 60
AI_EXTRACT_TIMEOUT_S = 150
# Bump when analysis rules change; saved comparisons from older versions are re-analysed (free, no searching)
# when opened. 2: per-length prices, requested-spec checks, implausibly low prices set aside.
# 3: with a length to buy, prices must say what length they cover; reel sizes read from titles.
# 4: suppliers and contacts, market value groups, picks by channel, coverage report, quote drafts.
# 5: sizes and cable types aren't part numbers; listings stating every spec are equivalents of a part number.
# 6: "3 C" read as 3-conductor; contractors on map listings aren't quote targets; listing suppliers asked first.
ANALYSIS_VERSION = 10
FALLBACK_STAGE_TIMEOUT_S = 75  # all pages read via Anthropic web fetch, together
PAGE_TEXT_CHARS = 15000


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
    used_ok: bool = True  # include used, refurbished, auction and surplus channels
    # answers to the clarifying questions ({"intended_use": ..., "budget_cad": ...}) and what was assumed
    answers: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    spec_text: str = ""             # specs from the answers ("1000 V copper"), checked in listings
    length_text: str | None = None  # a length to buy from the answers ("300 ft of")
    intended_use: str | None = None
    area: str = "both"  # where to look: "local" (Thunder Bay only), "outside" (not Thunder Bay) or "both"
    # limits from the search filters: price_min/price_max (CAD), year_min/year_max, km_max, hours_max
    filters: dict[str, float] = field(default_factory=dict)


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
    # plain-language requests: sizes/materials to check in listings, and a length to buy ("300 ft of ...")
    specs: list[dict[str, Any]] = field(default_factory=list)
    order_length: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.specs and not self.order_length:
            self.specs, self.order_length = ex.request_specs(self.name)


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

    async def run(self, req: ResearchRequest, progress: Progress | None = None,
                  meter: dict[str, Any] | None = None) -> dict[str, Any]:
        """`meter`, if given, receives meter["credits"]: a callable returning usage so far (also after a failure)."""
        progress = progress or (lambda step, pct: None)
        started = time.monotonic()
        query = req.query.strip()
        if not query:
            raise ResearchError("Enter a product name, model number, description or URL.", kind="bad_input")
        depth = req.depth if req.depth in DEPTHS else "standard"
        cfg = disc.DEPTH_BUDGET[depth]
        async with self._client() as client:
            providers = build_providers(self.settings, client, self.anthropic_client)
            if providers.web is None:
                raise ResearchError("No search provider is configured.", kind="not_configured")
            fetcher = PageFetcher(client, user_agent=self.settings.fetch_user_agent,
                                  timeout_s=self.settings.fetch_timeout_s, max_bytes=self.settings.fetch_max_bytes,
                                  respect_robots=self.settings.respect_robots_txt,
                                  allow_unresolved=self.settings.fetch_trust_proxy_dns)
            # Used only for what this server can't connect to itself (never for a site's own refusal)
            ai_fetcher = (AnthropicFetcher(self.settings.anthropic_api_key or "",
                                           model=self.settings.anthropic_fetch_model or self.settings.anthropic_model,
                                           base_url=self.settings.anthropic_base_url, client=self.anthropic_client)
                          if self.settings.fetch_fallback_enabled else None)
            # page text is only used by the AI reading step
            reader = (AnthropicPageReader(ai_fetcher, user_agent=self.settings.fetch_user_agent,
                                          max_pages=self.settings.fetch_via_anthropic_max,
                                          respect_robots=self.settings.respect_robots_txt)
                      if ai_fetcher is not None and self.llm is not None and self.settings.fetch_pages else None)
            llm_usage: dict[str, Any] = {}

            def current_credits() -> dict[str, Any]:
                credits = providers.credits()
                usage = dict(llm_usage)
                if ai_fetcher is not None and (ai_fetcher.requests or ai_fetcher.tokens["input_tokens"]):
                    credits["anthropic_web_fetches"] = ai_fetcher.requests
                    usage["web_fetch"] = {**ai_fetcher.tokens, "model": ai_fetcher.model}
                return {**credits, **({"llm_usage": usage} if usage else {})}

            if meter is not None:
                meter["credits"] = current_credits

            # 1. Understand the request ------------------------------------------------
            progress("Understanding the request", 5)
            identity, ref_fetch = await self._identify(query, fetcher, providers, reader)
            if (req.spec_text or req.length_text) and identity.input_type != "url":
                # answers to the clarifying questions are checked in listings like specs in the request itself
                specs, length = ex.request_specs(f"{identity.name} {req.spec_text} {req.length_text or ''}")
                identity.specs, identity.order_length = specs, identity.order_length or length
            extra_queries: list[str] = []
            ai_alt_names: list[str] = []
            if self.llm is not None:
                try:
                    request = identity.name + (f" (intended use: {req.intended_use})" if req.intended_use else "")
                    plan_info = await asyncio.wait_for(self.llm.plan(request, identity.input_type),
                                                       timeout=AI_PLAN_TIMEOUT_S)
                    identity.category = plan_info.get("category")
                    identity.key_specs = plan_info.get("key_specs", [])[:8]
                    brand = plan_info.get("brand")
                    if brand and brand.lower() in identity.name.lower():
                        identity.brand_words = _brand_words(identity.name, [brand])
                    extra_queries = plan_info.get("search_queries", [])
                    ai_alt_names = plan_info.get("alternative_names", [])
                    llm_usage["plan"] = plan_info.get("_usage")
                except Exception as exc:  # noqa: BLE001 - AI is optional; report and continue
                    identity.notes.append(f"AI request planning unavailable: {_ai_error(exc)}")

            # 2. Plan: category, channels, markets (Thunder Bay first) -------------------
            category = disc.categorize(identity.name, identity.category)
            # search for the item, not the order: "300 ft of 300 MCM teck cable" -> "300 MCM teck cable"
            search_name = _without_order_length(identity.name)
            brand = identity.brand_words[0] if identity.brand_words else None
            alt_names = list(dict.fromkeys(disc.alt_spellings(search_name) + ai_alt_names))[:3]
            stated_budget = _number(req.answers.get("budget_cad"))
            quantity = req.quantity
            rounds, deepened = disc.depth_decision(depth, category, identity.name, None, quantity, stated_budget)
            run_depth = disc.DEEPER[depth] if deepened else depth  # searched one level deeper than chosen
            cfg = disc.DEPTH_BUDGET[run_depth]
            plan = disc.initial_plan(search_name, category, depth, brand=brand, alt_names=alt_names,
                                     ai_queries=extra_queries, used_ok=req.used_ok, budget=rounds[0])
            plan = disc.scope_plan(plan, req.area)
            seen = {disc._norm(pq) for pq in plan}

            # 3. Round 1 searches, Google Shopping and local map listings, together ----------
            progress(f"Searching Thunder Bay first, then wider ({len(plan)} searches via {providers.web.name})", 12)
            local_qs = disc.local_queries(search_name, category, cfg["maps"]) if req.area != "outside" else []
            hits, (listings, shopping_status), (local_businesses, local_status) = await _gather_or_raise(
                self._search_all(providers, plan, cfg),
                # Google Shopping lists national and online sellers: not part of a Thunder Bay-only search
                # and vehicles and property aren't sold there: it returns toys and accessories for them
                self._shopping(providers, search_name)
                if req.area != "local" and category.key not in ("vehicle", "property") else _nothing(),
                self._local(providers, local_qs))
            all_hits = list(hits)
            all_plan = list(plan)
            sources = build_sources(all_hits, identity.brand_words)
            round_log = [_round_entry(1, plan, hits, set(), set(), sources)]
            if deepened is None:
                # a rough value from round-1 snippets decides whether this is an expensive purchase
                value = disc.snippet_value_estimate(sources)
                more, why = disc.depth_decision(depth, category, identity.name, value, quantity, stated_budget)
                if why:
                    run_depth = disc.DEEPER[depth]
                    cfg = disc.DEPTH_BUDGET[run_depth]
                    rounds = more
                    deepened = (f"{why} Round 1 ran at {depth} depth before the prices were seen; the follow-up "
                                "rounds and page reading used the deeper settings.")

            # 4. Follow-up rounds: leads from earlier rounds --------------------------------
            covered: set[str] = set()
            covered_names: set[str] = set()
            stop_reason = "the search budget for this depth was used" if len(rounds) > 1 else None
            local_dicts = [asdict(b) for b in local_businesses]
            for rno, budget in enumerate(rounds[1:], start=2):
                if any(pq.error and pq.error.get("kind") in FATAL_KINDS for pq in all_plan):
                    stop_reason = "a search provider error stopped further searching"
                    break
                leads = disc.find_leads([s for s in sources if is_seller_source(s)], local_dicts,
                                        name=search_name, brand=brand, category=category, alt_names=alt_names,
                                        covered_domains=covered, covered_names=covered_names,
                                        local_names=[n for n in (vd.directory_business_name(s) for s in sources
                                                                 if _in_home_city(s)) if n])
                fplan = disc.scope_plan(disc.follow_up_plan(leads, search_name, category, rno, budget, seen), req.area)
                if not fplan:
                    stop_reason = f"no new leads to follow after round {rno - 1}"
                    break
                progress(f"Following up {len(fplan)} leads (round {rno})", 12 + 10 * (rno - 1))
                before_domains = _seller_domains(sources)
                before_prices = _snippet_prices(sources)
                new_hits = await self._search_all(providers, fplan, cfg, required=False)
                all_hits += new_hits
                all_plan += fplan
                covered |= {d for pq in fplan for d in pq.domains or []}
                covered_names |= {pq.lead for pq in fplan if pq.lead and not pq.domains}
                sources = build_sources(all_hits, identity.brand_words)
                new_domains = _seller_domains(sources) - before_domains
                new_prices = _snippet_prices(sources) - before_prices
                round_log.append(_round_entry(rno, fplan, new_hits, new_domains, new_prices, sources))
                if not new_domains and not new_prices:
                    stop_reason = f"round {rno} found no new suppliers or prices"
                    break

            # 5. Evidence -----------------------------------------------------------------
            builder = OfferBuilder(identity.brand_words, identity.model_tokens)
            if ref_fetch is not None:
                ref_src = add_source(sources, url=identity.reference_url or query, title=identity.name,
                                     snippet="Page you provided", purpose="input_url", provider="page fetch",
                                     brand_words=identity.brand_words)
                ref_src.fetch = {"ok": ref_fetch.ok, "status": ref_fetch.status, "error": ref_fetch.error,
                                 "fetched_at": ref_fetch.fetched_at, "structured": False, "via": ref_fetch.via}
                if ref_fetch.ok and ref_fetch.html:
                    ref_src.page_text = ex.page_text(ref_fetch.html, PAGE_TEXT_CHARS)
                    found = builder.from_structured(ref_src, ex.structured_products(ref_fetch.html),
                                                    identity.model_tokens, ref_fetch.fetched_at, is_reference=True)
                    ref_src.fetch["structured"] = found
                elif ref_fetch.ok and ref_fetch.text:
                    ref_src.page_text = ex.focus_text(ref_fetch.text, identity.model_tokens, PAGE_TEXT_CHARS)
            builder.from_shopping(listings, sources)
            for s in sources:
                _snippet_details(s)

            progress("Reading supplier pages for prices and contacts", 50)
            fetch_attempts, fetch_failures, fetched_via = await self._fetch_and_extract(
                sources, builder, identity, fetcher, reader,
                max_pages=round(self.settings.fetch_max_pages * FETCH_SCALE[run_depth]))
            contact_pages = await self._contact_pages(sources, local_businesses, fetcher, CONTACT_PAGES[run_depth])

            if self.llm is not None and getattr(self.llm, "key_rejected", False):
                identity.notes.append("AI evidence reading skipped: Anthropic rejected the saved API key.")
                llm_summary = None
            elif self.llm is not None:
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

            # 6. FX + analysis --------------------------------------------------------------
            progress("Converting currencies (Bank of Canada)", 82)
            fx_service = FxService(self.db, client, fallback=ai_fetcher)
            currencies = {o.currency for o in builder.offers if o.currency and o.price is not None}
            fx = await fx_service.rates(currencies)

            progress("Comparing offers", 90)
            credits = current_credits()
            extra_rows = [r for r in (shopping_status, *local_status) if r]
            meta = {
                "query": query, "depth": depth, "quantity": quantity, "researched_at": iso(),
                "duration_s": round(time.monotonic() - started, 1),
                "providers": {"web": providers.web.name,
                              "shopping": providers.shopping.name if providers.shopping else None,
                              "local": f"{providers.local.name} (Google Maps)" if providers.local else None,
                              "llm": self.settings.anthropic_model if self.llm is not None else None,
                              "fx": "Bank of Canada Valet",
                              "fetch_fallback": VIA if ai_fetcher is not None else None},
                "queries": [asdict(p) for p in all_plan] + extra_rows,
                "plan": {"category": category.key, "category_label": category.label,
                         "high_risk": category.high_risk, "rounds": round_log, "stop_reason": stop_reason,
                         "deepened": deepened, "run_depth": run_depth, "alt_names": alt_names,
                         "used_ok": req.used_ok,
                         "channels": disc.channel_table(category, req.used_ok), "home": disc.HOME["city"],
                         "local_search": ("Google Maps via SerpApi" if providers.local else
                                          "not available (needs a SerpApi key); local suppliers were searched on "
                                          "the web only")},
                "local_businesses": local_dicts,
                "contact_pages": contact_pages,
                "answers": dict(req.answers),
                "stated_assumptions": list(req.assumptions),  # for unanswered questions ("assumptions" = import inputs)
                "area": req.area,
                "filters": dict(req.filters),
                "credits": credits,
                "cost_estimate": {"usd": estimate_usd(credits), "prices_checked": PRICES_CHECKED,
                                  "note": "Anthropic charges estimated from reported usage at list prices"},
                "fetch": {"attempted": fetch_attempts, "failed": fetch_failures, "via_anthropic": fetched_via,
                          "robots_respected": self.settings.respect_robots_txt},
                "fx_errors": fx_service.errors,
            }
            result = analyze(identity=asdict(identity), sources=sources, offers=builder.offers, fx=fx,
                             assumptions={}, meta=meta, home_province=self.settings.home_province,
                             llm_summary=llm_summary)
            progress("Done", 100)
            return result

    # ---------------------------------------------------------------- helpers
    async def _identify(self, query: str, fetcher: PageFetcher, providers: ProviderSet,
                        reader: AnthropicPageReader | None = None):
        input_type = ex.classify_input(query)
        if input_type != "url":
            tokens = ex.model_tokens(query)
            return Identity(query, input_type, query, tokens, _brand_words(query), "your request"), None
        url = query.strip()
        fr = await fetcher.fetch(url) if self.settings.fetch_pages else None
        if fr is not None and not fr.ok and fr.network_failure and reader is not None:
            via = await reader.read(url)
            if via.ok:
                fr = via
            else:
                fr.error = f"{fr.error}; {via.error}"
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
        elif fr is not None and fr.ok and fr.text:
            heading = next((ln.lstrip("#").strip() for ln in fr.text.splitlines()
                            if re.match(r"^#{1,2}\s+\S", ln.strip())), None)
            name = fr.title or (heading[:150] if heading and len(heading) > 5 else None)
            source = f"page title (page read via {VIA})"
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

    async def _search_all(self, providers: ProviderSet, plan: list[PlannedQuery], cfg: dict[str, Any],
                          required: bool = True) -> list[SearchHit]:
        """Run one round's searches. With `required`, a round where every search failed stops the research."""
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
                                                     include_raw=include_raw, domains=pq.domains)
                    pq.status, pq.result_count = "ok", len(res)
                    for h in res:
                        h.channel, h.market, h.round = pq.channel, pq.market, pq.round
                    return res
                except ProviderError as exc:
                    pq.status, pq.error = "failed", exc.to_dict()
                    if exc.kind in FATAL_KINDS:
                        fatal.append(exc)
                    return []

        results = await asyncio.gather(*(one(pq) for pq in plan))
        hits = [h for r in results for h in r]
        if required and not any(pq.status == "ok" for pq in plan):
            errs = [pq.error for pq in plan if pq.error]
            first = fatal[0] if fatal else None
            msg = first.user_message if first else (errs[0]["message"] if errs else "all searches failed")
            kinds = {e.get("kind") for e in errs if e}
            kind = first.kind if first else (kinds.pop() if len(kinds) == 1 else "search_failed")
            raise ResearchError(f"Search failed: {msg}", kind=kind, details=errs)
        return hits

    @staticmethod
    async def _shopping(providers: ProviderSet, name: str) -> tuple[list[ShoppingListing], dict[str, Any] | None]:
        if providers.shopping is None:
            return [], None
        row = {"query": name, "purpose": "shopping", "channel": "retail", "market": "canada", "round": 1,
               "country": "ca", "provider": "SerpApi (Google Shopping)", "domains": None, "lead": None}
        try:
            listings = await providers.shopping.shopping(name)
            return listings, {**row, "status": "ok", "result_count": len(listings), "error": None}
        except ProviderError as exc:
            return [], {**row, "status": "failed", "result_count": 0, "error": exc.to_dict()}

    @staticmethod
    async def _local(providers: ProviderSet, queries: list[str]) -> tuple[list[LocalBusiness], list[dict[str, Any]]]:
        """Businesses near Thunder Bay from Google Maps (SerpApi). Listing fields are kept as shown."""
        if providers.local is None or not queries:
            return [], []

        async def one(q: str) -> tuple[list[LocalBusiness], dict[str, Any]]:
            row = {"query": q, "purpose": "local_map", "channel": "local_suppliers", "market": "local", "round": 1,
                   "country": "canada", "provider": "SerpApi (Google Maps)", "domains": None, "lead": None}
            try:
                found = await providers.local.local(q, disc.HOME["maps_ll"])
                return found, {**row, "status": "ok", "result_count": len(found), "error": None}
            except ProviderError as exc:
                return [], {**row, "status": "failed", "result_count": 0, "error": exc.to_dict()}

        out = await asyncio.gather(*(one(q) for q in queries))
        seen: set[tuple[str, str]] = set()
        businesses: list[LocalBusiness] = []
        now = iso()
        for found, _ in out:
            for b in found:
                key = (re.sub(r"\W+", "", b.name.lower()), re.sub(r"\W+", "", (b.address or "").lower()))
                if key not in seen:
                    seen.add(key)
                    b.retrieved_at = now
                    businesses.append(b)
        return businesses, [row for _, row in out]

    async def _contact_pages(self, sources: list[Source], businesses: list[LocalBusiness], fetcher: PageFetcher,
                             limit: int) -> list[dict[str, Any]]:
        """Read the own websites of local and regional suppliers that have no email address yet (home page, then
        its contact page) for phone numbers, emails and addresses. robots.txt is respected by the fetcher."""
        if not self.settings.fetch_pages or limit <= 0:
            return []
        with_email = {s.domain for s in sources if s.contacts and s.contacts.get("emails")}
        targets: list[tuple[str, str, str]] = []  # (domain, name, url)
        for b in businesses:
            if b.website:
                dom = domain_of(b.website)
                if dom and dom not in with_email and not is_platform_domain(dom):
                    targets.append((dom, b.name, b.website))
        for s in sources:
            loc = s.location or {}
            near = loc.get("tier") in ("local", "regional") or loc.get("mentions_home") or "local" in s.markets
            if near and is_seller_source(s) and s.domain not in with_email and not is_platform_domain(s.domain):
                targets.append((s.domain, s.name, f"https://{s.domain}/"))
        picked, seen = [], set()
        for t in targets:
            if t[0] not in seen:
                seen.add(t[0])
                picked.append(t)
        pages_left = [limit]
        sem = asyncio.Semaphore(4)

        async def one(dom: str, name: str, url: str) -> dict[str, Any] | None:
            async with sem:
                if pages_left[0] <= 0:
                    return None
                pages_left[0] -= 1
                fr = await fetcher.fetch(url)
                entry = {"domain": dom, "name": name, "url": url, "ok": fr.ok, "error": fr.error,
                         "fetched_at": fr.fetched_at, "phones": [], "emails": [], "addresses": []}
                landed = domain_of(fr.final_url) if fr.final_url else dom
                if fr.ok and landed.removeprefix("www.") != dom.removeprefix("www."):
                    # sent to another site: its contacts aren't this business's
                    entry.update(ok=False, error=f"redirected to another site ({landed})")
                    return entry
                if not (fr.ok and fr.html):
                    return entry
                found = ex.contacts_in_html(fr.html)
                link = ex.contact_link(fr.html, url) if not found["emails"] else None
                if link and pages_left[0] > 0:
                    pages_left[0] -= 1
                    fr2 = await fetcher.fetch(link)
                    if fr2.ok and fr2.html:
                        more = ex.contacts_in_html(fr2.html)
                        entry["contact_url"] = link
                        for k in found:
                            found[k] = list(dict.fromkeys(more[k] + found[k]))[:3]
                entry.update(found)
                return entry

        out = await asyncio.gather(*(one(*t) for t in picked))
        return [e for e in out if e is not None]

    async def _fetch_and_extract(self, sources: list[Source], builder: OfferBuilder, identity: Identity,
                                 fetcher: PageFetcher, reader: AnthropicPageReader | None = None,
                                 max_pages: int | None = None) -> tuple[int, int, int]:
        sellers = [s for s in sources if is_seller_source(s) and "input_url" not in s.purposes
                   and "shopping" not in s.purposes]
        def priority(s: Source) -> tuple[int, int, int, int]:
            exact = ex.match_offer(identity.model_tokens, f"{s.title} {s.snippet}",
                                   ex.alternative_models(identity.name, identity.model_tokens)).level == "exact"
            loc = s.location or {}
            local = loc.get("tier") == "local" or loc.get("mentions_home") or "local" in s.markets
            preferred = s.type in (DISTRIBUTOR, RETAILER, MANUFACTURER, B2B_MARKETPLACE)
            return (0 if exact else 1, 0 if local else 1, 0 if preferred else 1, int(s.id[1:]))
        ordered = sorted(sellers, key=priority)
        limit = max_pages if max_pages is not None else self.settings.fetch_max_pages
        to_fetch = ordered[:limit] if self.settings.fetch_pages else []
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
                _page_details(s, fr.html, fr.fetched_at)
                found = builder.from_structured(s, ex.structured_products(fr.html), identity.model_tokens,
                                                fr.fetched_at)
                s.fetch["structured"] = found
                if found:
                    done_ids.add(s.id)
            else:
                failures += 1
        via_ok = 0
        if reader is not None:
            # only pages this server couldn't connect to; a site's own refusal is final
            retry = [s for s, fr in fetched if not fr.ok and fr.network_failure][: reader.remaining]
            for s, fr in await self._read_via(reader, retry):
                if fr.ok and fr.text:
                    s.fetch = {"ok": True, "status": None, "error": None, "fetched_at": fr.fetched_at,
                               "structured": False, "via": VIA, "direct_error": s.fetch["error"]}
                    s.page_text = ex.focus_text(fr.text, identity.model_tokens, PAGE_TEXT_CHARS)
                    failures -= 1
                    via_ok += 1
                else:
                    s.fetch["error"] = f"{s.fetch['error']}; {fr.error}"
        for s in sellers:
            builder.from_snippet(s)
        dedupe_snippet_offers(builder.offers, done_ids)
        return len(to_fetch), failures, via_ok

    @staticmethod
    async def _read_via(reader: AnthropicPageReader, sources: list[Source]) -> list[tuple[Source, FetchResult]]:
        if not sources:
            return []
        tasks = {asyncio.create_task(reader.read(s.url)): s for s in sources}
        done, pending = await asyncio.wait(tasks, timeout=FALLBACK_STAGE_TIMEOUT_S)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        out = []
        for t, s in tasks.items():
            if t in pending:
                err = f"{VIA} gave up after {FALLBACK_STAGE_TIMEOUT_S}s"
            elif t.exception() is not None:
                log.warning("%s failed for %s: %r", VIA, s.url, t.exception())
                err = f"{VIA} failed: {type(t.exception()).__name__}"
            else:
                out.append((s, t.result()))
                continue
            out.append((s, FetchResult(s.url, False, None, None, err, iso(), via=VIA)))
        return out


async def _nothing() -> tuple[list[Any], None]:
    return [], None


async def _gather_or_raise(*aws: Awaitable[Any]) -> list[Any]:
    """Run together; if one fails, let the others finish (they share the HTTP client) and then raise."""
    results = await asyncio.gather(*aws, return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException):
            raise r
    return results


def _without_order_length(name: str) -> str:
    m = ex.order_length(name)
    if not m:
        return name
    start, end = m["span"]
    return re.sub(r"\s+", " ", f"{name[:start]} {name[end:]}").strip(" ,-") or name


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(value or ""))
    return float(m.group(0).replace(",", "")) if m else None


def _seller_domains(sources: list[Source]) -> set[str]:
    return {s.domain for s in sources if is_seller_source(s)}


def _snippet_prices(sources: list[Source]) -> set[tuple[str, float]]:
    return {(s.domain, round(p.amount, 2)) for s in sources if is_seller_source(s)
            for p in ex.find_prices(s.snippet or "")[:2]}


def _round_entry(rno: int, plan: list[PlannedQuery], hits: list[SearchHit], new_domains: set[str],
                 new_prices: set[tuple[str, float]], sources: list[Source]) -> dict[str, Any]:
    if rno == 1:
        new_domains, new_prices = _seller_domains(sources), _snippet_prices(sources)
    return {"round": rno, "searches": len(plan), "ok": sum(1 for pq in plan if pq.status == "ok"),
            "failed": sum(1 for pq in plan if pq.status == "failed"), "results": len(hits),
            "new_suppliers": sorted(new_domains)[:25], "new_supplier_count": len(new_domains),
            "new_prices": len(new_prices), "leads": [pq.lead for pq in plan if pq.lead]}


def _in_home_city(s: Source) -> bool:
    """A directory page placed in Thunder Bay by its own title or address path (".../Thunder-Bay/...")."""
    return disc.HOME["city"].lower() in f"{s.title} {s.url.replace('-', ' ').replace('+', ' ')}".lower()


def _snippet_details(s: Source) -> None:
    """Contacts, location and marketplace badges written in a search result's own title and snippet."""
    text = f"{s.title}. {s.snippet}"
    found = ex.contacts_in_text(s.snippet or "")
    if any(found.values()) and not s.contacts:
        s.contacts = {**found, "basis": "search result text", "seen_at": s.retrieved_at, "url": s.url}
    if s.location is None:
        if found["addresses"]:
            tier, basis = ex.location_tier(found["addresses"][0], disc.HOME["city"])
            if tier:
                s.location = {"tier": tier, "basis": f"{basis} (search result text)"}
        elif disc.HOME["city"].lower() in text.lower():
            # "we ship to Thunder Bay" isn't a Thunder Bay business: worth reading first, not labelled local
            s.location = {"tier": None, "mentions_home": True,
                          "basis": f"search result mentions {disc.HOME['city']} (location not confirmed)"}
    s.badges = list(dict.fromkeys(s.badges + ex.badges(text)))[:3]


def _page_details(s: Source, html: str, fetched_at: str) -> None:
    s.image = s.image or ex.page_image(html, s.url)
    found = ex.contacts_in_html(html)
    if any(found.values()):
        s.contacts = {**found, "basis": "the supplier's own page", "seen_at": fetched_at, "url": s.url}
        if found["addresses"]:
            tier, basis = ex.location_tier(" ; ".join(found["addresses"]), disc.HOME["city"])
            if tier:
                s.location = {"tier": tier, "basis": f"{basis} on the supplier's page"}
    s.badges = list(dict.fromkeys(s.badges + ex.badges(f"{s.title}. {(s.page_text or '')[:3000]}")))[:3]


_AD_TYPES = {"classifieds / used", "auction / surplus"}
JUDGED_CATEGORIES = {"vehicle", "machinery", "property"}
SHORTLIST_NOTE = ("This is a type of product, not one model, so the listings are different models from different "
                  "makers and aren't ranked by price. Pick a model that meets the checklist, or ask a local dealer "
                  "which one suits your site, then search its model number to compare like-for-like prices.")
JUDGE_NOTE = ("Vehicles, equipment, property and used items aren't ranked by price: listings differ in condition, "
              "hours or mileage, options and location, which need a person's judgment. Open the listing pages and "
              "call the local dealers below; the asking prices seen are under Market value.")


FILTER_LABELS = {"year": "year", "km": "kilometres", "hours": "hours"}


def _apply_filters(o: Offer, f: dict[str, float], category: str) -> None:
    """Leave out listings that state something outside the search filters. A listing that doesn't state it stays
    in, with what couldn't be checked noted in its facts; prices are compared in CAD."""
    single = o.page_kind is None  # a page of many ads states many years and odometers: none of them is this one's
    text = f"{o.product_title} {o.evidence_quote or ''}"
    years = ex.model_years(o.product_title)
    facts: dict[str, Any] = {}
    if single and len(years) == 1:
        facts["year"] = years[0]
    if single and category in ("vehicle", "machinery"):
        # km and hours belong to this listing only if it's one vehicle's ad (one model year in its title) or the
        # title itself states them; a dealer's home page or an auction page quotes some other unit's numbers
        src = text if len(years) == 1 else o.product_title
        km, hours = ex.odometer_km(src), (ex.machine_hours(src) if category == "machinery" else None)
        if km is not None:
            facts["km"] = km
        if hours is not None:
            facts["hours"] = hours
    unchecked = []
    reasons = []
    lo, hi = f.get("price_min"), f.get("price_max")
    if (lo is not None or hi is not None) and o.price_cad is not None and o.price_type == "listed":
        if (lo is not None and o.price_cad < lo) or (hi is not None and o.price_cad > hi):
            reasons.append("outside your price range")
    for key, lo_key, hi_key in (("year", "year_min", "year_max"), ("km", None, "km_max"), ("hours", None, "hours_max")):
        lo_v, hi_v = f.get(lo_key) if lo_key else None, f.get(hi_key)
        if lo_v is None and hi_v is None:
            continue
        v = facts.get(key)
        if v is None:
            unchecked.append(FILTER_LABELS[key])
        elif (lo_v is not None and v < lo_v) or (hi_v is not None and v > hi_v):
            reasons.append(f"{FILTER_LABELS[key]} outside your filter ({v:,})")
    if unchecked:
        facts["not_stated"] = unchecked
    o.facts = facts
    if reasons:
        o.exclusion_reasons.extend(reasons)
        o.comparable = False


def _condition_from_ad_text(offers: list[Offer], category: str) -> None:
    """Vehicles, machinery, classifieds and auctions: read 'used' from the ad's own words near the price
    (title and quoted text), with a note saying which words. Other listings keep the title-only rule, since
    shop pages say things like 'used by professionals'."""
    for o in offers:
        if o.condition or not (category in ("vehicle", "machinery") or o.supplier_type in _AD_TYPES):
            continue
        words = ex.used_evidence(f"{o.product_title} {o.evidence_quote or ''}", machinery=category == "machinery")
        if words:
            o.condition = "used"
            note = f"Condition read from the listing text ('{words}')."
            if note not in o.notes:
                o.notes.append(note)


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
        src = by_id.get(o.source_id or "")
        o.image = src.image if src else None
    if "specs" in identity:
        specs, length = identity.get("specs") or [], identity.get("order_length") or None
    else:  # saved before spec checks existed
        specs, length = ex.request_specs(identity.get("name", ""))
    for o in offers:
        if not o.pack_qty:  # re-read from the title under the current rules ("100 Gloves/Box", "100/bx")
            pack = ex.pack_quantity(o.product_title)
            if pack:
                o.pack_qty, o.pack_text = pack
    category = (meta.get("plan") or {}).get("category") or disc.categorize(identity.get("name", ""),
                                                                           identity.get("category")).key
    _condition_from_ad_text(offers, category)
    name = identity.get("name", "")
    wanted = ex.detect_condition(name) or ("used" if ex.used_evidence(name) else None)
    year = ex.requested_model_year(name) if category in ("vehicle", "machinery") else None
    year_note = None
    if year and not any(sp["dim"] == "model year" for sp in specs):
        specs = specs + [{"dim": "model year", "value": str(year), "num": float(year), "label": f"model year {year}"}]
        researched_year = int((meta.get("researched_at") or iso())[:4])
        if not wanted and year <= researched_year - 2:
            wanted = "used"
            year_note = f"A {year} model is compared with used listings: in {researched_year} it is sold used."
    # vehicles, equipment, property and used items: listings differ in condition, hours, mileage, options and
    # location, so the app shows them for a person to judge instead of ranking prices
    judge = category in JUDGED_CATEGORIES or wanted == "used"
    # a type rather than a model ("portable two-way radio"): different makers' models aren't ranked by price
    shortlist = not judge and not tokens and guides.match(name) is not None
    apply_match(offers, tokens, by_id, specs, length, category=category, any_of=ex.alternative_models(name, tokens))
    # without a model number, the words that say which vehicle or machine is wanted ("hi-rail") must be in the
    # listing: otherwise any pickup, or any part with "truck" in its name, would pass
    quals = ex.qualifier_words(name, tokens) if category in ("vehicle", "machinery") and not tokens else []
    if quals:
        for o in offers:
            missing = ex.missing_qualifiers(f"{o.product_title} {o.evidence_quote or ''}", quals)
            if missing and o.match_level != "different":
                o.match_level = "different"
                o.match_notes = [f"Doesn't mention {', '.join(missing)}."]
    if category == "vehicle":
        for o in offers:
            toy, part = ex.vehicle_toy(o.product_title), ex.vehicle_part(o.product_title)
            if (toy or part) and o.match_level != "different":
                o.match_level = "compatible"
                o.match_notes = [f"Looks like a toy or scale model ('{toy}'), not the vehicle." if toy else
                                 f"Looks like a part or accessory ('{part}') for the vehicle, not the vehicle."]
    an.apply_costs(offers, fx, clean, quantity, order_feet=length["feet"] if length else None)
    conflicts = an.detect_conflicts(offers)
    an.assess_comparability(offers, tokens, quantity, order_length=length,
                            badges_by_source={s.id: s.badges for s in sources if s.badges}, wanted_condition=wanted)
    area = meta.get("area") or "both"
    filters = {k: v for k, v in (meta.get("filters") or {}).items() if v is not None}
    rentals: list[Offer] = []
    for o in offers:
        _apply_filters(o, filters, category)
        article = ex.article_words(o.product_title) if o.supplier_type in (UNKNOWN, None) else None
        if article:
            o.exclusion_reasons.append(f"an article, not a listing ('{article}')")
            o.comparable = False
        rental = ex.rental_words(f"{o.product_title} {o.evidence_quote or ''}") \
            if category in ("vehicle", "machinery") and not article else None
        if rental:
            o.exclusion_reasons.append(f"a rental or lease rate ('{rental}'), not a sale price")
            o.comparable = False
            if o.match_level not in ("different", "compatible"):
                rentals.append(o)
        local = ((by_id.get(o.source_id or "") and by_id[o.source_id].location) or {}).get("tier") == "local"
        if area == "local" and not local:
            o.exclusion_reasons.append("not shown to be in Thunder Bay (you chose Thunder Bay only)")
            o.comparable = False
        elif area == "outside" and local:
            o.exclusion_reasons.append("in Thunder Bay (you chose outside Thunder Bay only)")
            o.comparable = False
        kind = guides.off_topic(name, o.product_title) if shortlist else None
        if kind and o.price is not None:
            o.exclusion_reasons.append(f"its title doesn't name {kind} - may be a different product")
            o.comparable = False
        words = guides.consumer_words(name, f"{o.product_title} {o.evidence_quote or ''}")
        if words:
            o.exclusion_reasons.append(f"looks like a consumer product ('{words}') - not built or checked for "
                                       "industrial use")
            o.comparable = False
    an.stale_copy_flags(offers, meta.get("researched_at"))
    an.set_compare_values(offers)
    conflicts += an.outlier_flags(offers)
    rec = an.recommend(offers, tokens, specs=specs, order_length=length)
    if judge or shortlist:
        rec = {"lowest": None, "best_value": None, "basis": rec.get("basis"), "pool_size": rec.get("pool_size", 0),
               "notes": [JUDGE_NOTE if judge else SHORTLIST_NOTE]}
    if year_note:
        rec["notes"].insert(0, year_note)
    by_offer = {o.id: o for o in offers}
    for key in ("lowest", "best_value"):
        if rec.get(key):
            rec[key]["totals"] = mk.order_totals(by_offer[rec[key]["offer_id"]], quantity, length, home_province,
                                                 clean)
    vendors = vd.build_vendors(sources, offers, meta.get("local_businesses"), meta.get("contact_pages"),
                               home_city=disc.HOME["city"], quantity=quantity, item=identity.get("name", ""),
                               tokens=tokens)
    if area == "local":
        vendors = [v for v in vendors if v["tier"] == "local"]
    elif area == "outside":
        vendors = [v for v in vendors if v["tier"] != "local"]
    market = mk.market_value(offers, tokens, length, category)
    if shortlist:
        market["overall_new"] = None
        market["notes"].insert(0, "These are different models, so no single market value is shown: compare prices "
                                  "once you've picked a model.")
    fx_public = {cur: asdict(r) for cur, r in fx.items() if cur != "CAD"}
    checklist = import_checklist([asdict(o) for o in offers], fx_public, clean, category)
    compliance = COMPLIANCE.get(category, COMPLIANCE["general"])
    used_ok = (meta.get("plan") or {}).get("used_ok", True)
    plainly = recommend_plainly(offers, vendors, rec, tokens, quantity, length, home_province, used_ok, clean,
                                judge="listings" if judge else ("shortlist" if shortlist else None))
    if judge and quals and not plainly["listing_pages"]:
        plainly["needed"].insert(0, f"No listing found mentions {' / '.join(quals)}. Specialist dealers and upfitters "
                                    "usually sell these: ask the local dealers below, and send quote requests.")
    if rentals:
        names = ", ".join(dict.fromkeys(f"{o.supplier} ({o.product_title[:60]})" for o in rentals[:3]))
        plainly["needed"].append(f"Rentals were found, if renting suits the job: {names}.")
    rfqs = rfq_drafts(vendors, identity, quantity, length, meta.get("answers"), compliance, category)
    cov = coverage_report(meta, sources, offers, vendors, market)
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
        "analysis_version": ANALYSIS_VERSION,
        **meta,
        "identity": identity,
        "product_key": product_key,
        "assumptions": clean,
        "sources": [s.public() for s in sources],
        "source_counts": source_counts,
        "offers": [asdict(o) for o in offers_sorted],
        "recommendations": rec,
        "recommendation": plainly,
        "market_value": market,
        "rfq_drafts": rfqs,
        "coverage": cov,
        "vendors": vendors,
        "vendor_summary": vd.vendor_summary(vendors),
        "quality": quality,
        "channels": chs,
        "opportunities": an.channel_opportunities(chs, quantity),
        "alternatives": alternatives,
        "spec_differences": an.spec_differences(offers),
        "alternatives_ai": alternatives_ai,
        "fx": fx_public,
        "import_notes": general_notes(home_province),
        "import_checklist": checklist,
        "compliance": compliance,
        "guide": guides.public(name),
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
                 "cost_estimate", "fetch", "fx_errors", "plan", "local_businesses", "contact_pages", "answers",
                 "stated_assumptions", "area", "filters"]
    meta = {k: result.get(k) for k in meta_keys}
    if quantity is not None:
        meta["quantity"] = quantity or None
    identity = dict(result["identity"])
    if identity.get("input_type") != "url":
        # part numbers are re-read from the request under the current rules ("500MCM" is a size, not a model)
        identity["model_tokens"] = ex.model_tokens(identity.get("name", ""))
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
