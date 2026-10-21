"""Sold-by-length items and plain-language specs, modelled on a real first search (2026-10-21):
"300 ft of 3-conductor 500 MCM copper Teck cable" recommended a CAD 8.42 listing, 89% below the median,
as both lowest price and best value. Snippet wording for Gerrie and Lumen is from real listings; the other
suppliers and prices are test fixtures."""

import copy

import pytest
from fastapi.testclient import TestClient

from app import extract as ex
from app.config import Settings
from app.main import create_app
from tests.fakeweb import FakeWeb, jsonld_page, tavily_result
from tests.test_api import research

QUERY = "300 ft of 3-conductor 500 MCM copper Teck cable"
SOLEX = "https://solexpower.ca/products/teck90-cable-copper"

RESULTS = {
    "price": [
        tavily_result("https://gerrie.com/Product/Teck-Cable-TC500-3CU-CUT", "Teck Cable TC500/3CU-CUT",
                      "Teck Cable TC500/3CU-CUT 500 kcmil 3-conductor stranded copper 1kV $251.02 / Meter "
                      "Regular Price: $440.38"),
        tavily_result("https://lumen.ca/en/products/teck90-cables/cab500teck3c1kval",
                      "cab500teck3c1kval sonecable 500 3c teck alum 1kv",
                      "500mcm 3c teck 1kv 90c hlft4 black nual $101.7887 / M"),
        tavily_result(SOLEX, "TECK90 Cable - Copper | Solex Power", "Teck90 armoured cable, copper. Sold by the foot."),
        tavily_result("https://www.ontario-electric-example.ca/500-mcm-3c-teck90", "500 MCM 3C Teck90 Copper Cable",
                      "500 MCM 3C Teck90 copper 1kV. Our price: $76.50/ft. In stock."),
        tavily_result("https://www.wire-example.ca/teck-500kcmil-3c", "Teck 500 kcmil 3-conductor copper",
                      "Teck90 500 kcmil 3-conductor copper $79.90 per foot"),
        tavily_result("https://www.reel-example.ca/500mcm-3c-teck-250ft", "500 MCM 3C Copper Teck - 250 ft reel",
                      "500 MCM 3C copper Teck90, 250 ft reel: $19,500.00"),
        tavily_result("https://nassaunationalcable.com/en-ca/products/500-1c-teck-90",
                      "500-1C Teck 90 Bare Copper Aluminum Interlocked Armored Cable With Ground 1kV",
                      "500 MCM 1C copper Teck $45.00 /FT"),
    ],
    "reviews": [], "wholesale": [], "other": [],
}


def run(tmp_path, solex_title="TECK90 Cable - Copper"):
    fw = FakeWeb(tavily_results=copy.deepcopy(RESULTS))
    fw.pages[SOLEX] = (200, jsonld_page(solex_title, "8.42", "CAD", mpn="TECK90-CU",
                                        extra_text="Sold by the foot. Cut to the length you need."))
    app = create_app(Settings(tavily_api_key="tvly-test-key", database_path=tmp_path / "c.db"),
                     transport=fw.transport())
    with TestClient(app) as c:
        job = research(c, QUERY, depth="quick")
        assert job["status"] == "done", job
        return c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]


def by_host(res, host):
    return next(o for o in res["offers"] if host in o["url"] and o["price"] is not None)


def test_cable_request_compares_per_foot_and_recommends_a_listing_that_states_the_specs(tmp_path):
    res = run(tmp_path)
    assert res["identity"]["order_length"]["feet"] == 300
    assert [s["label"] for s in res["identity"]["specs"]] == ["500 kcmil", "3-conductor", "copper"]

    gerrie = by_host(res, "gerrie.com")
    assert (gerrie["price"], gerrie["per_length"], gerrie["comparable"]) == (251.02, "m", True)
    assert gerrie["per_ft_cad"] == pytest.approx(251.02 / 3.28084, abs=0.01)  # per metre -> per foot
    ontario = by_host(res, "ontario-electric")
    assert (ontario["per_ft_cad"], ontario["order_total_cad"]) == (76.5, 22950.0)

    # excluded, each for its own reason
    lumen = by_host(res, "lumen.ca")
    assert not lumen["comparable"] and any("unit unclear" in r for r in lumen["exclusion_reasons"])
    assert any("aluminum" in r for r in lumen["exclusion_reasons"])
    reel = by_host(res, "reel-example")
    assert not reel["comparable"] and any("priced per item" in r for r in reel["exclusion_reasons"])
    one_c = by_host(res, "nassaunationalcable")
    assert any("1-conductor" in r for r in one_c["exclusion_reasons"])

    # the CAD 8.42 page is sold by the foot but never says 500 kcmil or 3-conductor: not recommended
    solex = by_host(res, "solexpower")
    assert (solex["price"], solex["per_length"], solex["comparable"]) == (8.42, "ft", True)
    assert solex["spec_missing"] == ["500 kcmil", "3-conductor"]
    rec = res["recommendations"]
    assert rec["basis"] == "price per foot (CAD)"
    assert rec["lowest"]["offer_id"] == ontario["id"] and rec["best_value"]["offer_id"] != solex["id"]
    assert rec["lowest"]["order_total_cad"] == 22950.0 and rec["lowest"]["unit"] == "per ft"
    assert any("For 300 ft: about CAD 22,950.00" in e for e in rec["lowest"]["explanation"])
    assert any("don't state all of: 500 kcmil, 3-conductor, copper" in n for n in rec["notes"])


