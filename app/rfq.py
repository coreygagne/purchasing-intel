"""Request-for-quote drafts for suppliers that quote on request or showed no price.

Drafts only: nothing is sent. The buyer copies a draft or opens it in their own email program. Contact
details come from the supplier record (each with its source); a supplier with no email gets a draft for a
phone call or their web form instead.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from . import discovery as disc
from . import guides

MAX_DRAFTS = 8
SKIP_TYPES = {"marketplace", "business directory", "auction / surplus", "property listings", "classifieds / used"}


def rfq_drafts(vendors: list[dict[str, Any]], identity: dict[str, Any], quantity: int | None,
               order_length: dict[str, Any] | None, answers: dict[str, Any] | None,
               compliance: list[dict[str, str]] | None, category: str | None) -> list[dict[str, Any]]:
    answers = answers or {}
    item = identity.get("name") or identity.get("input") or "the item"
    specs = [s["label"] for s in identity.get("specs") or []] or list(identity.get("key_specs") or [])[:5]
    if order_length:
        qty = order_length["text"]
    elif quantity:
        qty = f"{quantity} unit(s)"
    elif answers.get("quantity"):
        qty = str(answers["quantity"])
    else:
        qty = "please quote your standard unit / pack size"
    needed_by = answers.get("needed_by")
    use = answers.get("intended_use")
    reqs = guides.requirements(identity.get("name") or "", answers)
    guide = guides.match(identity.get("name") or "")
    cert = _cert_line(category)
    targets = [v for v in vendors if v["quote_opportunity"] and v["type"] not in SKIP_TYPES]
    drafts = []
    for v in targets[:MAX_DRAFTS]:
        email = v["emails"][0] if v["emails"] else None
        phone = v["phones"][0] if v["phones"] else None
        lines = [f"Hello {v['name']} team,", "",
                 f"{disc.HOME['company']} in {disc.HOME['city']}, Ontario is requesting a quote for:", "",
                 f"  Item: {item}"]
        if specs:
            lines.append(f"  Specifications: {', '.join(specs)}")
        lines.append(f"  Quantity: {qty}")
        lines.append(f"  Delivery: to {disc.HOME['city']}, ON" + (f", needed by {needed_by}" if needed_by else ""))
        if use:
            lines.append(f"  Intended use: {use}")
        lines += [f"  {r}" for r in reqs]
        lines += ["", "Please include:",
                  "  - unit price and total in CAD, before tax",
                  "  - any trade, contractor or volume pricing, and the minimum order",
                  f"  - delivery cost to {disc.HOME['city']} and lead time, and whether it is in stock",
                  "  - warranty terms"]
        if cert:
            lines.append(f"  - {cert}")
        if guide:
            lines += ["", "Please also confirm:"] + [f"  - {c}" for c in guide[0]["checklist"]]
        lines += ["", "Thank you,", "[Your name]", disc.HOME["company"], "[Phone]"]
        subject = f"Request for quote: {item}"[:150]
        body = "\n".join(lines)
        drafts.append({
            "vendor_id": v["id"], "vendor": v["name"], "tier": v["tier_label"], "reasons": v["quote_reasons"],
            "to": email["value"] if email else None, "to_basis": email["basis"] if email else None,
            "phone": phone["value"] if phone else None, "phone_basis": phone["basis"] if phone else None,
            "website": v["website"], "subject": subject, "body": body,
            "mailto": (f"mailto:{email['value']}?subject={quote(subject)}&body={quote(body)}" if email else None),
            "how": "email" if email else ("phone" if phone else "website contact form"),
        })
    return drafts


def _cert_line(category: str | None) -> str | None:
    return {"electrical": "the certification marks and CSA standard (e.g. CSA/cUL, cable rating)",
            "ppe": "the CSA / NIOSH certification for the item",
            "tools": "the Canadian electrical safety mark (CSA, cUL or cETL) for powered tools",
            "electronics": "ISED certification (IC number) and electrical safety mark",
            "parts": "the CRN, where pressure-rated parts need one",
            "consumables": "Safety Data Sheets (WHMIS) for hazardous products",
            "machinery": "manuals, inspection records and certification",
            "vehicle": "the vehicle history, inspection and recall status"}.get(category or "")
