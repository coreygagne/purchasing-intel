"""Ads, listing pages, value estimates and model years: what the app may and may not recommend."""

from app import extract as ex
from app.evidence import Offer, page_kind
from app.research import analyze


def _offer(i, price, title, url=None, supplier_type="classifieds / used", **kw) -> Offer:
    base = dict(id=f"O{i}", source_id=None, url=url or f"https://s{i}.example/listing/{1000000 + i}",
                supplier=f"S{i}", supplier_domain=f"s{i}.example", supplier_type=supplier_type,
                supplier_in_directory=False, country="CA", country_basis="x", product_title=title, price=price,
                price_high=None, currency="CAD", currency_basis="stated", price_text=f"${price}", price_type="listed",
                price_basis="snippet", evidence_quote=f"{title} ${price}", observed_at="2026-10-22T00:00:00+00:00",
                provider="t")
    base.update(kw)
    return Offer(**base)


def _run(name, offers, category):
    return analyze(identity={"name": name, "input_type": "text", "model_tokens": ex.model_tokens(name)}, sources=[],
                   offers=offers, fx={}, assumptions={}, home_province="ON",
                   meta={"query": name, "quantity": None, "researched_at": "2026-10-22T12:00:00+00:00",
                         "plan": {"category": category}})


def test_used_words_mileage_and_hours():
    assert ex.used_evidence("USED Hyster 5,000 lb forklift") == "USED"
    assert ex.used_evidence("2019 F-150, 161,420 km, one owner") == "161,420 km"
    assert ex.used_evidence("Toyota 8FBCU25 5806 Hours", machinery=True) == "5806 Hours"
    assert ex.used_evidence("Toyota 8FBCU25 5806 Hours") is None  # hours only count for machinery
    assert ex.used_evidence("Gloves used by professionals") is None


def test_model_years_and_between_ranges():
    assert ex.requested_model_year("2019 Ford F-150 pickup") == 2019
    assert ex.model_years("Ford 2018 F-150 4x4 - Supercrew Xlt") == [2018]
    assert ex.model_years("Milwaukee 2767-20") == [] and ex.model_years("2,019 km") == []
    assert ex.requested_model_year("2015-2018 F-150") is None
    p = ex.find_prices("2019 Ford F-150 value ranges between $13176 and $33686 in Canada.")
    assert [(x.amount, x.high) for x in p] == [(13176.0, 33686.0)]


def test_page_kind():
    assert page_kind("118 ads for 5000 lb forklift in All Categories in Ontario", "https://x.ca/b-forklift")[0] == \
        "results"
    assert page_kind("More than 180 in Forklifts & Trucks", "https://ebay.example/b/forklifts")[0] == "results"
    assert page_kind("2019 Ford F-150 Value Canada", "https://www.clutch.ca/car-value-calculator/2019-ford-f-150")[0] \
        == "valuation"
    srp = ("2019 Ford F-150 for Sale in Ontario", "https://www.autotrader.ca/cars/ford/f-150/my_2019/reg_on")
    assert page_kind(*srp, ads=True)[0] == "results"
    assert page_kind(*srp) is None  # "for sale in" only marks inventory pages for vehicles, equipment and ads
    one = ("Ford 2018 F-150 4x4 - Supercrew Xlt in Thunder Bay",
           "https://www.lakeheadmotors.ca/used/2018-Ford-F_150-id14472759.html")
    assert page_kind(*one, ads=True) is None
    assert page_kind("Milwaukee 2767-20 M18 FUEL Impact Wrench", "https://shop.example/p/2767-20") is None


def test_vehicle_request_is_judged_not_ranked():
    offers = [
        _offer(1, 26899.0, "2019 Ford F-150 XLT 161,423 km"),
        _offer(2, 27995.0, "Ford 2018 F-150 4x4 - Supercrew Xlt"),  # a different model year
        _offer(3, 24290.0, "2019 Ford F-150 for Sale in Ontario", url="https://autotrader.example/cars/f-150/reg_on"),
        _offer(4, 13176.0, "2019 Ford F-150 Value Canada", url="https://clutch.example/car-value-calculator/f-150",
               supplier_type="unknown", price_type="range", price_high=33686.0),
    ]
    res = _run("2019 Ford F-150 pickup", offers, "vehicle")
    by = {o["id"]: o for o in res["offers"]}
    assert res["recommendations"]["lowest"] is None and res["recommendations"]["best_value"] is None
    plain = res["recommendation"]
    assert plain["judge"] and plain["lead"] is None and plain["picks"] == {}
    assert any("2019 model is compared with used listings" in n for n in res["recommendations"]["notes"])
    assert by["O1"]["condition"] == "used" and "model year 2019" in by["O1"]["spec_confirmed"]
    assert any("2018" in c for c in by["O2"]["spec_conflicts"])
    assert by["O3"]["page_kind"] == "results"
    assert any(p["offer_id"] == "O3" for p in plain["listing_pages"])
    mv = res["market_value"]
    assert [v["offer_id"] for v in mv["valuations"]] == ["O4"]  # a value estimate, never an asking price
    assert all(ob["offer_id"] != "O4" for g in mv["groups"] for ob in g["observations"])


def test_used_pick_prefers_fixed_price_over_opening_bid():
    offers = [_offer(i, p, "Acme TX-4400 compressor", supplier_type="retailer", price_basis="structured_data")
              for i, p in ((1, 900.0), (2, 950.0), (3, 1000.0))]
    offers += [_offer(4, 11.25, "Used Acme TX-4400", supplier_type="auction / surplus", condition="used",
                      price_kind="current_bid"),
               _offer(5, 600.0, "Used Acme TX-4400", condition="used")]
    res = _run("Acme TX-4400", offers, "general")
    assert res["recommendation"]["picks"].get("used") == "O5"
