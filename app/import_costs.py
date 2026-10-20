"""Canadian import considerations and delivered / landed cost estimates.

Rules of the road:
* Only arithmetic on observed prices and the user's own stated assumptions.
* Duty and surtax rates depend on tariff classification and the goods'
  country of ORIGIN (where made), which search results rarely establish, so
  they are never assumed - the user enters them or they stay "unknown".
* Every component carries a basis label: quoted, calculated, assumption,
  rate (published tax rate), or unknown.
"""

from __future__ import annotations

from typing import Any

GUIDANCE_REVIEWED = "2026-10-20"

LINKS = {
    "customs_tariff": "https://www.cbsa-asfc.gc.ca/trade-commerce/tariff-tarif/menu-eng.html",
    "customs_notices": "https://www.cbsa-asfc.gc.ca/publications/cn-ad/menu-eng.html",
    "import_guide": "https://www.cbsa-asfc.gc.ca/import/guide-eng.html",
    "cusma_low_value": "https://www.cbsa-asfc.gc.ca/services/cusma-aceum/lvs-efv-eng.html",
    "us_surtax_order_2026": "https://gazette.gc.ca/rp-pr/p2/2026/2026-09-23/html/sor-dors186-eng.html",
    "hst_imports_memo": "https://cbsa-asfc.gc.ca/publications/dm-md/d17/d17-1-22-eng.html",
    "recalls": "https://recalls-rappels.canada.ca/en",
}

GST_RATE = 0.05  # federal GST on imports, assessed on (value for duty + duties)
HST_RATES = {"ON": 0.13, "NS": 0.14, "NB": 0.15, "NL": 0.15, "PE": 0.15}

DEFAULT_ASSUMPTIONS: dict[str, float | None] = {
    "intl_shipping_cad": None,   # freight to Thunder Bay for an international order
    "domestic_shipping_cad": None,
    "duty_pct": None,
    "surtax_pct": None,
    "brokerage_cad": None,
}


def clean_assumptions(raw: dict[str, Any] | None) -> dict[str, float | None]:
    out = dict(DEFAULT_ASSUMPTIONS)
    for key in out:
        val = (raw or {}).get(key)
        if val in (None, ""):
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue
        if num < 0 or (key.endswith("_pct") and num > 300):
            continue
        out[key] = num
    return out


def general_notes(home_province: str) -> list[dict[str, str]]:
    hst = HST_RATES.get(home_province)
    tax_note = (f"Domestic purchases in {home_province} carry {hst * 100:.0f}% HST" if hst
                else f"Domestic purchases carry GST plus applicable {home_province} sales tax")
    return [
        {"topic": "Prices compared before tax",
         "text": f"{tax_note}. Comparisons here are pre-tax; GST/HST paid by a registered business is generally "
                 "recoverable as an input tax credit - confirm with accounting.", "basis": "rule"},
        {"topic": "Origin decides duty, not seller location",
         "text": "Customs duty, CUSMA (duty-free) eligibility and surtaxes depend on the goods' country of origin "
                 "(where made) and tariff classification (HS code). A US or Canadian seller can still ship goods made "
                 "elsewhere.", "basis": "rule", "link": LINKS["customs_tariff"]},
        {"topic": "Surtaxes on US-origin goods (since 2026-09-08)",
         "text": "Canada applies surtaxes of 15%, 25% or 50% (by tariff classification) to many US-origin goods, "
                 "including 50% on most covered steel and aluminum products (United States Surtax Order (2026); "
                 "CBSA Customs Notices 26-23 and 25-11). Check whether this item's classification is listed before "
                 "buying from the US.", "basis": "rule", "link": LINKS["us_surtax_order_2026"]},
        {"topic": "Other origins",
         "text": "Surtaxes or quota measures also apply to some goods from other origins (for example certain steel "
                 "and aluminum products). Check current CBSA customs notices for the item's classification.",
         "basis": "rule", "link": LINKS["customs_notices"]},
        {"topic": "GST at the border",
         "text": "CBSA assesses 5% GST on imports (on value plus duties/surtaxes). For commercial goods imported by "
                 "an HST registrant into Ontario, the provincial part generally isn't collected at the border but "
                 "self-assessment rules may apply.", "basis": "rule", "link": LINKS["hst_imports_memo"]},
        {"topic": "Brokerage and courier fees",
         "text": "Couriers and customs brokers usually charge per-shipment clearance fees that vary by carrier and "
                 "value. They are not included unless you enter an amount.", "basis": "rule",
         "link": LINKS["import_guide"]},
        {"topic": "Guidance date",
         "text": f"Import guidance text last reviewed {GUIDANCE_REVIEWED}. Trade measures change often - "
                 "verify current rates with CBSA or your customs broker before relying on them.", "basis": "rule"},
    ]


