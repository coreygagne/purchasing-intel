"""Research plan, local supplier discovery, contacts, market value and order totals.

Simulated web only (tests/fakeweb.py): the businesses, domains and phone numbers below are fictional test
fixtures (555-01xx numbers are reserved for fiction).
"""

from fastapi.testclient import TestClient

from app import discovery as disc
from app import extract as ex
from app.config import Settings
from app.evidence import Offer
from app.main import create_app
from app.market import market_value, order_totals
from tests.fakeweb import LOCAL_SITE, SERP_SHOPPING, FakeWeb, tavily_result, with_local_supplier
from tests.test_api import research

def local_web() -> FakeWeb:
    return with_local_supplier(FakeWeb(serp_body=SERP_SHOPPING))


def run(tmp_path, fw, **kw):
    settings = Settings(tavily_api_key="tvly-test-key", serpapi_api_key="serp-test", database_path=tmp_path / "t.db")
    with TestClient(create_app(settings, transport=fw.transport())) as c:
        job = research(c, **kw)
        assert job["status"] == "done", job
        return c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]


# ------------------------------------------------------------------- plan


def test_plan_starts_local_and_always_covers_wholesale_and_manufacturer():
    cat = disc.categorize("Acme TX-4400 torque widget")
    plan = disc.initial_plan("Acme TX-4400 torque widget", cat, "quick", brand="Acme", budget=8)
    assert len(plan) == 8
    assert plan[0].market == "local" and "Thunder Bay" in plan[0].query
    channels = {pq.channel for pq in plan}
    assert {"wholesale", "manufacturer", "local_suppliers"} <= channels
    assert len({disc._norm(pq) for pq in plan}) == len(plan)  # no repeated searches


def test_plan_follows_category_and_used_preference():
    ppe = disc.categorize("nitrile gloves box of 100")
    assert ppe.key == "ppe"
    plan = disc.initial_plan("nitrile gloves box of 100", ppe, "deep", budget=20)
    assert not {"used", "auction"} & {pq.channel for pq in plan}
    reasons = {r["channel"]: r["reason"] for r in disc.channel_table(ppe) if not r["relevant"]}
    assert "used PPE" in reasons["used"]
    tools = disc.categorize("Milwaukee 2767-20 impact wrench")
    new_only = disc.initial_plan("Milwaukee 2767-20", tools, "deep", used_ok=False, budget=20)
    assert not {"used", "auction", "completed_sales"} & {pq.channel for pq in new_only}
    assert any(r["reason"] == "you asked for new only" for r in disc.channel_table(tools, used_ok=False))


def test_property_plan_uses_listings_and_sales_not_wholesale():
    cat = disc.categorize("industrial warehouse building")
    assert cat.key == "property"
    plan = disc.initial_plan("industrial warehouse building", cat, "standard", budget=14)
    channels = {pq.channel for pq in plan}
    assert {"property_listings", "property_sales"} <= channels and "wholesale" not in channels
    assert any(pq.domains and "realtor.ca" in pq.domains for pq in plan)


def test_expensive_or_high_risk_items_are_searched_deeper():
    machinery = disc.categorize("used forklift 5000 lb")
    rounds, why = disc.depth_decision("standard", machinery, "used forklift 5000 lb", None, None, None)
    assert rounds == disc.DEPTH_BUDGET["deep"]["rounds"] and "higher-risk" in why
    tools = disc.categorize("torque wrench")
    assert disc.depth_decision("standard", tools, "torque wrench", 80.0, 1, None) == (
        disc.DEPTH_BUDGET["standard"]["rounds"], None)
    rounds, why = disc.depth_decision("quick", tools, "torque wrench", 1200.0, 10, None)
    assert rounds == disc.DEPTH_BUDGET["standard"]["rounds"] and "CAD 12,000" in why
    assert disc.depth_decision("deep", machinery, "forklift", None, None, None)[1] is None


def test_alt_spellings_for_trade_names():
    assert "300 kcmil 3-conductor teck" in [a.lower() for a in disc.alt_spellings("300 MCM 3-conductor teck")]


# --------------------------------------------------------------- extraction


