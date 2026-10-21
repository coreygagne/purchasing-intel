"""Comparison, recommendations and evidence summaries.

Deterministic and explainable: every recommendation lists the factors and
the evidence behind them. Nothing here invents a price, rating or review;
it only compares what the sources said.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from . import extract as ex
from .evidence import Offer, Source, canonical_url, is_search_results_url
from .fx import FxRate
from .import_costs import delivered_estimate
from .suppliers import (B2B_MARKETPLACE, CLASSIFIEDS, COMPLAINTS, COUNTRY_NAMES, DEALS, DISTRIBUTOR, FORUM,
                        GOVERNMENT, MANUFACTURER, MARKETPLACE, RETAILER, REVIEW, UNKNOWN, VIDEO)

SUPPLIER_TYPE_POINTS = {DISTRIBUTOR: 15, MANUFACTURER: 15, RETAILER: 12, MARKETPLACE: 5, B2B_MARKETPLACE: 3,
                        CLASSIFIEDS: 0, UNKNOWN: 2}
PRICE_LABEL = {"structured_data": "the page's own price data", "shopping_api": "the Google Shopping listing",
               "llm_verified": "verified page text"}
EVIDENCE_POINTS = {"structured_data": 10, "shopping_api": 8, "llm_verified": 7, "snippet": 2}


def fmt_money(value: float | None, currency: str | None) -> str:
    if value is None:
        return "n/a"
    return f"{currency or '?'} {value:,.2f}"


# --------------------------------------------------------------- FX + costs


def apply_costs(offers: list[Offer], fx: dict[str, FxRate], assumptions: dict[str, float | None],
                quantity: int | None, order_feet: float | None = None) -> None:
    for o in offers:
        o.exclusion_reasons = []
        o.price_cad = o.fx_rate = o.fx_date = o.unit_price = o.unit_price_cad = None
        o.per_ft_cad = o.order_total_cad = None
        if o.price is not None and o.currency:
            rate = FxRate("CAD", 1.0, "", "identity") if o.currency == "CAD" else fx.get(o.currency)
            if rate:
                o.fx_rate, o.fx_date = rate.rate_to_cad, rate.rate_date or None
                o.price_cad = round(o.price * rate.rate_to_cad, 2)
        feet = ex.LengthUnit(o.per_length, o.per_length_qty).feet if o.per_length else None
        if feet and o.price_cad is not None:
            o.per_ft_cad = round(o.price_cad / feet, 4)
            if order_feet:
                o.order_total_cad = round(o.per_ft_cad * order_feet, 2)
        elif o.price is not None and o.pack_qty:
            o.unit_price = round(o.price / o.pack_qty, 4)
            if o.price_cad is not None:
                o.unit_price_cad = round(o.price_cad / o.pack_qty, 4)
        # Totals only make sense for a single, published price per item (not per foot or metre)
        o.delivered = (delivered_estimate(_offer_dict(o), assumptions, quantity)
                       if o.price_type == "listed" and not o.per_length else None)


def _offer_dict(o: Offer) -> dict[str, Any]:
    return {"price_cad": o.price_cad, "currency": o.currency, "country": o.country, "pack_qty": o.pack_qty,
            "unit_price_cad": o.unit_price_cad, "shipping_cost": o.shipping_cost, "shipping_text": o.shipping_text,
            "shipping_scope": o.shipping_scope, "fx_rate": o.fx_rate}


# ----------------------------------------------------------- comparability


def assess_comparability(offers: list[Offer], tokens: list[str], quantity: int | None) -> None:
    for o in offers:
        reasons: list[str] = []
        if o.price_type == "quote_required":
            reasons.append("price on request (quote required)")
        elif o.price_type == "unclear":
            reasons.append("several prices in source text; which one applies is unclear")
        elif o.price_type == "range":
            reasons.append("price range, not a single price")
        elif o.price is None:
            reasons.append("no price found")
        if tokens and o.match_level != "exact":
            reasons.append({"variant": "different variant/kit or suffix not confirmed",
                            "compatible": "compatible/aftermarket item, not the original",
                            "different": "requested model not found in listing"}.get(o.match_level, "not verified as same item"))
        if o.condition and o.condition not in ("new",):
            reasons.append(f"condition: {o.condition}")
        if o.price is not None and not o.currency:
            reasons.append("currency not stated")
        elif o.price is not None and o.price_cad is None:
            reasons.append(f"no exchange rate available for {o.currency}")
        if o.superseded():
            reasons.append("superseded by a more reliable price for the same listing")
        if o.per_length == "?":
            reasons.append(f"price unit unclear ('{o.per_length_text}': per metre, or per 1,000 ft in the wire trade)")
        for c in o.spec_conflicts:
            reasons.append(f"different size or spec: {c}")
        if o.availability and any(w in o.availability for w in ("out of stock", "sold out", "discontinued",
                                                                "unavailable", "not available")):
            reasons.append(f"not available to buy ({o.availability})")
        if quantity and o.moq:
            nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", o.moq)]
            if nums and nums[0] > quantity:
                reasons.append(f"minimum order ({o.moq}) exceeds the {quantity} units you need")
        o.exclusion_reasons = reasons
        o.comparable = not reasons
        # informational flags
        if o.price_basis == "snippet" and o.comparable:
            o.flags.append("Price only seen in a search snippet - confirm on the supplier page.")
        if is_search_results_url(o.url) and o.price is not None:
            o.flags.append("Price seen on the site's search-results page, which lists several products or sellers - "
                           "open it to confirm which listing this price belongs to.")
        if o.currency_basis.startswith("inferred"):
            o.flags.append(f"Currency {o.currency} {o.currency_basis}.")
        if o.country != "CA":
            o.flags.append("Possible import: duties, surtaxes, brokerage and longer delivery may apply."
                           if o.country else "Seller country unknown.")
        if o.moq and not quantity:
            o.flags.append(f"Minimum order: {o.moq}. Enter your quantity to check it.")
        if o.supplier_type in (MARKETPLACE, B2B_MARKETPLACE, CLASSIFIEDS):
            o.flags.append("Marketplace: the actual seller may be a third party - check seller ratings and return policy.")
        if o.supplier_type == UNKNOWN and not o.supplier_in_directory:
            o.flags.append("Supplier not in the built-in directory - verify the business before ordering.")
        if not tokens and o.comparable:
            if o.spec_missing:
                o.flags.append(f"The listing doesn't state: {', '.join(o.spec_missing)} - confirm before ordering.")
            elif not o.spec_confirmed:
                o.flags.append("Equivalence not verified (no model number) - compare specs before choosing.")
        if o.per_length in ("ft", "m"):
            o.flags.append(f"Priced {ex.LengthUnit(o.per_length, o.per_length_qty).label} "
                           f"({o.per_length_text}) - compared per foot.")
    _split_length_basis(offers)


def _split_length_basis(offers: list[Offer]) -> None:
    """Per-foot/metre prices and per-item prices can't be ranked together. The larger group (per-length on
    a tie) stays comparable; the other is set aside with a reason."""
    pool = [o for o in offers if o.comparable]
    per_len = [o for o in pool if o.per_length in ("ft", "m")]
    per_item = [o for o in pool if not o.per_length]
    if not per_len or not per_item:
        return
    if len(per_len) >= len(per_item):
        for o in per_item:
            o.exclusion_reasons.append("priced per item (e.g. a reel or cut length) while other listings are "
                                       "priced per foot/metre - check the length to compare")
            o.comparable = False
    else:
        for o in per_len:
            o.exclusion_reasons.append(f"priced {ex.LengthUnit(o.per_length, o.per_length_qty).label} while other "
                                       "listings are priced per item")
            o.comparable = False


STALE_COPY_DAYS = 3


def _when(value: str | None) -> datetime | None:
    try:
        t = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def stale_copy_flags(offers: list[Offer], researched_at: str | None) -> None:
    """A price observed well before the research ran came from an old copy of the page (Anthropic web fetch
    can return a cached copy). It is shown with its date but is no longer strong evidence of today's price."""
    ref = _when(researched_at) or datetime.now(timezone.utc)
    for o in offers:
        seen = _when(o.observed_at)
        if seen is None or o.price is None:
            continue
        age = (ref - seen).days
        if age >= STALE_COPY_DAYS:
            o.flags.append(f"Price read from a copy of the page dated {seen.date().isoformat()} ({age} days before "
                           "this research) - confirm the current price.")
            if o.confidence in ("high", "medium"):
                o.confidence = "low"


