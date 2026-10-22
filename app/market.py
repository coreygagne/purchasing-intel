"""Market value: what this item sells for, from the prices actually observed.

Prices are grouped so unlike things are never mixed: new asking prices from retailers and marketplaces, published
trade/wholesale prices (distributors, manufacturers, B2B), used asking prices, auction bids in progress and
completed sales. Each group shows how many observations it rests on, low / median / high (median only from three
observations), the dates and the sources, and what differs between the listings. Every figure is calculated from
the listed observations; nothing is estimated from outside them.

Order totals show the unit price and the total for the quantity asked for, with shipping, import costs and tax
labelled as quoted, calculated, your assumption or unknown.
"""

from __future__ import annotations

import statistics
from typing import Any

from .evidence import Offer
from .import_costs import GST_RATE, HST_RATES, delivered_estimate
from .suppliers import B2B_MARKETPLACE, DISTRIBUTOR, MANUFACTURER

TRADE = {DISTRIBUTOR, MANUFACTURER, B2B_MARKETPLACE}
GROUPS = [
    ("new_retail", "New - retail and marketplace asking prices"),
    ("new_trade", "New - published trade / wholesale prices (distributors, manufacturers, B2B)"),
    ("used", "Used or refurbished - asking prices"),
    ("unstated", "Condition not stated - asking prices (classifieds, dealers, auctions)"),
    ("current_bids", "Auctions in progress - current bids (final prices will be higher)"),
    ("completed_sales", "Completed sales - what items sold for"),
]
MIN_FOR_MEDIAN = 3


def _same_item(o: Offer, tokens: list[str]) -> bool:
    if o.superseded() or o.spec_conflicts:
        return False
    if tokens:
        return o.match_level in ("exact", "equivalent")
    return o.match_level not in ("different", "compatible")


def _set_aside(o: Offer) -> bool:
    return any(f.startswith("Not recommended: priced far below") for f in o.flags)


_AD_TYPES = {"classifieds / used", "auction / surplus"}


def _group(o: Offer, category: str | None = None) -> str:
    if o.price_kind == "completed_sale":
        return "completed_sales"
    if o.price_kind == "current_bid":
        return "current_bids"
    if o.condition and o.condition != "new":
        return "used"
    if not o.condition and (o.supplier_type in _AD_TYPES or category in ("vehicle", "machinery", "property")):
        # an ad or a vehicle/equipment listing that doesn't say: never assumed to be new
        return "unstated"
    if o.supplier_type in TRADE or o.moq:
        return "new_trade"
    return "new_retail"


def _basis(eligible: list[Offer], order_length: dict[str, Any] | None) -> tuple[str, str]:
    """('per_ft' | 'per_unit' | 'listing', label) used for every group, so groups compare on one basis."""
    per_len = [o for o in eligible if o.per_ft_cad is not None]
    if order_length or (per_len and len(per_len) * 2 >= len(eligible)):
        return "per_ft", "CAD per foot"
    stated = [o for o in eligible if o.pack_qty and not o.per_length]
    if len(stated) >= 2:
        return "per_unit", "CAD per unit (listings that don't state a pack size left out)"
    return "listing", "CAD per listing"


def _value(o: Offer, basis: str) -> float | None:
    if basis == "per_ft":
        return o.per_ft_cad
    if o.per_length:
        return None  # a per-foot price can't sit with per-item prices
    if basis == "per_unit":
        # a listing without a pack size can't be put per unit: "$4.99" may be one glove or a box of 100
        return round(o.price_cad / o.pack_qty, 4) if o.pack_qty and o.price_cad is not None else None
    return o.price_cad


