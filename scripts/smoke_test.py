"""Live check against the REAL configured providers (uses real credits).

    python -m scripts.smoke_test "Milwaukee 2767-20" [--depth quick] [--save]

Runs one research exactly as the app does and prints what came back and from
where. Without --save it uses a throwaway in-memory database. Exit code 0 means
the search provider answered and the pipeline completed; it says nothing about
whether a given product has published prices.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import load_settings
from app.db import Database
from app.providers import provider_status
from app.research import ResearchEngine, ResearchError, ResearchRequest, observation_rows


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--depth", default="quick", choices=["quick", "standard", "deep"])
    ap.add_argument("--save", action="store_true", help="store the result in the configured database")
    args = ap.parse_args()

    settings = load_settings()
    st = provider_status(settings)
    for p in st["providers"]:
        print(f"  {p['name']:<22} {'configured' if p['configured'] else 'not configured'}")
    if not st["ready"]:
        print("\nNo search provider configured. Set TAVILY_API_KEY or SERPAPI_API_KEY in .env.")
        return 2

    db = Database(settings.database_path if args.save else ":memory:")
    llm = None
    if settings.llm_enabled:
        from app.llm import ClaudeAnalyst
        llm = ClaudeAnalyst(settings)
    engine = ResearchEngine(settings, db, llm=llm)
    try:
        res = await engine.run(ResearchRequest(args.query, args.depth), lambda s, p: print(f"  [{p:3d}%] {s}"))
    except ResearchError as exc:
        print(f"\nFAILED ({exc.kind}): {exc}")
        for d in exc.details[:5]:
            print("   -", d.get("message"))
        return 1

    print(f"\nIdentified as: {res['identity']['name']}  (models: {res['identity']['model_tokens'] or 'none'})")
    for q in res["queries"]:
        status = f"{q['result_count']} results" if q["status"] == "ok" else f"{q['status']}: {(q.get('error') or {}).get('message')}"
        print(f"  query [{q['purpose']}] {q['query']!r}: {status}")
    print(f"Usage: {res['credits']}")
    print(f"Sources: {res['counts']}; pages read: {res['fetch']}")
    print("\nOffers (comparable first):")
    for o in res["offers"][:15]:
        price = f"{o['currency'] or '?'} {o['price']:.2f}" if o["price"] is not None else o["price_type"]
        print(f"  {'*' if o['comparable'] else ' '} {o['supplier'][:30]:<30} {price:<16} [{o['price_basis']}] "
              f"{o['match_level']:<10} {o['url'][:70]}")
    rec = res["recommendations"]
    for key in ("lowest", "best_value"):
        r = rec.get(key)
        print(f"\n{key}: " + (f"{r['supplier']} {r['currency']} {r['price']:.2f}\n   " + "\n   ".join(r["explanation"])
                                if r else "none - " + "; ".join(rec["notes"])))
    print("\nGaps:", *res["gaps"], sep="\n  - ")
    if args.save:
        cid = db.save_comparison(title=res["identity"]["name"][:200], query=args.query,
                                 normalized=args.query.lower().strip(), product_key=res["product_key"], result=res)
        db.add_observations(observation_rows(res, cid, None))
        print(f"\nSaved as comparison {cid} in {settings.database_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