def _component(label: str, value: float | None, basis: str, note: str = "") -> dict[str, Any]:
    return {"label": label, "value": None if value is None else round(value, 2), "basis": basis, "note": note}


def delivered_estimate(offer: dict[str, Any], assumptions: dict[str, float | None],
                       quantity: int | None = None) -> dict[str, Any] | None:
    """Delivered (domestic) or landed (international) cost in CAD for one order.

    The order is one listing, or enough listings/packs to cover `quantity`.
    Shipping and brokerage are counted once per order. Returns None when the
    listing has no CAD-convertible price.
    """
    price_cad = offer.get("price_cad")
    if price_cad is None:
        return None
    domestic = offer.get("country") == "CA"
    pack_qty = int(offer["pack_qty"]) if offer.get("pack_qty") else None
    notes: list[str] = []
    packs = 1
    if quantity:
        per_listing = pack_qty or 1
        packs = -(-quantity // per_listing)  # ceiling division
        if not pack_qty:
            notes.append("Assumes each listing is one unit (pack size not stated).")
    goods = price_cad * packs
    goods_note = "" if offer.get("currency") == "CAD" else f"converted from {offer.get('currency')}"
    if packs > 1:
        goods_note = (goods_note + "; " if goods_note else "") + f"{packs} x {price_cad:,.2f}"
    comps = [_component("Goods (CAD)", goods,
                        "quoted" if offer.get("currency") == "CAD" and packs == 1 else "calculated", goods_note)]
    missing: list[str] = []

    ship = offer.get("shipping_cost")
    ship_applies = ship is not None and (domestic or offer.get("shipping_scope") == "canada")
    if ship is not None and not ship_applies:
        notes.append(f"The listing says \"{offer.get('shipping_text')}\", but that may not apply to shipping to "
                     "Canada, so it isn't used.")
    if ship_applies:
        converted = offer.get("currency") not in (None, "CAD")
        ship_cad = ship * (offer.get("fx_rate") or 1.0)
        comps.append(_component("Shipping", ship_cad, "calculated" if converted and ship else "quoted",
                                (offer.get("shipping_text") or "") + (f" (converted from {offer.get('currency')})"
                                                                      if converted and ship else "")))
        if packs > 1:
            notes.append("Quoted shipping is for one listing; larger orders may differ.")
    else:
        key = "domestic_shipping_cad" if domestic else "intl_shipping_cad"
        if assumptions.get(key) is not None:
            ship_cad = assumptions[key]
            comps.append(_component("Shipping", ship_cad, "assumption", "your assumption"))
        else:
            ship_cad = None
            missing.append("shipping")

    duty = surtax = brokerage = None
    if not domestic:
        if offer.get("country") is None:
            notes.append("Seller country unknown - treated as a possible import.")
        duty_pct, surtax_pct = assumptions.get("duty_pct"), assumptions.get("surtax_pct")
        duty = goods * duty_pct / 100 if duty_pct is not None else None
        surtax = goods * surtax_pct / 100 if surtax_pct is not None else None
        comps.append(_component("Customs duty", duty, "assumption" if duty is not None else "unknown",
                                f"{duty_pct:g}% (your assumption)" if duty_pct is not None
                                else "depends on HS code and origin"))
        comps.append(_component("Surtax", surtax, "assumption" if surtax is not None else "unknown",
                                f"{surtax_pct:g}% (your assumption)" if surtax_pct is not None
                                else "check CBSA notices for this classification"))
        if duty is None:
            missing.append("duty")
        if surtax is None:
            missing.append("surtax")
        brokerage = assumptions.get("brokerage_cad")
        comps.append(_component("Brokerage / clearance", brokerage,
                                "assumption" if brokerage is not None else "unknown"))
        if brokerage is None:
            missing.append("brokerage")
        gst_base = goods + (duty or 0) + (surtax or 0)
        comps.append(_component("GST at border (5%)", gst_base * GST_RATE, "rate",
                                "generally recoverable for GST/HST registrants; not added to total"))

    total = goods + (ship_cad or 0) + (duty or 0) + (surtax or 0) + (brokerage or 0)
    units = packs * (pack_qty or 1)
    label = "estimated" if any(c["basis"] == "assumption" for c in comps) else "calculated"
    return {
        "value": round(total, 2),
        "per_unit": round(total / units, 2) if units else None,
        "units": units,
        "label": label,
        "complete": not missing,
        "missing": missing,
        "components": comps,
        "notes": notes,
        "kind": "delivered" if domestic else "landed",
    }