def detect_conflicts(offers: list[Offer]) -> list[dict[str, Any]]:
    """Same supplier and URL with different prices: keep both, prefer the stronger evidence."""
    rank = {"structured_data": 3, "shopping_api": 2, "llm_verified": 2, "snippet": 1, "none": 0}
    by_key: dict[str, list[Offer]] = defaultdict(list)
    for o in offers:
        if o.price is not None:
            by_key[canonical_url(o.url)].append(o)
    conflicts = []
    for url, group in by_key.items():
        prices = {(round(o.price, 2), o.currency) for o in group if o.price is not None}
        if len(group) < 2:
            continue
        best = max(group, key=lambda o: (rank.get(o.price_basis, 0), o.observed_at))
        superseded = False
        for o in group:
            if o is not best and o.price_basis == "snippet" and best.price_basis != "snippet":
                o.notes.append(f"Superseded by {PRICE_LABEL.get(best.price_basis, best.price_basis)} for the same page.")
                superseded = True
        if len(prices) > 1:
            detail = "; ".join(f"{fmt_money(o.price, o.currency)} ({o.price_basis.replace('_', ' ')})" for o in group)
            outcome = (f"The price from {PRICE_LABEL.get(best.price_basis, best.price_basis)} "
                       f"({fmt_money(best.price, best.currency)}) is used; the search-snippet price is shown for "
                       "reference only." if superseded else
                       "Both are shown; neither is preferred automatically.")
            conflicts.append({"type": "price_disagreement", "url": url, "supplier": best.supplier,
                              "offer_ids": [o.id for o in group],
                              "text": f"Sources disagree on the price at {best.supplier}: {detail}. {outcome} "
                                      "Confirm before ordering."})
            for o in group:
                o.flags.append("Sources disagree on this listing's price (see 'Watch out for').")
    # Same supplier, different listings/sources, different prices (informational)
    by_supplier: dict[str, list[Offer]] = defaultdict(list)
    for o in offers:
        if o.price is not None and o.price_type == "listed" and o.match_level == "exact" and not o.superseded():
            by_supplier[re.sub(r"[^a-z0-9]", "", o.supplier.lower())].append(o)
    for group in by_supplier.values():
        urls = {canonical_url(o.url) for o in group}
        prices = {(round(o.price, 2), o.currency) for o in group}
        if len(urls) > 1 and len(prices) > 1:
            detail = "; ".join(f"{fmt_money(o.price, o.currency)} ({o.price_basis.replace('_', ' ')})" for o in group)
            conflicts.append({"type": "supplier_price_mismatch", "supplier": group[0].supplier,
                              "offer_ids": [o.id for o in group],
                              "text": f"{group[0].supplier} appears with different prices in different sources: "
                                      f"{detail}. They may be different listings or a recent price change."})
    return conflicts


