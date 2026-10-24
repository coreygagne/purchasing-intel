"""Three distinct supplier prices, with delivered costs and buyer-entered replies."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .rfq import SKIP_TYPES


def supplier_key(vendor: dict[str, Any]) -> str:
    domain = (vendor.get("domain") or "").lower().removeprefix("www.").strip()
    if domain:
        return f"domain:{domain}"
    name = re.sub(r"[^a-z0-9]+", "-", (vendor.get("name") or "").lower()).strip("-")
    return f"name:{name[:120]}"


def candidate_score(vendor: dict[str, Any], profile: dict[str, Any] | None) -> tuple[int, str]:
    """Prefer approved, item-relevant suppliers with usable contact details."""
    score = 0
    if profile and profile.get("preferred"):
        score += 100
    if vendor.get("lists_item"):
        score += 45
    if vendor.get("quote_opportunity"):
        score += 20
    if vendor.get("tier") == "local":
        score += 20
    elif vendor.get("tier") in ("regional", "canada"):
        score += 10
    if vendor.get("emails") or (profile and profile.get("email")):
        score += 25
    elif vendor.get("phones") or (profile and profile.get("phone")):
        score += 18
    elif vendor.get("website"):
        score += 5
    if (vendor.get("lowest") or {}).get("comparable"):
        score += 8
    if vendor.get("business_kind") == "service":
        score -= 100
    return score, (vendor.get("name") or "").lower()


def shortlist(result: dict[str, Any], profiles: dict[str, dict[str, Any]],
              account_prices: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    drafts = {d["vendor_id"]: d for d in result.get("rfq_drafts") or []}
    candidates = []
    for v in result.get("vendors") or []:
        if v.get("type") in SKIP_TYPES or v.get("business_kind") == "service":
            continue
        key = supplier_key(v)
        profile = profiles.get(key)
        if not (v.get("emails") or v.get("phones") or v.get("website") or
                (profile and (profile.get("email") or profile.get("phone")))):
            continue
        score, _ = candidate_score(v, profile)
        candidates.append({"key": key, "vendor": v, "profile": profile, "account_price": account_prices.get(key),
                           "draft": drafts.get(v.get("id")), "score": score})
    candidates.sort(key=lambda c: (-c["score"], c["vendor"]["name"].lower()))
    unique = {}
    for candidate in candidates:
        unique.setdefault(candidate["key"], candidate)
    return list(unique.values())


def quote_totals(quote: dict[str, Any], needed_quantity: int | None) -> dict[str, Any]:
    q = dict(quote)
    q["total_cad"] = None
    issues: list[str] = []
    if q["status"] != "received":
        return {**q, "comparable": False, "issues": issues}
    if q.get("unit_price") is None or q.get("quantity") is None:
        issues.append("price or quantity missing")
    if needed_quantity and q.get("quantity") != needed_quantity:
        issues.append(f"quantity differs from the requested {needed_quantity}")
    if not q.get("specs_confirmed"):
        issues.append("item and specifications not confirmed")
    if q.get("shipping_cad") is None:
        issues.append("shipping cost or pickup not confirmed")
    if q.get("valid_until") and q["valid_until"] < date.today().isoformat():
        issues.append("quote expired")
    rate = q.get("fx_rate_to_cad")
    if q.get("currency") != "CAD" and (rate is None or rate <= 0):
        issues.append("CAD conversion rate missing")
    if q.get("unit_price") is not None and q.get("quantity") is not None and (
        q.get("currency") == "CAD" or rate is not None and rate > 0
    ):
        subtotal = q["unit_price"] * q["quantity"] * (1 if q["currency"] == "CAD" else rate)
        q["total_cad"] = round(subtotal + (q.get("shipping_cad") or 0) + (q.get("other_cad") or 0), 2)
    q["comparable"] = not issues
    q["issues"] = issues
    return q


def published_prices(result: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One recent, comparable published asking price per supplier, with its original source."""
    offers = {o["id"]: o for o in result.get("offers") or []}
    prices: dict[str, dict[str, Any]] = {}
    for vendor in result.get("vendors") or []:
        if vendor.get("type") in SKIP_TYPES or vendor.get("business_kind") == "service":
            continue
        eligible = [offers[oid] for oid in vendor.get("offer_ids") or [] if oid in offers
                    and offers[oid].get("comparable") and offers[oid].get("price_cad") is not None
                    and offers[oid].get("price_basis") in ("structured_data", "shopping_api", "llm_verified")
                    and offers[oid].get("confidence") in ("high", "medium")
                    and offers[oid].get("price_kind") == "asking"
                    and offers[oid].get("price_type") == "listed"]
        if not eligible:
            continue
        def cost(o: dict[str, Any]) -> tuple[int, float]:
            delivered = o.get("delivered") or {}
            ship = next((c for c in delivered.get("components", []) if c.get("label") == "Shipping"), None)
            quantity_shipping_unconfirmed = any("larger orders may differ" in note for note in delivered.get("notes", []))
            ready = bool(delivered.get("complete") and ship and ship.get("basis") != "assumption"
                         and not any(c.get("basis") == "assumption" for c in delivered.get("components", []))
                         and not quantity_shipping_unconfirmed)
            return (0 if ready else 1, delivered.get("value") or o.get("compare_value") or o["price_cad"])

        offer = min(eligible, key=cost)
        key = supplier_key(vendor)
        delivered = offer.get("delivered") or {}
        shipping = next((c for c in delivered.get("components", []) if c.get("label") == "Shipping"), None)
        quantity_shipping_unconfirmed = any("larger orders may differ" in note for note in delivered.get("notes", []))
        ready = bool(delivered.get("complete") and shipping and shipping.get("basis") != "assumption"
                     and not any(c.get("basis") == "assumption" for c in delivered.get("components", []))
                     and not quantity_shipping_unconfirmed)
        row = {"kind": "published", "supplier_key": key, "supplier_name": vendor["name"],
                       "price_cad": offer["price_cad"], "price": offer.get("price"),
                       "currency": offer.get("currency"),
                       "comparison_value_cad": delivered.get("value") if ready else None,
                       "goods_and_known_costs_cad": delivered.get("value"),
                       "shipping_cad": shipping.get("value") if shipping and shipping.get("basis") != "assumption" else None,
                       "delivered_ready": ready,
                       "missing_costs": list(delivered.get("missing") or []) + (
                           ["shipping for requested quantity"] if quantity_shipping_unconfirmed else
                           ["shipping"] if not shipping or shipping.get("basis") == "assumption" else []) +
                           (["assumed import/delivery charges"] if any(
                               c.get("basis") == "assumption" and c.get("label") != "Shipping"
                               for c in delivered.get("components", [])) else []),
                       "price_label": offer.get("price_label"), "url": offer.get("url"),
                       "observed_at": offer.get("observed_at"), "vendor": vendor,
                       "profile": profiles.get(key)}
        if key not in prices or (0 if ready else 1, row["goods_and_known_costs_cad"] or 1e18) < (
                0 if prices[key]["delivered_ready"] else 1, prices[key]["goods_and_known_costs_cad"] or 1e18):
            prices[key] = row
    return sorted(prices.values(), key=lambda p: (0 if p["delivered_ready"] else 1,
                                                  p["comparison_value_cad"] if p["delivered_ready"] else p["price_cad"],
                                                  p["supplier_name"].lower()))