def test_contacts_and_location_are_copied_not_inferred():
    found = ex.contacts_in_text("Gerrie Example Ltd, 99 Red River Rd, Thunder Bay, ON P7B 1A1. Tel 807.555.0199. "
                                "Model 2767-20, part 48-11-1850")
    assert found["phones"] == ["(807) 555-0199"]  # model numbers are not phone numbers
    assert found["addresses"][0].endswith("Thunder Bay, ON P7B 1A1")
    assert ex.location_tier("Winnipeg, MB R3C 0A1") == ("canada", "Canadian postal code")
    assert ex.location_tier("Dryden, ON P8N 1A1")[0] == "regional"
    assert ex.location_tier("1 Main St, Duluth, MN 55802")[0] == "us"
    assert ex.location_tier("") == (None, None)
    html = ('<script type="application/ld+json">{"@type": "LocalBusiness", "telephone": "+1 807 555 0110", '
            '"email": "info@example-supply.ca", "address": {"streetAddress": "5 Main St", "addressLocality": '
            '"Thunder Bay", "addressRegion": "ON", "postalCode": "P7A 1A1"}}</script>')
    c = ex.contacts_in_html(html)
    assert c["phones"] == ["(807) 555-0110"] and c["emails"] == ["info@example-supply.ca"]
    assert c["addresses"] == ["5 Main St, Thunder Bay, ON, P7A 1A1"]


def test_price_kinds_and_badges():
    text = "Lot 12 forklift Sold for $5,200 on Oct 3. Similar unit current bid $3,100"
    i = text.find("$5,200")
    assert ex.price_kind(text, i, i + 6) == "completed_sale"
    j = text.find("$3,100")
    assert ex.price_kind(text, j, j + 6) in ("current_bid", "completed_sale")
    assert ex.price_kind("Forklift for sale $9,800", 17, 23) == "asking"
    assert ex.badges("Amazon's Choice for torque widget") == ["Amazon's Choice"]


# ---------------------------------------------------------------- full run


def test_local_suppliers_found_on_maps_followed_up_and_contacted(tmp_path):
    res = run(tmp_path, local_web())
    assert res["providers"]["local"] == "SerpApi (Google Maps)"
    maps_rows = [q for q in res["queries"] if q["purpose"] == "local_map"]
    assert maps_rows and maps_rows[0]["status"] == "ok"
    # round 2 searched the local supplier's own site
    lead = [q for q in res["queries"] if q["round"] == 2 and q.get("domains") == ["northerntoolsupply-example.ca"]]
    assert lead and lead[0]["result_count"] == 1
    v = next(v for v in res["vendors"] if v["name"] == "Northern Tool Supply Ltd")
    assert res["vendors"][0]["id"] == v["id"]  # local suppliers are listed first
    assert v["tier"] == "local" and "Thunder Bay" in v["tier_basis"]
    assert v["phones"][0] == {"value": "(807) 555-0142", "basis": "Google Maps listing",
                              "url": "https://www.google.com/maps?cid=1234567890", "seen_at": v["phones"][0]["seen_at"]}
    assert v["emails"][0]["value"] == "sales@northerntoolsupply-example.ca"
    assert v["emails"][0]["basis"] == "the supplier's own website"
    assert v["emails"][0]["url"] == LOCAL_SITE + "contact-us"
    assert v["price_status"] == "no_price_seen" and v["quote_opportunity"]
    assert any("trade pricing" in t["text"] for t in v["trade_signals"])
    assert v["rating"]["basis"].startswith("Google Maps rating")
    assert res["vendor_summary"]["local"] >= 1 and res["vendor_summary"]["quote_opportunities"] >= 1
    plan = res["plan"]
    assert plan["category"] == "tools" and plan["rounds"][0]["round"] == 1 and plan["stop_reason"]


def test_without_serpapi_local_search_is_reported_unavailable(tmp_path):
    settings = Settings(tavily_api_key="tvly-test-key", database_path=tmp_path / "t.db")
    with TestClient(create_app(settings, transport=FakeWeb().transport())) as c:
        res = c.get(f"/api/comparisons/{research(c)['comparison_id']}").json()["result"]
    assert res["providers"]["local"] is None
    assert "needs a SerpApi key" in res["plan"]["local_search"]
    assert res["local_businesses"] == []


