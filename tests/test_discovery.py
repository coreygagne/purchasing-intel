"""Research plan, local supplier discovery, contacts, market value and order totals.

Simulated web only (tests/fakeweb.py): the businesses, domains and phone numbers below are fictional test
fixtures (555-01xx numbers are reserved for fiction).
"""

from fastapi.testclient import TestClient

from app import clarify as cl
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
    assert found["phones"] == ["807.555.0199"]  # as written; model numbers are not phone numbers
    assert found["addresses"][0].endswith("Thunder Bay, ON P7B 1A1")
    assert ex.location_tier("Winnipeg, MB R3C 0A1") == ("canada", "Canadian postal code")
    assert ex.location_tier("Dryden, ON P8N 1A1")[0] == "regional"
    assert ex.location_tier("1 Main St, Duluth, MN 55802")[0] == "us"
    assert ex.location_tier("") == (None, None)
    html = ('<script type="application/ld+json">{"@type": "LocalBusiness", "telephone": "+1 807 555 0110", '
            '"email": "info@example-supply.ca", "address": {"streetAddress": "5 Main St", "addressLocality": '
            '"Thunder Bay", "addressRegion": "ON", "postalCode": "P7A 1A1"}}</script>')
    c = ex.contacts_in_html(html)
    assert c["phones"] == ["+1 807 555 0110"] and c["emails"] == ["info@example-supply.ca"]
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



# ------------------------------------------------- review regressions (round 3)


def test_product_names_with_property_or_vehicle_words_keep_their_category():
    cases = {"warehouse pallet racking": "machinery", "building wire 12 AWG T90": "electrical",
             "Generac home standby generator": "machinery", "lot of 50 galvanized shackles": "parts",
             "Home Hardware deck screws": "parts", "electric pallet truck": "machinery", "hand truck": "tools",
             "semi-gloss exterior paint": "consumables", "car battery charger": "tools",
             "2019 Ford F-150 pickup": "vehicle", "used dump truck": "vehicle",
             "warehouse space for lease": "property", "10 acres vacant land": "property"}
    assert {q: disc.categorize(q).key for q in cases} == cases


def test_shared_platform_websites_never_merge_businesses():
    from app.evidence import build_sources
    from app.providers.base import SearchHit
    from app.vendors import build_vendors
    maps = [{"name": "Northern Rigging Supply", "address": "1 Main St, Thunder Bay, ON P7B 1A1", "phone": "(807) 555-0101",
             "website": "https://www.facebook.com/northernrigging", "category": "Rigging", "rating": 4.0, "reviews": 3,
             "listing_url": "https://www.google.com/maps?cid=1", "retrieved_at": "2026-10-21T00:00:00+00:00"},
            {"name": "Lakehead Safety", "address": "2 Main St, Thunder Bay, ON P7B 1A2", "phone": "(807) 555-0102",
             "website": "https://www.facebook.com/lakeheadsafety", "category": "Safety", "rating": 4.5, "reviews": 9,
             "listing_url": "https://www.google.com/maps?cid=2", "retrieved_at": "2026-10-21T00:00:00+00:00"}]
    hits = [SearchHit("Tavily", "q", "local_suppliers", "https://www.facebook.com/someshop/", "Some Shop - Home | Facebook",
                      "Some Shop, Kenora. Call 807-555-0103", 1, channel="local_suppliers", market="local"),
            SearchHit("Tavily", "q", "local_suppliers", "https://www.facebook.com/othershop/", "Other Shop | Facebook",
                      "Other Shop. Call 204-555-0104", 2, channel="local_suppliers", market="local")]
    sources = build_sources(hits, [])
    vendors = build_vendors(sources, [], maps)
    by_name = {v["name"]: v for v in vendors}
    assert by_name["Northern Rigging Supply"]["phones"][0]["value"] == "(807) 555-0101"
    assert by_name["Lakehead Safety"]["phones"][0]["value"] == "(807) 555-0102"
    assert "facebook.com" not in by_name  # the platform itself is never a supplier
    assert {v["phones"][0]["value"] for v in vendors if v["name"] in ("Some Shop", "Other Shop")} == {
        "807-555-0103", "204-555-0104"}
    leads = disc.find_leads([], maps, name="x", brand=None, category=disc.CATEGORIES["general"])
    assert not any(lead.value.endswith("facebook.com") for lead in leads)


