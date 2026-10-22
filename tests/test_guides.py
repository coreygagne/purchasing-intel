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