def test_implausibly_low_price_is_set_aside_even_when_it_states_the_specs(tmp_path):
    res = run(tmp_path, solex_title="TECK90 500 kcmil 3C Copper")
    solex = by_host(res, "solexpower")
    assert solex["spec_missing"] == [] and solex["comparable"]
    rec = res["recommendations"]
    assert rec["lowest"]["offer_id"] != solex["id"] and rec["best_value"]["offer_id"] != solex["id"]
    assert any(n.startswith("Set aside 1 listing(s) priced far below the rest") and "89% below" in n
               for n in rec["notes"])
    assert solex["flags"][0].startswith("Not recommended: priced far below")


def test_excel_export_has_length_and_spec_columns(tmp_path):
    from app.export import offers_csv
    res = run(tmp_path)
    head, *rows = offers_csv(res).splitlines()
    for col in ("Priced per (length)", "CAD per foot (calculated)", "CAD for requested length (calculated)",
                "Requested specs not stated", "Spec differences"):
        assert col in head
    assert any("500 kcmil, 3-conductor" in r for r in rows)


@pytest.mark.parametrize("text,unit,qty", [
    ("$251.02 / Meter", "m", 1), ("Our price: $76.50/ft.", "ft", 1), ("Price per foot: $76.50", "ft", 1),
    ("$1,250.00 per 1000 ft", "ft", 1000), ("$1,299.99 /M ft", "ft", 1000), ("$4.20 per metre", "m", 1),
    ("$101.7887 / M", "?", 1), ("$2.99/sq ft", None, None), ("$349.00 each", None, None),
    ("$9.99/m2", None, None),
])
def test_price_units(text, unit, qty):
    [p] = ex.find_prices(text)
    assert (p.per.unit if p.per else None, p.per.qty if p.per else None) == (unit, qty)


@pytest.mark.parametrize("query,specs,length", [
    ("300 ft of 3-conductor 500 MCM copper Teck cable", ["500 kcmil", "3-conductor", "copper"], 300),
    ("12/3 outdoor extension cord 50 ft", ["12 AWG", "3-conductor", "50 ft"], None),
    ("3/8 in grade 70 chain", ["3/8 in"], None),
    ("150 m roll of 4/0 AWG aluminum cable", ["4/0 AWG", "aluminum"], 492.13),
    ("copper or aluminum 2/0 AWG cable", ["2/0 AWG"], None),
    ("nitrile gloves box of 100", [], None),
])
def test_request_specs(query, specs, length):
    got, ln = ex.request_specs(query)
    assert [s["label"] for s in got] == specs
    assert (ln["feet"] if ln else None) == length


@pytest.mark.parametrize("listing,conflict", [
    ("Southwire 25 ft 12/3 outdoor extension cord", "listing says 25 ft; you asked for 50 ft"),
    ("16/3 outdoor extension cord, 50 ft", "listing says 16 AWG; you asked for 12 AWG"),
    ("12/3 SJTW outdoor cord - 25 ft / 50 ft / 100 ft", None),  # several lengths incl. the one asked for
])
def test_spec_conflicts_for_an_everyday_item(listing, conflict):
    req, _ = ex.request_specs("12/3 outdoor extension cord 50 ft")
    got = ex.spec_check(req, listing)["conflicts"]
    assert (got[0] if got else None) == conflict


def test_aluminum_armour_is_not_an_aluminum_conductor():
    req, _ = ex.request_specs("500 MCM 3C copper Teck")
    chk = ex.spec_check(req, "500 MCM 3C bare copper conductors, aluminum interlocked armour")
    assert chk == {"confirmed": ["500 kcmil", "3-conductor", "copper"], "missing": [], "conflicts": []}


def test_comparisons_saved_by_an_older_version_are_reanalysed_when_opened(tmp_path):
    """The user's saved CAD 8.42 result (analysed before these rules) gets corrected without searching again."""
    fw = FakeWeb(tavily_results=copy.deepcopy(RESULTS))
    fw.pages[SOLEX] = (200, jsonld_page("TECK90 Cable - Copper", "8.42", "CAD", mpn="TECK90-CU",
                                        extra_text="Sold by the foot."))
    app = create_app(Settings(tavily_api_key="tvly-test-key", database_path=tmp_path / "o.db"),
                     transport=fw.transport())
    with TestClient(app) as c:
        cid = research(c, QUERY, depth="quick")["comparison_id"]
        db = app.state.db
        old = db.get_comparison(cid)["result"]
        # make it look like a version-1 result: no spec checks, no per-length data, the bad recommendation
        old.pop("analysis_version")
        old["identity"].pop("specs"); old["identity"].pop("order_length")
        for o in old["offers"]:
            for k in ("per_length", "per_length_text", "spec_confirmed", "spec_missing", "spec_conflicts"):
                o.pop(k, None)
        solex_id = next(o["id"] for o in old["offers"] if "solexpower" in o["url"] and o["price"])
        old["recommendations"]["lowest"]["offer_id"] = solex_id
        db.update_comparison_meta(cid, result=old)
        calls_before = len(fw.calls)
        res = c.get(f"/api/comparisons/{cid}").json()["result"]
    assert res["analysis_version"] >= 2 and len(fw.calls) == calls_before  # nothing searched or fetched
    assert res["recommendations"]["lowest"]["offer_id"] != solex_id
    assert db.get_comparison(cid)["result"]["analysis_version"] >= 2   # saved, so it's done once