def test_a_mention_of_thunder_bay_does_not_make_a_seller_local():
    from app.research import _snippet_details
    from app.evidence import build_sources
    from app.providers.base import SearchHit
    [s] = build_sources([SearchHit("Tavily", "q", "retail", "https://shop.example.ca/x", "Widget",
                                   "We ship across Ontario, including Thunder Bay. $20", 1)], [])
    _snippet_details(s)
    assert s.location["tier"] is None and s.location["mentions_home"]
    c = ex.contacts_in_text("Next-day delivery to Thunder Bay. Head office: 200 Bay St, Toronto ON M5J 2J2")
    assert c["addresses"] == ["200 Bay St, Toronto ON M5J 2J2"]
    assert ex.location_tier(c["addresses"][0])[0] == "regional"


def test_live_auction_bids_are_not_completed_sales():
    for text in ("High Bid: $41,000. Auction closes Oct 30", "Highest bid $950 · ends in 2d", "Winning bid so far $300"):
        assert ex.price_kind(text) == "current_bid", text
    for text in ("Winning bid $500. Auction ended", "Sold: $260.00", "Lot closed - high bid $700"):
        assert ex.price_kind(text) == "completed_sale", text
    assert ex.price_kind("Final price $1,200 after discount") == "asking"


def test_auction_site_prices_are_bids_by_default(tmp_path):
    fw = FakeWeb()
    fw.tavily_results["price"].append(tavily_result(
        "https://www.govdeals.ca/asset/1", "Acme TX-4400 Torque Widget", "Acme TX-4400 torque widget $150.00"))
    res = run(tmp_path, fw)
    o = next(o for o in res["offers"] if "govdeals" in o["url"])
    assert o["price_kind"] == "current_bid" and not o["comparable"]
    v = next(v for v in res["vendors"] if v["domain"] == "govdeals.ca")
    assert v["price_status"] == "no_price_seen" and v["sold_or_bid_prices"][0]["price_kind"] == "current_bid"


def test_quality_themes_ignore_negations_copies_and_unrelated_mentions():
    from app.analysis import quality_themes
    issues = [{"quote": "Handle is too short", "domain": "reddit.com", "url": "u1"},
              {"quote": "Paint scratches off easily", "domain": "homedepot.ca", "url": "u2"},
              {"quote": "Mine has never failed in 3 years", "domain": "forum.example", "url": "u3"},
              {"quote": "The motor overheats after an hour", "domain": "a.example", "url": "u4"},
              {"quote": "The motor overheats after an hour.", "domain": "b.example", "url": "u5"}]
    themes = quality_themes(issues, [])
    assert [t["theme"] for t in themes] == ["Overheating"]  # no "Other" group, no negated "failure"
    assert themes[0]["sites"] == 1 and not themes[0]["pattern"]  # syndicated copy counts once


def test_foreign_per_foot_totals_keep_import_costs_unknown():
    o = _offer(1, 2.0, per_length="ft", per_ft_cad=2.8, order_total_cad=840.0, country="US", currency="USD",
               fx_rate=1.4, price_cad=2.8)
    t = order_totals(o, None, {"text": "300 ft", "feet": 300.0}, "ON", {})
    assert {"shipping", "duty", "surtax", "brokerage"} <= set(t["unknown"])
    assert t["tax"]["label"] == "GST 5% at the border" and t["tax"]["value"] == 42.0
    t2 = order_totals(_offer(2, 2.0, per_length="ft", per_ft_cad=2.0, order_total_cad=600.0), None,
                      {"text": "300 ft", "feet": 300.0}, "ON", {"domestic_shipping_cad": 50.0})
    assert t2["pre_tax_total"] == 650.0 and t2["complete"] and t2["label"] == "estimated"


