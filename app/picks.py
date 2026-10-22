"""The recommendation, told plainly: the best-supported option first, then picks by channel (local, wholesale,
used/auction, international) only where the evidence supports one, a side-by-side comparison, and what quote
or information is still needed.

Every figure comes from the offers and their order totals; a pick is never made from a price that wasn't
observed.
"""

from __future__ import annotations

from typing import Any

from .analysis import fmt_money
from .evidence import Offer
from .market import order_totals
from .suppliers import B2B_MARKETPLACE, DISTRIBUTOR, MANUFACTURER

TRADE = {DISTRIBUTOR, MANUFACTURER, B2B_MARKETPLACE}
PICK_LABELS = {"local": "Best local (Thunder Bay) option", "wholesale": "Best trade / wholesale option",
               "used": "Best used or auction option", "international": "Best option from outside Canada"}


def _vendor_index(vendors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {oid: v for v in vendors for oid in v["offer_ids"]}


def _same_item(o: Offer, tokens: list[str]) -> bool:
    if o.superseded() or o.spec_conflicts or o.price_cad is None or o.price_type != "listed":
        return False
    return o.match_level in ("exact", "equivalent") if tokens else o.match_level not in ("different", "compatible")


def _row(o: Offer, vendor: dict[str, Any] | None, labels: list[str], quantity: int | None,
         order_length: dict[str, Any] | None, home_province: str,
         assumptions: dict[str, float | None] | None = None) -> dict[str, Any]:
    totals = order_totals(o, quantity, order_length, home_province, assumptions)
    specs = ("states " + ", ".join(o.spec_confirmed) if o.spec_confirmed else "") + (
        ("; doesn't state " + ", ".join(o.spec_missing)) if o.spec_missing else "")
    risks = []
    if o.country != "CA":
        risks.append("import: duty, surtax, brokerage and longer delivery possible")
    if o.confidence == "low":
        risks.append("price only seen in a search snippet or results page")
    if o.condition and o.condition != "new":
        risks.append(f"{o.condition}: usually limited or no warranty")
    if o.supplier_type in ("marketplace", "classifieds / used", "auction / surplus"):
        risks.append("third-party seller")
    if o.price_kind == "current_bid":
        risks.append("auction in progress: final price will be higher, plus buyer's fees")
    return {
        "offer_id": o.id, "labels": labels, "supplier": o.supplier, "url": o.url,
        "tier": vendor["tier_label"] if vendor else None,
        "price": fmt_money(o.price, o.currency) if o.price is not None else None,
        "compare_value": o.compare_value,
        "total_pre_tax": totals["pre_tax_total"] if totals else None,
        "total_with_tax": totals["total_with_tax"] if totals else None,
        "total_complete": totals["complete"] if totals else False,
        "total_unknown": totals["unknown"] if totals else [],
        "evidence": o.price_label, "confidence": o.confidence, "observed_at": o.observed_at,
        "delivery": o.shipping_text or "not stated", "availability": o.availability or "not stated",
        "warranty": o.warranty or "not stated",
        "compatibility": {"exact": "model number matches", "unverified": "match not verified",
                          "variant": "variant - check suffix"}.get(o.match_level, o.match_level) +
                         (f" ({specs})" if specs else ""),
        "risks": risks,
    }


def recommend_plainly(offers: list[Offer], vendors: list[dict[str, Any]], rec: dict[str, Any], tokens: list[str],
                      quantity: int | None, order_length: dict[str, Any] | None, home_province: str,
                      used_ok: bool = True, assumptions: dict[str, float | None] | None = None) -> dict[str, Any]:
    by_id = {o.id: o for o in offers}
    vendor_of = _vendor_index(vendors)
    comparable = [o for o in offers if o.comparable and o.compare_value is not None
                  and not any(f.startswith("Not recommended") for f in o.flags)]
    best = by_id.get((rec.get("best_value") or {}).get("offer_id", ""))
    lowest = by_id.get((rec.get("lowest") or {}).get("offer_id", ""))

    picks: dict[str, Offer] = {}
    local = [o for o in comparable if (vendor_of.get(o.id) or {}).get("tier") == "local"]
    if local:
        picks["local"] = min(local, key=lambda o: o.compare_value)
    trade = [o for o in comparable if o.supplier_type in TRADE or (vendor_of.get(o.id) or {}).get("sells_trade")]
    if trade:
        picks["wholesale"] = min(trade, key=lambda o: o.compare_value)
    if used_ok:
        used = [o for o in offers if _same_item(o, tokens) and o.compare_value is not None
                and o.price_kind != "completed_sale"
                and ((o.condition and o.condition != "new") or o.price_kind == "current_bid")]
        if used:
            picks["used"] = min(used, key=lambda o: o.compare_value)
    intl = [o for o in comparable if o.country != "CA"]
    if intl:
        picks["international"] = min(intl, key=lambda o: o.compare_value)

    # one row per offer, carrying every label it earned
    rows: dict[str, dict[str, Any]] = {}
    for label, o in [("Best overall value", best), ("Lowest comparable cost", lowest)] + [
            (PICK_LABELS[k], o) for k, o in picks.items()]:
        if o is None:
            continue
        if o.id in rows:
            rows[o.id]["labels"].append(label)
        else:
            rows[o.id] = _row(o, vendor_of.get(o.id), [label], quantity, order_length, home_province, assumptions)

    pick_notes = []
    if "used" in picks:
        pick_notes.append("The used/auction pick isn't compared with new items: condition, warranty and fees "
                          "differ. Inspect before buying.")
    if "international" in picks:
        p = picks["international"]
        if not (p.delivered or {}).get("complete"):
            pick_notes.append(f"The international pick ({p.supplier}) has an incomplete landed cost - freight, duty, "
                              "surtax or brokerage are unknown (see Import).")
    missing = []
    if "local" not in picks:
        local_vendors = [v for v in vendors if v["tier"] == "local"]
        missing.append({"kind": "local", "text": ("No Thunder Bay supplier showed a comparable price" +
                                                  (": ask " + ", ".join(v["name"] for v in local_vendors[:3]) +
                                                   " for a quote." if local_vendors else "."))})
    if "wholesale" not in picks:
        missing.append({"kind": "wholesale", "text": "No published trade/wholesale price for the same item: ask "
                                                     "distributors for account or volume pricing."})

    lead = None
    if best is not None:
        row = rows[best.id]
        why = [f"{best.supplier}: {row['price']}" + (f", CAD {row['total_pre_tax']:,.2f} before tax for "
                                                     f"{_qty_text(quantity, order_length)}" if row["total_pre_tax"]
                                                     else "") + f" ({best.price_label.lower()})."]
        if lowest is not None and lowest.id != best.id and lowest.compare_value and best.compare_value:
            diff = best.compare_value - lowest.compare_value
            why.append(f"{fmt_money(diff, 'CAD')} ({diff / lowest.compare_value * 100:.0f}%) more per "
                       f"{'foot' if best.per_ft_cad is not None else 'unit'} than the lowest comparable price "
                       f"({lowest.supplier}), for: " + ", ".join(
                           x for x in _advantages(best, lowest)) + "." if _advantages(best, lowest) else
                       f"{fmt_money(diff, 'CAD')} more than the lowest comparable price ({lowest.supplier}).")
        elif lowest is not None and lowest.id == best.id:
            why.append("It is also the lowest comparable price.")
        why += [f"Delivery: {row['delivery']}. Warranty: {row['warranty']}. Compatibility: {row['compatibility']}."]
        if row["risks"]:
            why.append("Risks: " + "; ".join(row["risks"]) + ".")
        lead = {"offer_id": best.id, "supplier": best.supplier, "url": best.url, "why": why}

    needed = _needed(rec, lowest, best, vendors, rows, order_length)
    return {"lead": lead, "picks": {k: o.id for k, o in picks.items()}, "comparison": list(rows.values()),
            "pick_notes": pick_notes, "missing_picks": missing, "needed": needed,
            "distinction": "Best overall value weighs price with evidence, supplier, domestic supply, delivery, "
                           "warranty and ratings; lowest comparable cost is the cheapest same-item price."}


def _qty_text(quantity: int | None, order_length: dict[str, Any] | None) -> str:
    if order_length:
        return order_length["text"]
    return f"{quantity} unit(s)" if quantity else "one listing"


def _advantages(best: Offer, other: Offer) -> list[str]:
    out = []
    if best.confidence in ("high", "medium") and other.confidence == "low":
        out.append("stronger price evidence")
    if best.country == "CA" and other.country != "CA":
        out.append("domestic supply")
    if best.warranty and not other.warranty:
        out.append("stated warranty")
    if best.shipping_text and not other.shipping_text:
        out.append("stated shipping")
    if best.supplier_type in TRADE and other.supplier_type not in TRADE:
        out.append("trade supplier")
    if best.availability and "in stock" in best.availability and not (other.availability or "").count("in stock"):
        out.append("in stock")
    return out


def _needed(rec: dict[str, Any], lowest: Offer | None, best: Offer | None, vendors: list[dict[str, Any]],
            rows: dict[str, dict[str, Any]], order_length: dict[str, Any] | None) -> list[str]:
    out = []
    if lowest is None:
        # suppliers that list this item first (they quote on request), then local supply houses, then the rest
        ranked = sorted((v for v in vendors if v["quote_opportunity"]),
                        key=lambda v: (not v.get("lists_item"), v["tier"] != "local",
                                       v.get("business_kind") != "seller"))
        targets = [v["name"] for v in ranked][:4]
        first = next((v for v in ranked if v.get("lists_item") and v["tier"] == "local"), None) or \
            next((v for v in ranked if v.get("lists_item")), None)
        if first:
            phone = first["phones"][0]["value"] if first["phones"] else None
            email = first["emails"][0]["value"] if first["emails"] else None
            how = f" - call {phone}" if phone else (f" - email {email}" if email else "")
            out.append(f"Best first call: {first['name']} ({first['tier_label']}) lists this item"
                       + (f" (\"{first['products'][0]}\")" if first["products"] else "")
                       + f" and {'quotes on request' if first['price_status'] == 'quote_required' else 'shows no price'}"
                       f"{how}.")
        out.append("Not enough price evidence to recommend a supplier. Request quotes" +
                   (f" from {', '.join(targets)}" if targets else "") + " (drafts in the Suppliers tab).")
    for o in [x for x in (lowest, best) if x is not None]:
        r = rows.get(o.id)
        if o.confidence == "low":
            out.append(f"Confirm the price on {o.supplier}'s own page: it was only seen in a search snippet.")
        if r and r["total_unknown"]:
            out.append(f"Ask {o.supplier} for: {', '.join(r['total_unknown'])} to Thunder Bay.")
    if order_length and lowest is not None:
        out.append(f"Confirm each supplier can cut or supply {order_length['text']} and the reel/cut charges.")
    return list(dict.fromkeys(out))