def market_value(offers: list[Offer], tokens: list[str], order_length: dict[str, Any] | None = None,
                 category: str | None = None) -> dict[str, Any]:
    eligible = [o for o in offers if o.price_cad is not None and o.price_type == "listed" and _same_item(o, tokens)]
    basis, basis_label = _basis(eligible, order_length)
    groups = []
    for key, label in GROUPS:
        members = [(o, _value(o, basis)) for o in eligible if _group(o, category) == key]
        members = [(o, v) for o, v in members if v is not None]
        aside = [o for o, _ in members if _set_aside(o)]
        used = [(o, v) for o, v in members if not _set_aside(o)]
        if not members:
            continue
        vals = sorted(v for _, v in used)
        dates = sorted(o.observed_at[:10] for o, _ in used if o.observed_at)
        groups.append({
            "key": key, "label": label, "count": len(used),
            "low": vals[0] if vals else None, "high": vals[-1] if vals else None,
            "median": round(statistics.median(vals), 4) if len(vals) >= MIN_FOR_MEDIAN else None,
            "median_note": None if len(vals) >= MIN_FOR_MEDIAN else
            f"median not shown: fewer than {MIN_FOR_MEDIAN} observations",
            "first_seen": dates[0] if dates else None, "last_seen": dates[-1] if dates else None,
            "observations": [{"offer_id": o.id, "supplier": o.supplier, "value": v, "price": o.price,
                              "currency": o.currency, "price_label": o.price_label, "confidence": o.confidence,
                              "observed_at": o.observed_at, "url": o.url, "country": o.country,
                              "condition": o.condition} for o, v in sorted(used, key=lambda t: t[1])],
            "set_aside": [{"offer_id": o.id, "supplier": o.supplier, "price": o.price, "currency": o.currency,
                           "reason": "priced far below the other listings - likely a different size, variant or "
                                     "unit"} for o in aside],
            "differences": _differences([o for o, _ in used]),
        })
    ranges = [o for o in offers if o.price_type == "range" and o.price is not None and _same_item(o, tokens)]
    new = [g for g in groups if g["key"] in ("new_retail", "new_trade")]
    new_vals = sorted(ob["value"] for g in new for ob in g["observations"])
    overall = None
    if new_vals:
        overall = {"count": len(new_vals), "low": new_vals[0], "high": new_vals[-1],
                   "median": round(statistics.median(new_vals), 4) if len(new_vals) >= MIN_FOR_MEDIAN else None,
                   "supported": len(new_vals) >= MIN_FOR_MEDIAN,
                   "note": (f"Range of {len(new_vals)} new asking prices for the same item." if len(new_vals) >=
                            MIN_FOR_MEDIAN else f"Only {len(new_vals)} new asking price(s) - too few for a market "
                            "range; treat as individual observations.")}
    notes = []
    if any(g["key"] == "completed_sales" for g in groups):
        notes.append("Completed sales are what items actually sold for; asking prices are what sellers ask. They "
                     "are shown separately.")
    if not any(g["key"] == "completed_sales" for g in groups):
        notes.append("No completed-sale prices were found (sold prices are rarely published outside auctions and "
                     "marketplaces).")
    snippet_only = sum(1 for g in groups for ob in g["observations"] if ob["confidence"] == "low")
    if snippet_only:
        notes.append(f"{snippet_only} observation(s) come from search snippets or search-results pages (low "
                     "confidence) - they may be out of date.")
    return {"basis": basis, "basis_label": basis_label, "groups": groups, "overall_new": overall,
            "indicative_ranges": [{"offer_id": o.id, "supplier": o.supplier, "low": o.price, "high": o.price_high,
                                   "currency": o.currency, "url": o.url, "observed_at": o.observed_at,
                                   "moq": o.moq} for o in ranges][:8],
            "notes": notes,
            "method": "Calculated from the observations listed; low, median and high are of the values on the basis "
                      "shown. Asking prices, current bids and completed sales are never mixed."}


def _differences(group: list[Offer]) -> list[str]:
    out = []
    if not group:
        return out
    currencies = {o.currency for o in group}
    if len(currencies) > 1:
        out.append(f"Prices in {', '.join(sorted(c for c in currencies if c))}, converted to CAD at Bank of Canada "
                   "rates.")
    countries = {o.country for o in group}
    if len(countries) > 1:
        out.append("Sellers in different countries - import costs apply to some (not included).")
    packs = {o.pack_qty for o in group}
    if len(packs) > 1:
        out.append("Pack sizes differ.")
    ship = [o for o in group if o.shipping_cost == 0]
    if ship and len(ship) < len(group):
        out.append(f"{len(ship)} of {len(group)} include free shipping; the others don't state it or charge extra.")
    conds = {o.condition for o in group if o.condition}
    if len(conds) > 1:
        out.append(f"Conditions differ: {', '.join(sorted(conds))}.")
    if any(o.spec_missing for o in group):
        out.append("Some listings don't state every requested spec.")
    return out