def test_length_answers_with_reels_or_without_units():
    two = cl.apply_answers("300 MCM teck cable", {"length": "2 reels of 500 ft"}, None)
    assert two["length_text"] == "1000 ft of"
    bare = cl.apply_answers("300 MCM teck cable", {"length": "300"}, None)
    assert bare["length_text"] is None and any("has no unit" in a for a in bare["assumptions"])


def test_auto_deepening_applies_to_every_search_setting(tmp_path):
    settings = Settings(tavily_api_key="tvly-test-key", serpapi_api_key="serp-test", database_path=tmp_path / "t.db")
    with TestClient(create_app(settings, transport=local_web().transport())) as c:
        res = c.get(f"/api/comparisons/{research(c, 'used forklift 5000 lb', depth='standard')['comparison_id']}"
                    ).json()["result"]
    assert res["plan"]["run_depth"] == "deep" and "higher-risk" in res["plan"]["deepened"]
    first = [q for q in res["queries"] if q["round"] == 1 and q["purpose"] not in ("local_map", "shopping")]
    assert disc.DEPTH_BUDGET["standard"]["rounds"][0] < len(first) <= disc.DEPTH_BUDGET["deep"]["rounds"][0]
    assert len([q for q in res["queries"] if q["purpose"] == "local_map"]) == disc.DEPTH_BUDGET["deep"]["maps"]


def test_phone_numbers_keep_extensions_and_dedupe_by_digits():
    found = ex.contacts_in_text("Call 1-800-555-0199 ext. 204, or (807) 555-0142 / 807.555.0142")
    assert found["phones"] == ["1-800-555-0199 ext. 204", "(807) 555-0142"]



def test_leads_follow_named_local_businesses_not_news_pages(tmp_path):
    fw = local_web()
    # real-world shapes seen in search results: a trade-news page about a Thunder Bay branch (no item named),
    # and a Yellow Pages page for one Thunder Bay business with no website given
    fw.tavily_results["other"] = [
        tavily_result("https://electricalindustry.example/ces-opens-thunder-bay-branch",
                      "City Electric Supply Officially Opens Thunder Bay Branch", "The branch opened in June."),
        tavily_result("https://www.yellowpages.ca/bus/Ontario/Thunder-Bay/MGM-Example-Electric/2408907.html",
                      "MGM Example Electric - Electrical Equipment & Supply Stores - Thunder Bay",
                      "724 Macdonell St, Thunder Bay, ON P7B 4A6. 807-555-0177")]
    res = run(tmp_path, fw, depth="standard")
    later = [q for q in res["queries"] if q["round"] >= 2]
    assert not any(q.get("domains") == ["electricalindustry.example"] for q in later)
    named = [q for q in later if q.get("lead") == "MGM Example Electric"]
    assert named and named[0]["query"].startswith("MGM Example Electric Thunder Bay")
    v = next(v for v in res["vendors"] if v["name"] == "MGM Example Electric")
    assert v["tier"] == "local" and v["phones"][0]["value"] == "807-555-0177"
    assert v["phones"][0]["basis"] == "directory listing (yellowpages.ca)"


def test_listing_and_category_pages_are_search_results():
    from app.evidence import is_search_results_url
    for u in ("https://www.kijiji.ca/b-buy-sell/ontario/teck-cable/k0c10l9004",
              "https://www.alibaba.com/showroom/300-mcm-cable.html",
              "https://www.yellowpages.ca/search/si/1/Electrical+Equipment/Thunder+Bay+ON"):
        assert is_search_results_url(u), u
    assert not is_search_results_url("https://www.kijiji.ca/v-electrical/thunder-bay/teck-cable/1700000000")