def outlier_flags(offers: list[Offer]) -> list[dict[str, Any]]:
    pool = [o for o in offers if o.comparable]
    vals = [_cmp_value(o) for o in pool]
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return []
    med = statistics.median(vals)
    out = []
    for o in pool:
        v = _cmp_value(o)
        if v is None or med <= 0:
            continue
        if v < med * 0.5:
            o.flags.append("Unusually low vs. other comparable offers - check for a different variant, used item, or error.")
            out.append({"type": "low_outlier", "offer_ids": [o.id],
                        "text": f"{o.supplier} at {fmt_money(o.price, o.currency)} is less than half the median comparable "
                                "price. Verify it is the same item and condition."})
        elif v > med * 2:
            o.flags.append("Unusually high vs. other comparable offers.")
    return out


# --------------------------------------------------------- recommendations


def _cmp_value(o: Offer) -> float | None:
    return o.compare_value


def _comparison_basis(pool: list[Offer]) -> tuple[str, bool, list[Offer]]:
    """(basis label, per-unit?, listings counted as single units). Pure - no side effects.

    Listing price when pack sizes agree. Per-unit price only when at least two listings state a
    pack size; then listings without one are counted as single units (and flagged)."""
    if pool and all(o.per_length in ("ft", "m") for o in pool):
        return "price per foot (CAD)", False, []
    qtys = {o.pack_qty for o in pool}
    stated = [o for o in pool if o.pack_qty]
    if len(qtys) <= 1 or len(stated) < 2:
        return "listing price (CAD)", False, []
    return ("price per unit (CAD; listings without a stated pack size counted as single units)", True,
            [o for o in pool if not o.pack_qty])


def set_compare_values(offers: list[Offer]) -> None:
    """Decide the comparison basis once per analysis and record each offer's comparable value."""
    pool = [o for o in offers if o.comparable]
    _, per_unit, unknown = _comparison_basis(pool)
    for o in offers:
        if o.per_ft_cad is not None:
            o.compare_value = o.per_ft_cad
        else:
            o.compare_value = o.unit_price_cad if (per_unit and o.pack_qty) else o.price_cad
    for o in unknown:
        o.flags.append("Pack size not stated in the title - counted as a single unit in the per-unit comparison.")
    if not per_unit and len({o.pack_qty for o in pool}) > 1:
        for o in pool:
            if o.pack_qty:
                o.flags.append(f"States a pack size ({o.pack_text}); compared by listing price because other "
                               "listings don't state one.")


# A comparable price below this share of the median is set aside from both recommendations: it is far
# more often a different size or variant, a per-foot price or an error than a real deal.
IMPLAUSIBLE_LOW = 0.35