def workflow(result: dict[str, Any], quotes: list[dict[str, Any]],
             profiles: dict[str, dict[str, Any]], watch: dict[str, Any] | None,
             account_prices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    evaluated = [quote_totals(q, result.get("quantity")) for q in quotes]
    received = [q for q in evaluated if q["status"] == "received"]
    comparable = [q for q in received if q["comparable"]]
    comparable.sort(key=lambda q: (q["total_cad"], q["supplier_name"].lower()))
    published = published_prices(result, profiles)
    received_keys = {q["supplier_key"] for q in comparable}
    documented = ([{"kind": "supplier_quote", "comparison_value_cad": q["total_cad"],
                    "delivered_ready": True, **q} for q in comparable] +
                  [p for p in published if p["supplier_key"] not in received_keys])
    documented.sort(key=lambda p: (0 if p.get("delivered_ready") else 1,
                                   p.get("comparison_value_cad") if p.get("delivered_ready") else p.get("price_cad", 1e18),
                                   p["supplier_name"].lower()))
    ready_count = sum(bool(p.get("delivered_ready")) for p in documented)
    checks = []
    if not result.get("quantity"):
        checks.append("Set the quantity to compare three supplier responses on the same basis.")
    if not result.get("identity", {}).get("model_tokens"):
        checks.append("Confirm the exact model or specifications with each supplier.")
    if len(documented) < 3:
        checks.append(f"Find or record {3 - len(documented)} more comparable price option(s).")
    if ready_count < 3:
        checks.append(f"Confirm shipping to Thunder Bay for {min(3, len(documented)) - min(ready_count, 3)} option(s) before comparing delivered totals.")
    return {
        "candidates": shortlist(result, profiles, account_prices), "quotes": evaluated,
        "profiles": profiles, "account_prices": account_prices,
        "best_quotes": comparable[:3], "published_prices": published,
        "best_options": documented[:3], "received_count": len(received),
        "comparable_count": len(comparable), "documented_count": len(documented),
        "delivered_ready_count": ready_count,
        "three_prices_found": len(documented) >= 3,
        "checks": checks, "watch": watch,
    }