def test_map_searches_name_the_town_and_far_results_are_not_local():
    qs = disc.local_queries("300 MCM teck cable", disc.categorize("300 MCM teck cable"), 2)
    assert qs == ["electrical supply Thunder Bay ON", "electrical wholesaler Thunder Bay ON"]
    far = [{"name": "Dryden Electric", "address": "40 King St, Dryden, ON P8N 1B6",
            "website": "https://drydenelectric.example.ca/"}]
    [lead] = [l for l in disc.find_leads([], far, name="x", brand=None, category=disc.CATEGORIES["general"])]
    assert lead.market == "regional" and lead.priority > 1


# ---------------------------------------------- from the first live runs (2026-10-22)


def test_searches_are_for_the_item_not_the_order():
    from app.research import _without_order_length
    assert _without_order_length("300 ft of 300 MCM 3-conductor copper teck cable 1000V") == \
        "300 MCM 3-conductor copper teck cable 1000V"
    assert _without_order_length("Milwaukee 2767-20") == "Milwaukee 2767-20"


def test_quick_plan_reaches_beyond_the_always_channels():
    name = "300 MCM 3-conductor copper teck cable 1000V"
    plan = disc.initial_plan(name, disc.categorize(name), "quick", alt_names=["300 kcmil 3-conductor teck"], budget=8)
    channels = [pq.channel for pq in plan]
    assert channels.count("wholesale") == 1 and channels.count("manufacturer") == 1
    assert {"reviews", "distributor"} & set(channels)


def test_live_run_shapes_become_the_right_suppliers():
    from app.evidence import build_sources
    from app.providers.base import SearchHit
    from app.research import _snippet_details
    from app.vendors import build_vendors

    def hit(url, title, snippet, channel="dealer"):
        return SearchHit("Tavily", "q", channel, url, title, snippet, 1, channel=channel, market="local")
    hits = [
        hit("https://www.facebook.com/mceacherns/", "McEachern's Tool House | Thunder Bay ON",
            "Come down to McEachern's Tool House on 721 Vickers St N."),
        hit("https://www.itoolhouse-example.ca/", "McEachern Tool House: HOME",
            "721 Vickers St N, Thunder Bay, Ontario, Canada, P7C 4B8. Phone: (807) 555-0151. Email: info@itoolhouse-example.ca."),
        hit("https://assets-us-01.kc-usercontent.com/x/teck.pdf", "Teck cable catalogue",
            "300 MCM teck cable. 1.800.555.0101 SALES@TEXCAN.EXAMPLE", "manufacturer"),
        hit("https://thesis.lakeheadu.ca/handle/1", "Grid study", "teck cable in Thunder Bay", "local_suppliers"),
        hit("https://www.ieso.ca/page", "IESO market", "Ontario electricity", "local_suppliers"),
        hit("https://electricalindustry.example.ca/news", "City Electric Supply opens branch", "It opened in June.",
            "local_suppliers"),
    ]
    sources = build_sources(hits, [])
    for s in sources:
        _snippet_details(s)
    vendors = build_vendors(sources, [], [], item="Milwaukee 2767-20", tokens=["2767-20"])
    names = [v["name"] for v in vendors]
    assert names == ["McEachern's Tool House"]  # one business, not two; no file host, school, agency or news site
    v = vendors[0]
    assert v["domain"] == "itoolhouse-example.ca" and v["phones"][0]["value"] == "(807) 555-0151"
    assert v["emails"][0]["value"] == "info@itoolhouse-example.ca" and v["tier"] == "local"


def test_one_where_to_buy_search_per_manufacturer():
    from app.evidence import build_sources
    from app.providers.base import SearchHit
    sources = build_sources([SearchHit("Tavily", "q", "manufacturer", u, "Milwaukee 2767-20", "", 1)
                             for u in ("https://documents.milwaukeetool.com/x", "https://www.milwaukeetool.ca/y")],
                            ["Milwaukee"])
    leads = disc.find_leads(sources, [], name="Milwaukee 2767-20", brand=None, category=disc.CATEGORIES["tools"])
    assert [l.kind for l in leads].count("manufacturer") == 1