def recommend(offers: list[Offer], tokens: list[str], specs: list[dict[str, Any]] | None = None,
              order_length: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lowest comparable price and best overall value.

    Call after assess_comparability() and set_compare_values(), which decide which offers are
    comparable and on what basis (listing, per-unit or per-foot price); analyze() does this in order.
    """
    pool = [o for o in offers if o.comparable]
    notes: list[str] = []
    if not pool:
        reasons = []
        if not offers:
            reasons.append("No priced listings were found in the search results.")
        else:
            counts = defaultdict(int)
            for o in offers:
                for r in o.exclusion_reasons:
                    counts[r] += 1
            reasons.append("No listing met the comparison rules: " +
                           "; ".join(f"{n} x {r}" for r, n in sorted(counts.items(), key=lambda kv: -kv[1])[:5]) + ".")
        return {"lowest": None, "best_value": None, "basis": None, "notes": reasons, "pool_size": 0}

    basis, _, unknown_pack = _comparison_basis(pool)
    ranked_pool = pool
    labels = ", ".join(sp["label"] for sp in specs or [])
    if specs and not tokens:
        # prefer listings whose own text states every requested spec
        confirmed = [o for o in pool if o.spec_confirmed and not o.spec_missing]
        if confirmed and len(confirmed) < len(pool):
            notes.append(f"{len(pool) - len(confirmed)} comparable listing(s) don't state all of: {labels}. The "
                         f"recommendations use the {len(confirmed)} that do.")
            ranked_pool = confirmed
        elif not confirmed:
            notes.append(f"No listing states all of: {labels}. Check the size and material on each listing "
                         "before ordering.")
    known = [o for o in ranked_pool if _cmp_value(o) is not None]
    if len(known) >= 3:
        med = statistics.median(_cmp_value(o) for o in known)
        implausible = [o for o in known if _cmp_value(o) < med * IMPLAUSIBLE_LOW]
        if implausible:
            ranked_pool = [o for o in ranked_pool if o not in implausible]
            w = min(implausible, key=lambda o: _cmp_value(o))
            notes.append(f"Set aside {len(implausible)} listing(s) priced far below the rest, e.g. {w.supplier} at "
                         f"{fmt_money(w.price, w.currency)} ({(1 - _cmp_value(w) / med) * 100:.0f}% below the median "
                         f"of CAD {med:,.2f}): likely a different size or variant, a per-foot price or an error. "
                         "Open it before relying on it.")
            for o in implausible:
                o.flags.insert(0, "Not recommended: priced far below the other comparable listings - likely a "
                                  "different size or variant, a per-foot price or an error.")
    if unknown_pack:
        notes.append(f"Pack sizes differ: {len(unknown_pack)} listing(s) don't state one and were counted as single "
                     "units. Check pack contents before relying on the per-unit ranking.")
    strong = [o for o in ranked_pool if o.confidence in ("high", "medium")]
    lowest_pool = strong or ranked_pool
    lowest = min(lowest_pool, key=lambda o: _cmp_value(o) or float("inf"))
    cheaper_weak = [o for o in ranked_pool if o.confidence == "low" and (_cmp_value(o) or 1e18) < (_cmp_value(lowest) or 0)]
    if cheaper_weak:
        w = min(cheaper_weak, key=lambda o: _cmp_value(o) or float("inf"))
        cad = f" (about CAD {w.price_cad:,.2f}" + (" before shipping/import costs)" if w.country != "CA" else ")") \
            if w.currency != "CAD" and w.price_cad is not None else ""
        notes.append(f"Possibly lower: {w.supplier} at {fmt_money(w.price, w.currency)}{cad} was seen only in a "
                     "search snippet (unverified). Check that page before relying on it.")

    vals = sorted(v for v in (_cmp_value(o) for o in ranked_pool) if v is not None)
    lowest_expl = [
        f"Lowest {basis} among {len(ranked_pool)} comparable listing(s)"
        + (" with page-level or listing-level price evidence." if strong else "."),
        f"Price evidence: {lowest.price_label}.",
    ]
    if lowest.confidence == "low":
        lowest_expl.append("Low-confidence evidence (search snippet or search-results page) - confirm the price on "
                           "the listing itself before ordering.")
    if lowest.currency != "CAD":
        lowest_expl.append(f"Converted from {fmt_money(lowest.price, lowest.currency)} at {lowest.fx_rate} "
                           f"(Bank of Canada, {lowest.fx_date}).")
    if len(vals) >= 3:
        med = statistics.median(vals)
        lv = _cmp_value(lowest) or 0
        if (med - lv) / med >= 0.005:
            lowest_expl.append(f"{(med - lv) / med * 100:.0f}% below the median of the {len(vals)} comparable observed "
                               f"prices (calculated; median CAD {med:,.2f}).")
    if lowest in unknown_pack:
        lowest_expl.append("This listing doesn't state a pack size; it was counted as one unit.")
    if lowest.country != "CA":
        lowest_expl.append("Seller appears to be outside Canada - landed cost may be higher than the listed price.")
    if lowest.delivered and not lowest.delivered["complete"]:
        lowest_expl.append("Delivered cost incomplete: " + ", ".join(lowest.delivered["missing"]) + " unknown.")
    lowest_expl += _length_lines(lowest, order_length)
    if lowest.spec_confirmed:
        lowest_expl.append(f"The listing states: {', '.join(lowest.spec_confirmed)}.")

    lowest_rec = {"offer_id": lowest.id, "supplier": lowest.supplier, "price": lowest.price,
                  "currency": lowest.currency, "price_cad": lowest.price_cad, "compare_value": _cmp_value(lowest),
                  "basis": basis, "url": lowest.url, "explanation": lowest_expl, **_length_rec(lowest, order_length)}

    # ---- best overall value: transparent points, not "cheapest wins".
    # Offers whose price was only seen in a snippet are considered only when
    # nothing better is available.
    value_pool = [o for o in (strong or ranked_pool) if _cmp_value(o) is not None]
    if not value_pool:
        return {"lowest": None, "best_value": None, "basis": basis, "pool_size": len(pool),
                "notes": notes + ["No comparable listing has a CAD value to rank."]}
    lo = min(_cmp_value(o) for o in value_pool)
    scored = []
    for o in value_pool:
        v = _cmp_value(o)
        factors = []
        # 40 points for the lowest price, falling linearly to 0 at 50% above it
        premium = (v / lo - 1) if v is not None and lo > 0 else 1.0
        price_pts = max(0.0, 40.0 * (1 - premium / 0.5))
        factors.append({"factor": "Price position", "points": round(price_pts, 1),
                        "evidence": f"{fmt_money(v, 'CAD')} ({basis})" +
                                    (f", {premium * 100:.0f}% above the lowest" if premium > 0.0005 else ", lowest")})
        ev = EVIDENCE_POINTS.get(o.price_basis, 0)
        factors.append({"factor": "Price evidence", "points": ev, "evidence": o.price_label})
        st = SUPPLIER_TYPE_POINTS.get(o.supplier_type, 2)
        factors.append({"factor": "Supplier type", "points": st,
                        "evidence": f"{o.supplier_type}" + (" (in directory)" if o.supplier_in_directory else " (not in directory)")})
        dom = 15 if o.country == "CA" else (5 if o.country == "US" else 0)
        factors.append({"factor": "Domestic supply", "points": dom,
                        "evidence": COUNTRY_NAMES.get(o.country or "", "unknown country") +
                                    ("" if o.country == "CA" else " - import costs/delays possible")})
        if o.availability:
            a = 5 if "in stock" in o.availability or o.availability == "instock" else (-10 if any(
                w in o.availability for w in ("out of stock", "sold out", "discontinued")) else 0)
            factors.append({"factor": "Availability", "points": a, "evidence": o.availability})
        if o.warranty:
            factors.append({"factor": "Warranty stated", "points": 5, "evidence": o.warranty})
        if o.shipping_text:
            factors.append({"factor": "Shipping terms stated", "points": 5 if o.shipping_cost == 0 else 3,
                            "evidence": o.shipping_text})
        if o.rating and o.rating.get("value") is not None and (o.rating.get("count") or 0) >= 10:
            ratio = o.rating["value"] / (o.rating.get("best") or 5.0)
            pts = 5 if ratio >= 0.8 else (-5 if ratio <= 0.6 else 0)
            factors.append({"factor": "Customer rating", "points": pts,
                            "evidence": f"{o.rating['value']}/{o.rating.get('best') or 5} from {o.rating['count']} ratings ({o.rating['basis']})"})
        total = round(sum(f["points"] for f in factors), 1)
        scored.append((total, o, factors))
    scored.sort(key=lambda t: (-t[0], _cmp_value(t[1]) or 0))
    best_score, best, best_factors = scored[0]
    best_expl = [f"Highest overall score ({best_score:g}) across price, evidence quality, supplier type, "
                 "domestic supply, availability, warranty, shipping and ratings."]
    if best.id == lowest.id:
        best_expl.append("It is also the lowest comparable price.")
    else:
        bv, lv = _cmp_value(best) or 0, _cmp_value(lowest) or 0
        gains = [f["factor"].lower() for f in best_factors
                 if f["factor"] != "Price position" and f["points"] > _factor_points(scored, lowest, f["factor"])]
        if lv > 0 and bv > lv:
            best_expl.append(f"Costs CAD {bv - lv:,.2f} ({(bv - lv) / lv * 100:.0f}%) more than the lowest comparable "
                             f"price ({lowest.supplier})" + (f"; in exchange it scores better on: {', '.join(gains)}."
                                                             if gains else "."))
        elif gains:
            best_expl.append(f"Scores better than {lowest.supplier} on: {', '.join(gains)}.")
    if len(scored) > 1:
        runner = scored[1]
        best_expl.append(f"Runner-up: {runner[1].supplier} ({runner[0]:g} points).")
    if best.id != lowest.id:
        best_expl += _length_lines(best, order_length)
    best_rec = {"offer_id": best.id, "supplier": best.supplier, "price": best.price, "currency": best.currency,
                "price_cad": best.price_cad, "compare_value": _cmp_value(best), "url": best.url, "score": best_score,
                "factors": best_factors, "explanation": best_expl, **_length_rec(best, order_length),
                "scoring_note": "Points are a transparent rule of thumb (price up to 40; evidence up to 10; supplier "
                                "type up to 15; domestic supply up to 15; availability, warranty, shipping, ratings "
                                "up to 5 each). Use judgment - especially on safety-critical items."}
    if len(pool) == 1:
        notes.append("Only one comparable listing was found, so there is nothing to compare it against.")
    if not tokens and specs:
        notes.append(f"No model number in the request: listings were checked against the specs it states "
                     f"({labels}). Confirm the full specification (ratings, certifications, construction) before "
                     "ordering.")
    elif not tokens:
        notes.append("No model number in the request: listings were matched by search relevance only. "
                     "Confirm specifications are equivalent before choosing.")
    return {"lowest": lowest_rec, "best_value": best_rec, "basis": basis, "notes": notes, "pool_size": len(pool)}


def _length_lines(o: Offer, order_length: dict[str, Any] | None) -> list[str]:
    if o.per_ft_cad is None:
        return []
    plain = o.per_length == "ft" and o.per_length_qty == 1 and o.currency == "CAD"
    lines = [] if plain else [f"CAD {o.per_ft_cad:,.2f} per foot (calculated from {fmt_money(o.price, o.currency)} "
                              f"{ex.LengthUnit(o.per_length, o.per_length_qty).label})."]
    if o.order_total_cad is not None and order_length:
        lines.append(f"For {order_length['text']}: about CAD {o.order_total_cad:,.2f} (calculated: per-foot price x "
                     f"{order_length['feet']:g} ft; before tax, shipping and any cutting or reel charges).")
    return lines


def _length_rec(o: Offer, order_length: dict[str, Any] | None) -> dict[str, Any]:
    if o.per_ft_cad is None:
        return {}
    return {"unit": ex.LengthUnit(o.per_length, o.per_length_qty).label, "per_ft_cad": o.per_ft_cad,
            "order_total_cad": o.order_total_cad, "order_length": (order_length or {}).get("text")}


def _factor_points(scored: list[tuple[float, Offer, list[dict[str, Any]]]], offer: Offer, factor: str) -> float:
    for _, o, fs in scored:
        if o.id == offer.id:
            for f in fs:
                if f["factor"] == factor:
                    return f["points"]
    return 0


def spec_differences(offers: list[Offer]) -> list[dict[str, Any]]:
    """Specs published in page data that differ between same-or-similar listings."""
    relevant = [o for o in offers if o.specs and o.match_level in ("exact", "variant", "unverified", "compatible")]
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in relevant:
        for k, v in o.specs.items():
            by_key[k.strip().lower()].append({"offer_id": o.id, "supplier": o.supplier, "value": v,
                                              "match_level": o.match_level, "url": o.url})
    out = []
    for key, vals in by_key.items():
        distinct = {re.sub(r"\s+", " ", str(v["value"]).strip().lower()) for v in vals}
        if len(vals) >= 2 and len(distinct) > 1:
            out.append({"spec": key, "values": vals})
    return sorted(out, key=lambda d: d["spec"])


# ------------------------------------------------------------------ quality


REVIEW_LABELS = {REVIEW: "Professional / editorial review", FORUM: "User discussion (anecdotal)",
                 VIDEO: "Video review", COMPLAINTS: "Supplier reviews & complaints", GOVERNMENT: "Government / regulator",
                 MANUFACTURER: "Manufacturer statement (the maker's own claims or notices)",
                 DEALS: "Deal forum (past sale prices, not current offers)"}


def quality_evidence(sources: list[Source], offers: list[Offer], tokens: list[str]) -> dict[str, Any]:
    ratings = []
    for o in offers:
        if o.rating and o.rating.get("value") is not None:
            ratings.append({"offer_id": o.id, "supplier": o.supplier, "url": o.url, "value": o.rating["value"],
                            "best": o.rating.get("best") or 5.0, "count": o.rating.get("count"),
                            "basis": o.rating["basis"], "exact_model": o.match_level == "exact"})
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    issues, praise, recalls = [], [], []
    for s in sources:
        text = f"{s.title}. {s.snippet}"
        exact = bool(tokens) and ex.match_offer(tokens, text).level == "exact"
        if (s.type in REVIEW_LABELS and s.type != MANUFACTURER) or {"reviews", "issues"} & set(s.purposes):
            label = REVIEW_LABELS.get(s.type, "Other page found by review/issue search")
            groups[label].append({"source_id": s.id, "title": s.title, "url": s.url, "domain": s.domain,
                                  "excerpt": s.snippet[:400], "exact_model": exact,
                                  "published": s.published_date})
        for sent in ex.sentences_matching(s.snippet, ex.ISSUE_RE, 2):
            entry = {"quote": sent, "source_id": s.id, "url": s.url, "domain": s.domain, "type": s.type,
                     "exact_model": exact}
            (recalls if "recall" in sent.lower() else issues).append(entry)
        if s.type not in (RETAILER, MARKETPLACE, MANUFACTURER, DISTRIBUTOR, B2B_MARKETPLACE):
            for sent in ex.sentences_matching(s.snippet, ex.PRAISE_RE, 1):
                praise.append({"quote": sent, "source_id": s.id, "url": s.url, "domain": s.domain, "type": s.type,
                               "exact_model": exact})
    gov_recalls = [r for r in recalls if r["type"] == GOVERNMENT]
    return {
        "ratings": ratings,
        "ratings_note": "Ratings come from different sites with different reviewers and scales; they are listed, "
                        "not averaged." if ratings else "No structured customer ratings were found.",
        "sources_by_type": dict(groups),
        "issue_mentions": issues[:12],
        "praise_mentions": praise[:8],
        "recall_mentions": recalls[:6],
        "recall_note": ("A government source mentions a recall - check it before purchasing." if gov_recalls else
                        "Recall mentions found in non-government sources - verify at recalls-rappels.canada.ca."
                        if recalls else "No recall mentions found in the search results (this is not a guarantee).") ,
        "summary": None,  # optional AI summary is attached by the LLM layer
    }


# ----------------------------------------------------------------- channels

CHANNEL_GUIDANCE = {
    MANUFACTURER: "Buying direct can mean genuine stock and full warranty; some manufacturers only sell through "
                  "distributors or offer contract pricing for repeat volume.",
    DISTRIBUTOR: "Industrial distributors often negotiate account or volume pricing that isn't shown online; "
                 "ask for a quote at your expected annual volume.",
    RETAILER: "Retail pricing is usually transparent; watch for sales, contractor/pro pricing and bulk-buy discounts.",
    MARKETPLACE: "Marketplace listings vary by third-party seller: check seller ratings, return terms, warranty "
                 "validity and whether the item is genuine.",
    B2B_MARKETPLACE: "Wholesale marketplaces can offer low unit prices at a minimum order quantity, but add supplier "
                     "verification, quality control/inspection, compliance (e.g. CSA/UL), freight, duty/surtax, "
                     "and limited warranty recourse. Treat listed prices as indicative until quoted.",
    CLASSIFIEDS: "Used/clearance channels can cut cost substantially but usually without warranty; inspect before buying.",
}


def channels(offers: list[Offer], sources: list[Source]) -> list[dict[str, Any]]:
    by_type: dict[str, list[Offer]] = defaultdict(list)
    for o in offers:
        by_type[o.supplier_type].append(o)
    out = []
    for t, group in by_type.items():
        if t in (REVIEW, FORUM, VIDEO, COMPLAINTS, GOVERNMENT, DEALS):
            continue
        priced = [o for o in group if o.price is not None]
        quotes = [o for o in group if o.price_type == "quote_required"]
        moqs = [{"supplier": o.supplier, "moq": o.moq, "url": o.url} for o in group if o.moq]
        bulk = [{"supplier": o.supplier, "signal": o.bulk, "url": o.url} for o in group if o.bulk]
        packs = [{"supplier": o.supplier, "pack": o.pack_text, "unit_price_cad": o.unit_price_cad, "url": o.url}
                 for o in group if o.pack_qty and o.unit_price_cad is not None]
        ranges = [{"supplier": o.supplier, "low": o.price, "high": o.price_high, "currency": o.currency, "url": o.url}
                  for o in group if o.price_type == "range"]
        out.append({
            "type": t,
            "suppliers": sorted({o.supplier for o in group}),
            "listing_count": len(group),
            "priced_count": len(priced),
            "lowest_observed": _lowest_label(priced),
            "quote_required": [{"supplier": o.supplier, "url": o.url, "text": o.price_text} for o in quotes],
            "moq": moqs, "bulk_signals": bulk, "pack_sizes": packs, "price_ranges": ranges,
            "guidance": CHANNEL_GUIDANCE.get(t, "Unclassified seller - verify the business, terms and warranty."),
        })
    order = [DISTRIBUTOR, MANUFACTURER, RETAILER, MARKETPLACE, B2B_MARKETPLACE, CLASSIFIEDS, UNKNOWN]
    out.sort(key=lambda c: order.index(c["type"]) if c["type"] in order else 99)
    return out


def _lowest_label(priced: list[Offer]) -> str | None:
    """Lowest price in a channel, counting only comparable offers (same item, new, single price)."""
    listed = [o for o in priced if o.comparable and o.price_cad is not None]
    if not listed:
        return None
    o = min(listed, key=lambda x: x.price_cad or 0)
    return fmt_money(o.price, o.currency) + (f" (CAD {o.price_cad:,.2f})" if o.currency != "CAD" else "")


def channel_opportunities(chs: list[dict[str, Any]], quantity: int | None) -> list[str]:
    tips = []
    for c in chs:
        if c["quote_required"]:
            names = ", ".join(sorted({q["supplier"] for q in c["quote_required"]})[:4])
            tips.append(f"Request quotes from {names}: they don't publish prices online, and account/volume pricing "
                        "can undercut list prices.")
        if c["type"] == B2B_MARKETPLACE and (c["price_ranges"] or c["priced_count"]):
            tips.append("Wholesale marketplace listings were found. Worth considering only at volume and after "
                        "supplier verification, sample/QC and landed-cost check (see Import tab).")
        if c["bulk_signals"]:
            names = ", ".join(sorted({b["supplier"] for b in c["bulk_signals"]})[:3])
            verb = "mentions" if len({b["supplier"] for b in c["bulk_signals"]}) == 1 else "mention"
            tips.append(f"{names} {verb} bulk/volume pricing - ask for tier pricing at your quantity.")
        if c["pack_sizes"]:
            tips.append("Multi-pack listings found - compare the per-unit price (shown in the table).")
    if quantity and quantity >= 10 and not any("quote" in t.lower() for t in tips):
        tips.append(f"At {quantity} units, ask distributors for a volume quote even where list prices are shown.")
    return list(dict.fromkeys(tips))


# --------------------------------------------------------------------- gaps


def _fetch_reason(error: str | None) -> str:
    e = (error or "").lower()
    if "could not resolve" in e:
        return "host name could not be resolved (network/DNS)"
    if "could not be reached" in e:
        return "network error"
    if "robots.txt" in e:
        return "the site's robots.txt doesn't allow it"
    if "private or internal" in e or "port" in e or "only http" in e:
        return "link not allowed (safety check)"
    if "403" in e or "blocked" in e:
        return "blocked by the site"
    if "login" in e or "401" in e:
        return "login required"
    if "timed out" in e or "gave up" in e:
        return "timed out"
    if "network error" in e:
        return "network error"
    if "404" in e or "not found" in e:
        return "page not found"
    if "not an html" in e:
        return "not a web page"
    return "other HTTP error"


def gaps(offers: list[Offer], sources: list[Source], tokens: list[str], rec: dict[str, Any],
         fx_errors: dict[str, str], fetch_failures: int, fetch_attempts: int) -> list[str]:
    out = []
    priced = [o for o in offers if o.price is not None]
    if not priced:
        out.append("No published prices were found. Try a more specific name/model, or request quotes.")
    if tokens and not any(o.match_level == "exact" for o in offers):
        seen = [s for s in sources if ex.match_offer(tokens, f"{s.title} {s.snippet}").level == "exact"]
        if seen and not priced:
            out.append(f"{len(seen)} result(s) name model {', '.join(tokens)}, but none showed a usable price - "
                       "open them or request quotes.")
        elif seen:
            out.append(f"Model {', '.join(tokens)} appears in {len(seen)} result(s), but no priced listing "
                       "confirms it exactly.")
        else:
            out.append(f"No result explicitly shows model {', '.join(tokens)}. Results may be for related items.")
    if priced and all(o.price_basis == "snippet" for o in priced):
        out.append("All prices come from search snippets (not read from the supplier pages) - treat as indicative.")
    if any(o.price is not None and o.country != "CA" for o in offers):
        out.append("Some listings are from outside Canada (or unknown); their landed cost needs duty/surtax/"
                   "brokerage figures - enter assumptions in the Import tab.")
    if priced and not any(o.shipping_text for o in priced):
        out.append("No listing stated shipping cost; delivered cost could not be calculated.")
    if not any(o.warranty for o in offers):
        out.append("No warranty terms were found in the evidence.")
    review_srcs = [s for s in sources if s.type in (REVIEW, FORUM, VIDEO)]
    if not review_srcs:
        out.append("No independent review sources were found.")
    for cur, err in fx_errors.items():
        out.append(f"{err}: {cur} prices could not be converted or compared.")
    if fetch_attempts and fetch_failures:
        reasons: dict[str, int] = defaultdict(int)
        for s in sources:
            if s.fetch and not s.fetch.get("ok"):
                reasons[_fetch_reason(s.fetch.get("error"))] += 1
        detail = "; ".join(f"{n} x {r}" for r, n in sorted(reasons.items(), key=lambda kv: -kv[1]))
        out.append(f"{fetch_failures} of {fetch_attempts} supplier pages could not be read directly ({detail}); "
                   "their prices rely on search data.")
    if rec.get("pool_size", 0) == 1:
        out.append("Only one comparable listing - not enough for a meaningful comparison.")
    return out


LIMITS = [
    "Search engines don't index every supplier; many industrial distributors show prices only after login or by quote.",
    "Prices change frequently. Every price shows when and where it was observed.",
    "Equivalence is checked by matching model numbers in listing text; always confirm specs, kit contents and "
    "certifications before buying.",
    "Customer ratings come from different sites and populations; they are shown separately, never averaged.",
    "Nothing here is a quote. Taxes, duties and shipping must be confirmed with the supplier or your broker.",
]
