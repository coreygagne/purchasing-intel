"""What this research covered: channels and markets searched, what each found, what couldn't be reached.

A report on the searches that ran, not a claim about the whole market: search engines don't index every
supplier, and many trade prices are only given on request. No completeness percentage is calculated.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import discovery as disc
from .analysis import _fetch_reason
from .evidence import Offer, Source, is_seller_source

VERIFIED_BASES = {"structured_data", "shopping_api", "llm_verified"}
DISCLAIMER = ("This shows what the searches found, not every supplier or sale that exists: search engines don't "
              "index everything, many distributors show prices only to account holders or by quote, and a source "
              "that couldn't be reached may still have the item.")


def coverage_report(meta: dict[str, Any], sources: list[Source], offers: list[Offer], vendors: list[dict[str, Any]],
                    market: dict[str, Any]) -> dict[str, Any]:
    plan = meta.get("plan") or {}
    queries = meta.get("queries") or []
    by_ch: dict[str, dict[str, Any]] = defaultdict(lambda: {"searches": 0, "ok": 0, "failed": 0, "results": 0,
                                                            "sellers": set(), "offers": 0, "priced": 0})
    by_mk: dict[str, dict[str, Any]] = defaultdict(lambda: {"searches": 0, "results": 0, "sellers": set()})
    for q in queries:
        purpose = q.get("purpose")
        ch = purpose if purpose in ("local_map", "shopping") else (q.get("channel") or purpose or "other")
        row = by_ch[ch]
        row["searches"] += 1
        row["ok"] += q.get("status") == "ok"
        row["failed"] += q.get("status") == "failed"
        row["results"] += q.get("result_count") or 0
        mk = q.get("market") or "any"
        by_mk[mk]["searches"] += 1
        by_mk[mk]["results"] += q.get("result_count") or 0
    src_by_id = {s.id: s for s in sources}
    for s in sources:
        if not is_seller_source(s):
            continue
        for ch in s.channels or s.purposes:
            by_ch[ch]["sellers"].add(s.domain)
        for mk in s.markets:
            by_mk[mk]["sellers"].add(s.domain)
    for o in offers:
        s = src_by_id.get(o.source_id or "")
        for ch in (s.channels if s and s.channels else (s.purposes if s else [])):
            by_ch[ch]["offers"] += 1
            by_ch[ch]["priced"] += o.price is not None
    labels = dict(disc.CHANNELS, shopping="Google Shopping (Canada)", local_map="Map listings (Google Maps)")
    channels = []
    relevant = {c["channel"]: c for c in plan.get("channels") or []}
    for ch, row in by_ch.items():
        channels.append({"channel": ch, "label": labels.get(ch, ch.replace("_", " ")), "searches": row["searches"],
                         "ok": row["ok"], "failed": row["failed"], "results": row["results"],
                         "sellers": len(row["sellers"]), "offers": row["offers"], "priced": row["priced"]})
    order = list(disc.CHANNELS)
    channels.sort(key=lambda c: order.index(c["channel"]) if c["channel"] in order else len(order))
    not_searched = [{"channel": k, "label": c["label"], "reason": c["reason"]}
                    for k, c in relevant.items() if not c["relevant"]]
    unsearched_relevant = [{"channel": k, "label": c["label"]} for k, c in relevant.items()
                           if c["relevant"] and k not in by_ch and not (k == "local_suppliers" and by_ch.get("local_map"))]
    markets = [{"market": mk, "label": disc.MARKET_LABELS.get(mk, mk), "searches": r["searches"],
                "results": r["results"], "sellers": len(r["sellers"])}
               for mk, r in sorted(by_mk.items(), key=lambda kv: (disc.MARKETS + ("any",)).index(kv[0])
                                   if kv[0] in disc.MARKETS + ("any",) else 99)]

    priced = [o for o in offers if o.price is not None and not o.superseded()]
    verified = [o for o in priced if o.price_basis in VERIFIED_BASES]
    snippet = [o for o in priced if o.price_basis == "snippet"]
    groups = {g["key"]: g["count"] for g in market.get("groups") or []}
    inaccessible = []
    for s in sources:
        if s.fetch and not s.fetch.get("ok"):
            inaccessible.append({"domain": s.domain, "url": s.url, "reason": _fetch_reason(s.fetch.get("error"))})
    for cp in meta.get("contact_pages") or []:
        if not cp.get("ok"):
            inaccessible.append({"domain": cp["domain"], "url": cp["url"],
                                 "reason": "contact page: " + _fetch_reason(cp.get("error"))})
    failed_searches = [{"query": q["query"], "channel": q.get("channel") or q.get("purpose"),
                        "error": (q.get("error") or {}).get("message")} for q in queries if q.get("status") == "failed"]
    found = {
        "vendors": len(vendors),
        "local_vendors": sum(1 for v in vendors if v["tier"] == "local"),
        "offers": len([o for o in offers if not o.superseded()]),
        "priced_offers": len(priced),
        "verified_prices": len(verified),
        "snippet_prices": len(snippet),
        "quote_required_vendors": sum(1 for v in vendors if v["price_status"] == "quote_required"),
        "vendors_without_price": sum(1 for v in vendors if v["price_status"] == "no_price_seen"),
        "used_listings": groups.get("used", 0),
        "auction_bids": groups.get("current_bids", 0),
        "completed_sales": groups.get("completed_sales", 0),
        "trade_prices": groups.get("new_trade", 0),
        "map_listings": len(meta.get("local_businesses") or []),
    }
    return {
        "channels": channels, "markets": markets, "not_relevant": not_searched,
        "relevant_not_searched": unsearched_relevant,
        "found": found, "inaccessible": inaccessible[:30], "failed_searches": failed_searches,
        "rounds": plan.get("rounds") or [], "stop_reason": plan.get("stop_reason"), "deepened": plan.get("deepened"),
        "local_search": plan.get("local_search"),
        "next_steps": _next_steps(plan, found, vendors, unsearched_relevant, inaccessible, meta),
        "disclaimer": DISCLAIMER,
    }


def _next_steps(plan: dict[str, Any], found: dict[str, int], vendors: list[dict[str, Any]],
                unsearched: list[dict[str, str]], inaccessible: list[dict[str, str]], meta: dict[str, Any]) -> list[str]:
    steps = []
    local = [v for v in vendors if v["tier"] == "local"]
    local_priced = [v for v in local if v["price_status"] == "published"]
    if local and not local_priced:
        names = ", ".join(v["name"] for v in local[:3])
        steps.append(f"No local supplier showed a price: ask {names} for a quote (contacts in the Suppliers tab).")
    elif not local:
        steps.append("No Thunder Bay supplier was found online for this item; local suppliers that don't list "
                     "products online may still carry it - call the ones that sell this category.")
    if plan and "Google Maps" not in (plan.get("local_search") or "Google Maps"):
        steps.append("Add a SerpApi key to include Google Maps listings of local businesses (free plan).")
    if found["verified_prices"] == 0 and found["priced_offers"]:
        steps.append("Every price came from search snippets - open the listings or request quotes to confirm.")
    if found["quote_required_vendors"]:
        steps.append(f"{found['quote_required_vendors']} supplier(s) quote on request; trade pricing is often lower "
                     "than published prices.")
    if found["trade_prices"] == 0:
        steps.append("No published trade/wholesale price was found: ask distributors for account or volume pricing.")
    if unsearched:
        steps.append("Not searched this time (budget): " + ", ".join(u["label"].lower() for u in unsearched[:4]) +
                     ". A Deep search covers more channels.")
    if len(inaccessible) >= 3:
        steps.append(f"{len(inaccessible)} pages couldn't be read; their prices rely on search snippets.")
    if meta.get("depth") == "quick" and not plan.get("deepened"):
        steps.append("This was a Quick search; Standard or Deep runs more searches and follow-ups.")
    return steps