def order_totals(o: Offer, quantity: int | None, order_length: dict[str, Any] | None,
                 home_province: str, assumptions: dict[str, float | None] | None = None) -> dict[str, Any] | None:
    """Unit price and total for the quantity (or length) asked for, with tax shown separately.

    Pre-tax totals are what the comparison uses: GST/HST paid by a registered business is generally recoverable.
    Shipping, duty, surtax and brokerage are quoted, your assumption, or listed as unknown - never guessed.
    """
    if o.price_cad is None:
        return None
    if order_length and o.per_ft_cad is not None and o.order_total_cad is not None:
        # priced by length: the goods are the requested length; the other costs work as for any order
        d = delivered_estimate({"price_cad": o.order_total_cad, "currency": o.currency, "country": o.country,
                                "pack_qty": None, "shipping_cost": o.shipping_cost, "shipping_text": o.shipping_text,
                                "shipping_scope": o.shipping_scope, "fx_rate": o.fx_rate}, assumptions or {}, None)
        goods_label = f"Goods for {order_length['text']}"
        goods_note = f"{order_length['feet']:,.0f} ft x CAD {o.per_ft_cad:,.4f}/ft"
        unit = {"value": o.per_ft_cad, "label": "per foot", "basis": "calculated"}
        units_text = order_length["text"]
    elif o.delivered:
        d = o.delivered
        goods_label, goods_note = None, None
        goods = next((c["value"] for c in d["components"] if c["label"] == "Goods (CAD)"), None)
        unit = {"value": round(goods / d["units"], 4) if goods and d["units"] else o.price_cad,
                "label": "per unit" if (o.pack_qty or quantity) else "per listing",
                "basis": "calculated" if o.pack_qty or (quantity or 1) > 1 or o.currency != "CAD" else "quoted"}
        units_text = f"{d['units']} unit(s)" if d.get("units") else "one listing"
    else:
        return None
    lines: list[dict[str, Any]] = []
    border_gst = None
    for c in d["components"]:
        if c["label"].startswith("GST at border"):
            border_gst = c["value"]
            continue
        if c["label"] == "Goods (CAD)" and goods_label:
            lines.append({"label": goods_label, "value": c["value"], "basis": "calculated", "note": goods_note})
        else:
            lines.append({"label": c["label"], "value": c["value"], "basis": c["basis"], "note": c["note"]})
    unknown = list(d["missing"])
    shipping = next((c["value"] for c in d["components"] if c["label"] == "Shipping"), None)
    pre_tax = round(sum(l["value"] for l in lines if l["value"] is not None), 2) if lines else None
    domestic = o.country == "CA"
    rate = HST_RATES.get(home_province)
    tax_line = None
    if pre_tax is not None:
        if domestic and rate:
            tax_line = {"label": f"HST {rate * 100:.0f}% ({home_province})", "value": round(pre_tax * rate, 2),
                        "basis": "rate", "note": "generally recoverable as an input tax credit for GST/HST registrants"}
        elif domestic:
            tax_line = {"label": "GST 5% (plus provincial sales tax)", "value": round(pre_tax * GST_RATE, 2),
                        "basis": "rate", "note": "provincial sales tax not included"}
        elif border_gst is not None:
            tax_line = {"label": "GST 5% at the border", "value": border_gst, "basis": "rate",
                        "note": "on goods plus duties; the provincial part of HST may need self-assessment"}
    return {"offer_id": o.id, "supplier": o.supplier, "quantity_text": units_text, "unit": unit,
            "lines": lines, "pre_tax_total": pre_tax, "tax": tax_line,
            "total_with_tax": round(pre_tax + tax_line["value"], 2) if pre_tax is not None and tax_line else None,
            "complete": not unknown, "unknown": unknown, "minimum_order": o.moq,
            "volume_terms": o.bulk, "shipping": shipping,
            "label": "estimated" if any(l["basis"] == "assumption" for l in lines) else "calculated",
            "note": "Pre-tax totals are used for comparison. Unknown costs are not counted - confirm them with the "
                    "supplier." if unknown else "Pre-tax totals are used for comparison."}
