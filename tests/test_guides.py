"""Built-in buying guides for broad terms: types, questions, supplier checklist, safety flags."""

from app import clarify as cl
from app import guides
from app.rfq import rfq_drafts


def test_broad_term_gets_guide_and_the_questions_that_matter():
    r = cl.questions("radios")
    assert r["guide"]["key"] == "radios" and r["guide"]["broad"]
    assert [t["search"] for t in r["guide"]["types"]][0] == "portable two-way radio"
    ids = [q["id"] for q in r["questions"]]
    assert {"g_current", "g_hazardous"} <= set(ids) and "specifics" not in ids
    assert "not from a search" in r["guide"]["label"]


def test_specific_type_keeps_guide_but_not_broad():
    r = cl.questions("portable two-way radio")
    assert r["guide"]["key"] == "radios" and not r["guide"]["broad"]


def test_no_guide_for_part_numbers_or_unrelated_items():
    assert cl.questions("Milwaukee 2767-20")["guide"] is None
    assert guides.match("crane radio remote control") is None
    assert guides.match("300 MCM teck cable") is None


def test_unconfirmed_hazardous_area_is_stated():
    a = cl.apply_answers("radios", {"g_hazardous": "Not sure"}, None)["assumptions"]
    assert any("Hazardous areas not confirmed" in x for x in a)


def test_quote_request_carries_answers_and_checklist():
    vendor = {"id": "V1", "name": "Lakehead Radio", "quote_opportunity": True, "type": "industrial distributor",
              "emails": [], "phones": [], "tier_label": "Thunder Bay", "quote_reasons": [], "website": None}
    d = rfq_drafts([vendor], {"name": "portable two-way radio"}, 12, None,
                   {"g_current": "Motorola XPR 3300", "g_hazardous": "Yes"}, None, "electronics")[0]["body"]
    assert "Must work with current radios: Motorola XPR 3300" in d
    assert "Classified hazardous area: Yes - certification" in d
    assert "Please also confirm:" in d and "ISED" in d


def test_type_search_gives_a_shortlist_not_a_ranking():
    from tests.test_listing_pages import _offer, _run
    offers = [
        _offer(1, 81.99, "Digital Walkie Talkies 22 Channels for Camping, Hiking", supplier_type="retailer"),
        _offer(2, 249.0, "Kenwood NX-P1300 portable two-way radio", supplier_type="industrial distributor"),
        _offer(3, 409.5, "Motorola R2 portable two-way radio", supplier_type="industrial distributor"),
        _offer(4, 300.0, "Portable Radios Archives - Page 2 of 3", supplier_type="industrial distributor"),
    ]
    res = _run("portable two-way radio", offers, "electronics")
    plain = res["recommendation"]
    assert plain["judge"] == "shortlist" and plain["lead"] is None and plain["picks"] == {}
    assert res["recommendations"]["lowest"] is None and res["market_value"]["overall_new"] is None
    by = {o["id"]: o for o in res["offers"]}
    assert not by["O1"]["comparable"] and any("consumer product" in r for r in by["O1"]["exclusion_reasons"])
    assert by["O4"]["page_kind"] == "results"
    shown = {p["offer_id"] for p in plain["listing_pages"]}
    assert {"O2", "O3"} <= shown and "O1" not in shown
    assert res["guide"]["key"] == "radios"


def test_shortlist_leaves_out_listings_that_are_not_the_product_type():
    from tests.test_listing_pages import _offer, _run
    offers = [_offer(1, 74.99, "Canadian Tire Roadside Assistance", supplier_type="retailer"),
              _offer(2, 47.95, "Red Z87.1 Safety Glasses #749618", supplier_type="retailer"),
              _offer(3, 86.99, "CSA Prescription Safety Eyewear", supplier_type="retailer")]
    res = _run("safety glasses", offers, "ppe")
    by = {o["id"]: o for o in res["offers"]}
    assert not by["O1"]["comparable"] and any("doesn't name" in r for r in by["O1"]["exclusion_reasons"])
    assert by["O2"]["comparable"] and by["O3"]["comparable"]
    assert guides.off_topic("portable two-way radio", "Kenwood NX-P1300 Commercial Radios") is None
    assert guides.off_topic("work lights", "LED Light Tower 4 x 300 W") is None