def test_completed_sales_are_market_evidence_not_offers(tmp_path):
    fw = FakeWeb()
    fw.tavily_results["price"].append(tavily_result(
        "https://www.ebay.ca/itm/999", "Acme TX-4400 Torque Widget", "Acme TX-4400 torque widget Sold for $260.00"))
    res = run(tmp_path, fw)
    sold = next(o for o in res["offers"] if o["url"] == "https://www.ebay.ca/itm/999")
    assert sold["price_kind"] == "completed_sale" and not sold["comparable"]
    assert any("completed sale" in r for r in sold["exclusion_reasons"])
    groups = {g["key"]: g for g in res["market_value"]["groups"]}
    assert groups["completed_sales"]["count"] == 1 and groups["completed_sales"]["median"] is None


# ------------------------------------------------------------ market value


def _offer(i, price, supplier_type="retailer", **kw) -> Offer:
    base = dict(id=f"O{i}", source_id=None, url=f"https://s{i}.example/x", supplier=f"S{i}", supplier_domain=f"s{i}",
                supplier_type=supplier_type, supplier_in_directory=False, country="CA", country_basis="x",
                product_title="Acme TX-4400", price=price, price_high=None, currency="CAD", currency_basis="stated",
                price_text=f"${price}", price_type="listed", price_basis="structured_data", evidence_quote="",
                observed_at="2026-10-21T00:00:00+00:00", provider="t", match_level="exact", price_cad=price)
    base.update(kw)
    return Offer(**base)


def test_market_value_groups_and_median_rules():
    offers = [_offer(1, 300.0), _offer(2, 320.0), _offer(3, 350.0), _offer(4, 280.0, "industrial distributor"),
              _offer(5, 150.0, condition="used"), _offer(6, 999.0, match_level="different")]
    mv = market_value(offers, ["TX-4400"])
    g = {x["key"]: x for x in mv["groups"]}
    assert (g["new_retail"]["count"], g["new_retail"]["low"], g["new_retail"]["median"], g["new_retail"]["high"]) == (
        3, 300.0, 320.0, 350.0)
    assert g["new_trade"]["count"] == 1 and g["new_trade"]["median"] is None  # too few for a median
    assert g["used"]["low"] == 150.0
    assert mv["overall_new"]["count"] == 4 and mv["overall_new"]["supported"]
    assert all(ob["offer_id"] != "O6" for x in mv["groups"] for ob in x["observations"])  # different item


def test_order_totals_show_tax_separately():
    o = _offer(1, 100.0, shipping_cost=0.0, shipping_text="Free shipping", shipping_scope="canada")
    from app.import_costs import delivered_estimate
    from app.analysis import _offer_dict
    o.delivered = delivered_estimate(_offer_dict(o), {}, 3)
    t = order_totals(o, 3, None, "ON")
    assert t["pre_tax_total"] == 300.0 and t["tax"]["value"] == 39.0 and t["total_with_tax"] == 339.0
    assert t["unit"]["value"] == 100.0 and t["complete"]
    per_ft = _offer(2, 8.5, per_length="ft", per_ft_cad=8.5, order_total_cad=2550.0)
    t2 = order_totals(per_ft, None, {"text": "300 ft", "feet": 300.0}, "ON")
    assert t2["pre_tax_total"] == 2550.0 and "shipping" in t2["unknown"] and not t2["complete"]


# ------------------------------------------------ recommendation, coverage, RFQs


def test_plain_recommendation_picks_and_comparison(tmp_path):
    res = run(tmp_path, local_web(), quantity=2)
    r = res["recommendation"]
    assert r["lead"]["supplier"] == "KMS Tools"  # best-supported option leads
    assert any("CAD 679.98 before tax for 2 unit(s)" in w for w in r["lead"]["why"])
    labels = {lab: row for row in r["comparison"] for lab in row["labels"]}
    assert labels["Lowest comparable cost"]["supplier"] == "Canadian Tire"
    assert labels["Best used or auction option"]["supplier"] == "Princess Auto"  # refurbished, shown separately
    intl = labels["Best option from outside Canada"]
    assert intl["supplier"] == "Amazon.com" and not intl["total_complete"] and "duty" in intl["total_unknown"]
    assert "local" not in r["picks"]  # the local supplier showed no price: no pick, a quote request instead
    assert any(m["kind"] == "local" and "Northern Tool Supply Ltd" in m["text"] for m in r["missing_picks"])
    assert r["distinction"]


