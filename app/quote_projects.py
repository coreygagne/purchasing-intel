"""Multi-item RFQ comparison. A supplier is comparable only for a complete, current basket."""

from __future__ import annotations

from datetime import date
from typing import Any


def evaluate(project: dict[str, Any]) -> dict[str, Any]:
    items = project.get("items") or []
    today = date.today().isoformat()
    suppliers = []
    for supplier in project.get("suppliers") or []:
        row = dict(supplier)
        lines = row.get("lines") or {}
        line_results = []
        goods = 0.0
        missing = []
        for item in items:
            offer = lines.get(item["id"]) or {}
            price = offer.get("unit_price_cad")
            extended = round(float(price) * float(item["quantity"]), 2) if price is not None else None
            if price is None:
                missing.append(item["id"])
            else:
                goods += extended
            line_results.append({"item_id": item["id"], "unit_price_cad": price,
                                 "extended_cad": extended,
                                 "part": offer.get("part") or "", "note": offer.get("note") or ""})
        issues = []
        if missing:
            issues.append(f"{len(missing)} item(s) not priced")
        if not row.get("specs_confirmed"):
            issues.append("equivalence needs confirmation")
        if row.get("valid_until") and row["valid_until"] < today:
            issues.append("price expired")
        if not row.get("valid_until"):
            issues.append("validity not stated")
        if row.get("shipping_cad") is None:
            issues.append("Thunder Bay shipping/pickup unconfirmed")
        row["line_results"] = line_results
        row["goods_cad"] = round(goods, 2)
        row["total_cad"] = round(goods + float(row["shipping_cad"]), 2) if row.get("shipping_cad") is not None and not missing else None
        row["issues"] = issues
        row["comparable"] = not issues
        suppliers.append(row)
    complete = sorted((s for s in suppliers if s["comparable"]), key=lambda s: (s["total_cad"], s["name"].lower()))
    return {**project, "suppliers": suppliers, "comparable_suppliers": complete,
            "three_current_quotes": len(complete) >= 3}


def rfq_text(project: dict[str, Any]) -> str:
    lines = [f"Subject: Request for quote - {project['title']}", "", "Hello,", "",
             f"Please quote the following items for delivery to {project.get('ship_to') or 'Thunder Bay, Ontario'}.",
             "Please list your price and manufacturer/part number for each line. Identify any substitution clearly.", ""]
    for n, item in enumerate(project.get("items") or [], 1):
        lines.append(f"{n}. {item['quantity']:g} {item['unit']} - {item['description']}" +
                     (f" (reference part: {item['part']})" if item.get("part") else ""))
    lines += ["", "Please include stock/lead time, quote expiry, and freight to Thunder Bay (or confirm free local delivery/pickup).",
              "Please state whether reel deposit, cutting charges, and any other non-tax charges apply.",
              "Please confirm cable voltage/rating, connector voltage ratings, termination and splice compatibility for the proposed parts.",
              "Prices in CAD before tax, please.", "", "Thank you."]
    return "\n".join(lines)