def test_live_text_shapes_parse_correctly():
    # shapes copied from real search results (2026-10-22): Sonepar catalogue names, a product-line size range,
    # a parenthesised currency, and a kit whose snippet lists the bare tool it includes
    assert [(p.amount, p.currency) for p in ex.find_prices("Price: $279.00 (USD) THIS ITEM")] == [(279.0, "USD")]
    assert [x["label"] for x in ex.specs_in("300/3C 1KV TECK90")] == ["300 kcmil", "3-conductor", "1 kV"]
    assert [x["label"] for x in ex.specs_in("3/0/3C 1KV TECK90")][:2] == ["3/0 AWG", "3-conductor"]
    requested = ex.request_specs("300 MCM 3-conductor copper teck cable 1000V")[0]
    chk = ex.spec_check(requested, "300/3C 1KV TECK90 Armoured Cable, Black. TECK90 is available in 600 and 1000V "
                                   "constructions from #14 to 500 kcmil in copper.")
    assert chk["conflicts"] == [] and "300 kcmil" in chk["confirmed"]
    from app.evidence import apply_match
    kit = _offer(1, 800.30, product_title="Milwaukee 2767-22R 18 Volt 1/2 Inch Hex Impact Wrench", price_basis="snippet",
                 evidence_quote="WEB PRICE: $800.30 /EA/EA. Includes: (2767-20) High Torque 1/2 Impact Wrench")
    apply_match([kit], ["2767-20"], {})
    assert kit.match_level == "variant"


def test_utility_pages_are_not_suppliers():
    from app.evidence import build_sources
    from app.providers.base import SearchHit
    from app.research import _snippet_details
    from app.vendors import build_vendors
    [s] = build_sources([SearchHit("Tavily", "q", "local_suppliers", "https://www.synergynorth.example/supply",
                                   "Electricity Supply", "Ontario's electricity supply mix. THUNDER BAY, ON P7A 4L3 "
                                   "(807) 555-0111", 1, channel="local_suppliers", market="local")], [])
    _snippet_details(s)
    assert build_vendors([s], [], [], item="300 MCM teck cable") == []


def test_one_business_across_its_pages_directories_and_name_variants():
    from app.evidence import build_sources
    from app.providers.base import SearchHit
    from app.research import _snippet_details
    from app.vendors import build_vendors

    def hit(url, title, snippet):
        return SearchHit("Tavily", "q", "dealer", url, title, snippet, 1, channel="dealer", market="local")
    addr = "721 Vickers St N, Thunder Bay, Ontario, Canada, P7C 4B8. Phone: (807) 555-0151."
    sources = build_sources([
        hit("https://www.facebook.com/mceachern/", "McEachern's Tool House | Thunder Bay ON", "Cordless tools."),
        hit("https://www.itoolhouse-example.ca/", "HOME | McEachern Tool House", "Largest selection of power tools."),
        hit("https://www.itoolhouse-example.ca/products", "PRODUCTS", addr),
        hit("https://www.novapro-example.com/", "Nova Pro", "1228 Amber Drive Thunder Bay, Ontario P7B 6M5 Phone: 807-555-0184"),
        hit("https://www.facebook.com/novapro/", "Nova-Pro Industrial Supply LTD. | Thunder Bay ON", "Supplying quality products"),
        hit("https://www.catb-example.on.ca/member/1", "View Member Nova Pro Industrial Supply Ltd.",
            "Email: novapro@tbaytel.example ; Address: 1228 Amber Dr. Thunder Bay, ON. P7B 6M5"),
        hit("https://novapro-example.betterteam.com/", "Nova-Pro Industrial Supply Ltd Careers",
            "View job openings. 1228 Amber Dr, Thunder Bay, ON P7B 6M5"),
    ], [])
    for s in sources:
        _snippet_details(s)
    vendors = build_vendors(sources, [], [], item="Milwaukee 2767-20", tokens=["2767-20"])
    assert sorted(v["name"] for v in vendors) == ["McEachern's Tool House", "Nova Pro"]
    mc = next(v for v in vendors if v["name"].startswith("McEachern"))
    assert mc["domain"] == "itoolhouse-example.ca" and mc["phones"][0]["value"] == "(807) 555-0151"