def test_coverage_report_counts_without_claiming_completeness(tmp_path):
    res = run(tmp_path, local_web())
    cov = res["coverage"]
    assert cov["found"]["map_listings"] == 1 and cov["found"]["local_vendors"] >= 1
    assert cov["found"]["verified_prices"] >= 2 and cov["found"]["quote_required_vendors"] == 2
    chans = {c["channel"]: c for c in cov["channels"]}
    assert chans["wholesale"]["searches"] >= 1 and chans["manufacturer"]["searches"] >= 1
    assert chans["local_map"]["searches"] >= 1
    assert any(m["market"] == "local" for m in cov["markets"])
    assert any(x["domain"] == "grainger.ca" for x in cov["inaccessible"])
    assert "not every supplier" in cov["disclaimer"] and "%" not in cov["disclaimer"]
    assert cov["next_steps"] and cov["stop_reason"]


def test_rfq_drafts_are_drafts_with_sourced_contacts(tmp_path):
    res = run(tmp_path, local_web(), quantity=2)
    d = next(x for x in res["rfq_drafts"] if x["vendor"] == "Northern Tool Supply Ltd")
    assert d["to"] == "sales@northerntoolsupply-example.ca" and d["to_basis"] == "the supplier's own website"
    assert d["how"] == "email" and d["mailto"].startswith("mailto:sales@northerntoolsupply-example.ca?subject=")
    assert "Midcontinent Terminal in Thunder Bay" in d["body"] and "Quantity: 2 unit(s)" in d["body"]
    assert "[Your name]" in d["body"]  # no personal details invented
    tenaquip = next(x for x in res["rfq_drafts"] if x["vendor"] == "Tenaquip")
    assert tenaquip["to"] is None and tenaquip["how"] == "website contact form"
    assert not any(x["vendor"].startswith("Amazon") for x in res["rfq_drafts"])  # marketplaces aren't asked


def test_quality_themes_separate_patterns_from_isolated_mentions():
    from app.analysis import quality_themes
    issues = [{"quote": "The clutch overheats under load", "domain": "a.example", "url": "u1", "exact_model": True},
              {"quote": "Mine overheated after an hour", "domain": "b.example", "url": "u2", "exact_model": False},
              {"quote": "It broke in a week", "domain": "a.example", "url": "u3", "exact_model": True}]
    themes = {t["theme"]: t for t in quality_themes(issues, [])}
    assert themes["Overheating"]["pattern"] and themes["Overheating"]["sites"] == 2
    assert themes["Overheating"]["exact_model_mentions"] == 1
    assert not themes["Breakage or failure"]["pattern"]
    assert themes["Breakage or failure"]["label"] == "isolated: one site"


def test_import_checklist_leaves_unknowns_unknown(tmp_path):
    res = run(tmp_path, local_web())
    ck = res["import_checklist"]
    assert ck["applies"] and ck["foreign_offers"] >= 1
    items = {i["topic"]: i for i in ck["items"]}
    assert items["Tariff classification (HS code)"]["status"] == "unknown"
    assert items["Country of origin"]["status"] == "unknown"
    assert "USD at 1.38" in items["Currency"]["text"]
    assert items["Electrical safety mark"]["status"] == "check"  # tools category compliance
    assert res["compliance"][0]["topic"] == "Electrical safety mark"


def test_comparisons_saved_before_this_version_are_reanalysed(tmp_path):
    from app.research import ANALYSIS_VERSION, reanalyze
    res = run(tmp_path, local_web())
    old = {k: v for k, v in res.items() if k not in ("plan", "local_businesses", "contact_pages", "answers",
                                                     "stated_assumptions", "vendors", "coverage", "market_value",
                                                     "recommendation", "rfq_drafts", "import_checklist")}
    for s in old["sources"]:
        for k in ("channels", "markets", "round", "contacts", "location", "badges"):
            s.pop(k, None)
    for o in old["offers"]:
        o.pop("price_kind", None)
    old["analysis_version"] = 3
    new = reanalyze(old, {}, "ON")
    assert new["analysis_version"] == ANALYSIS_VERSION
    assert new["vendors"] and new["coverage"]["found"]["offers"] and new["recommendation"]["lead"]
    assert new["recommendations"]["lowest"]["supplier"] == res["recommendations"]["lowest"]["supplier"]
