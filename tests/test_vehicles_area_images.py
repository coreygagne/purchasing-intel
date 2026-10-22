"""Vehicle searches find vehicles (not parts), Thunder Bay / outside Thunder Bay searching, listing pictures."""

from app import discovery as disc
from app import extract as ex
from app.evidence import Source
from tests.test_api import make_client, research
from tests.test_listing_pages import _offer, _run


def test_model_numbers_match_however_they_are_written():
    assert ex.match_offer(["f250"], "2024 Ford F-250 CREW CAB 4X4").level == "exact"
    assert ex.match_offer(["f250"], "Ford F 250 XLT").level == "exact"
    assert ex.match_offer(["f250"], "Ford F-150 Lariat").level == "different"
    assert ex.match_offer(["2767-20"], "Milwaukee 2767-22 kit").level == "variant"  # still told apart


def test_either_or_request_matches_either_model():
    tokens = ["f250", "f350"]
    assert ex.alternative_models("f250 or f350 truck", tokens)
    assert ex.match_offer(tokens, "2023 Ford F 350 CREW CAB", any_of=True).level == "exact"
    assert ex.match_offer(tokens, "2023 Ford F 350 CREW CAB").level == "variant"  # without 'or' both are needed
    assert disc.request_variants("f250 or f350 truck") == ["f250 truck", "f350 truck"]


def test_vehicle_parts_are_told_apart_from_vehicles():
    for part in ("Front Bumper Ford F-250/F-350 Super Duty 2WD/4WD", "6 Inch Lift Kit Ford F-250/F-350 Super Duty 4WD",
                 "2017-2022 F250 Leveling Kit", "Truck & Jeep Parts - Ford - F250 / F350 Superduty"):
        assert ex.vehicle_part(part), part
    for truck in ("2024 Ford F-250 CREW CAB 4X4 8FT LONG BOX", "2019 Ford F-350 XLT tow mirrors, 120,000 km",
                  "Ford F-350 Super Duty for Sale in Ontario"):
        assert ex.vehicle_part(truck) is None, truck


def test_vehicle_plan_searches_for_vehicles_not_wholesale():
    plan = disc.initial_plan("f250 or f350 truck", disc.categorize("f250 or f350 truck"), "standard")
    queries = [pq.query for pq in plan]
    assert "f250 truck for sale Thunder Bay" in queries and "f350 truck for sale Thunder Bay" in queries
    assert not any(pq.channel == "wholesale" or "wholesale" in pq.query for pq in plan)


def test_vehicle_listings_leave_out_parts_and_other_models():
    offers = [_offer(1, 68800.0, "2024 Ford F-250 CREW CAB 4X4 8FT LONG BOX", supplier_type="unknown"),
              _offer(2, 1399.95, "Front Bumper Ford F-250/F-350 Super Duty 2WD/4WD", supplier_type="retailer"),
              _offer(3, 16995.0, "2017 Chevrolet Trax", supplier_type="unknown"),
              _offer(4, 72800.0, "2025 Ford F-350 Super Duty CREW CAB 4X4", supplier_type="unknown")]
    res = _run("f250 or f350 truck", offers, "vehicle")
    shown = {p["offer_id"] for p in res["recommendation"]["listing_pages"]}
    assert shown == {"O1", "O4"}  # the trucks asked for; not the bumper or the Chevrolet
    by = {o["id"]: o for o in res["offers"]}
    assert by["O2"]["match_level"] == "compatible" and "part or accessory" in by["O2"]["match_notes"][0]


def test_scope_plan_keeps_the_chosen_area():
    plan = disc.initial_plan("Milwaukee 2767-20", disc.categorize("Milwaukee 2767-20"), "standard")
    local = disc.scope_plan(plan, "local")
    assert local and all(pq.market == "local" or pq.channel in ("reviews", "issues", "specs") for pq in local)
    outside = disc.scope_plan(plan, "outside")
    assert outside and not any(pq.market == "local" for pq in outside)


def test_thunder_bay_only_compares_only_thunder_bay_sellers():
    offers = [_offer(1, 300.0, "Acme TX-4400", supplier_type="retailer", source_id="S1"),
              _offer(2, 280.0, "Acme TX-4400", supplier_type="retailer", source_id="S2")]
    common = dict(domain="x", snippet="", type="retailer", name="x", country="CA", country_basis="x",
                  in_directory=False, purposes=["price"], queries=[], provider="t",
                  retrieved_at="2026-10-22T00:00:00+00:00")
    sources = [Source(id="S1", url="https://s1.example", title="a", location={"tier": "local"}, **common),
               Source(id="S2", url="https://s2.example", title="b", location={"tier": "canada"}, **common)]
    from app.research import analyze
    res = analyze(identity={"name": "Acme TX-4400", "input_type": "text", "model_tokens": ["TX-4400"]},
                  sources=sources, offers=offers, fx={}, assumptions={}, home_province="ON",
                  meta={"query": "x", "researched_at": "2026-10-22T12:00:00+00:00", "area": "local",
                        "plan": {"category": "tools"}})
    by = {o["id"]: o for o in res["offers"]}
    assert by["O1"]["comparable"] and not by["O2"]["comparable"]
    assert any("Thunder Bay only" in r for r in by["O2"]["exclusion_reasons"])


def test_area_is_its_own_search_and_is_recorded(tmp_path):
    with make_client(tmp_path) as c:
        job = research(c, area="local")
        assert job["status"] == "done", job
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
        assert res["area"] == "local"
        assert all(q["market"] == "local" or q["channel"] in ("reviews", "issues", "specs") for q in res["queries"]
                   if q.get("purpose") != "local_map")
        r = c.post("/api/research", json={"query": res["query"], "area": "both"})
        assert "duplicate" not in r.json()  # the same words searched everywhere is a different search


def test_page_picture_is_found_and_safe():
    html = ('<meta property="og:image" content="/img/f250.jpg"><script type="application/ld+json">'
            '{"@type": "Car", "image": ["https://cdn.dealer.example/f250.jpg"]}</script>')
    assert ex.page_image(html, "https://dealer.example/listing/1") == "https://cdn.dealer.example/f250.jpg"
    assert ex.page_image('<meta property="og:image" content="/a.jpg">', "https://d.example/x") == "https://d.example/a.jpg"
    assert ex.page_image('<meta property="og:image" content="javascript:alert(1)">', "https://d.example/x") is None


def test_listing_picture_reaches_the_offer():
    common = dict(domain="x", snippet="", type="retailer", name="x", country="CA", country_basis="x",
                  in_directory=False, purposes=["price"], queries=[], provider="t",
                  retrieved_at="2026-10-22T00:00:00+00:00")
    src = Source(id="S1", url="https://s1.example", title="a", image="https://s1.example/p.jpg", **common)
    from app.research import analyze
    res = analyze(identity={"name": "Acme TX-4400", "input_type": "text", "model_tokens": ["TX-4400"]},
                  sources=[src], offers=[_offer(1, 300.0, "Acme TX-4400", source_id="S1", supplier_type="retailer")],
                  fx={}, assumptions={}, home_province="ON",
                  meta={"query": "x", "researched_at": "2026-10-22T12:00:00+00:00", "plan": {"category": "tools"}})
    assert res["offers"][0]["image"] == "https://s1.example/p.jpg"


def test_toy_trucks_are_not_trucks():
    assert ex.vehicle_toy("Greenlight Hollywood Yellowstone 1978 Ford F-250 Chase 1:64 Diecast")
    assert ex.vehicle_toy("Matchbox 2017 Ford F-350 SKYJACKER")
    assert ex.vehicle_toy("Ford F-250 Super Duty XL 8 ft box") is None
    assert ex.vehicle_toy("2019 Toyota Tacoma") is None  # "Toyota" isn't "toy"
    assert ex.vehicle_part("Ford F-250/F-350 Adventure Edition Aluminum Truck Cap")
    res = _run("f250 or f350 truck", [_offer(1, 182.4, "Greenlight BIGFOOT 1:18 Scale 1974 Ford F-250 Diecast"),
                                       _offer(2, 15995.0, "Ford F-250 Super Duty XL 8 ft box", supplier_type="unknown")],
               "vehicle")
    assert {p["offer_id"] for p in res["recommendation"]["listing_pages"]} == {"O2"}


def test_odometer_and_hours_are_read():
    assert ex.odometer_km("2019 F-150, 161,420 km, one owner") == 161420
    assert ex.odometer_km("98,000 miles") == round(98000 * 1.609344)
    assert ex.machine_hours("Toyota 8FBCU25 5806 Hours") == 5806
    assert ex.odometer_km("8 ft box") is None


def _filtered(filters, offers, category="vehicle", name="f250 or f350 truck"):
    from app.research import analyze
    return analyze(identity={"name": name, "input_type": "text", "model_tokens": ex.model_tokens(name)}, sources=[],
                   offers=offers, fx={}, assumptions={}, home_province="ON",
                   meta={"query": name, "researched_at": "2026-10-22T12:00:00+00:00", "filters": filters,
                         "plan": {"category": category}})


def test_filters_leave_out_what_is_stated_outside_and_mark_what_is_not_stated():
    offers = [_offer(1, 15995.0, "2012 Ford F-250 Super Duty XL, 240,000 km", supplier_type="unknown"),
              _offer(2, 68800.0, "2024 Ford F-250 CREW CAB 4X4", supplier_type="unknown"),
              _offer(3, 29999.0, "2019 Ford F-350 XLT, 98,000 km", supplier_type="unknown"),
              _offer(4, 31000.0, "Ford F-350 Super Duty XLT", supplier_type="unknown")]
    res = _filtered({"price_min": 10000, "price_max": 60000, "year_min": 2015, "km_max": 150000}, offers)
    by = {o["id"]: o for o in res["offers"]}
    assert any("year outside your filter" in r for r in by["O1"]["exclusion_reasons"])
    assert any("price range" in r for r in by["O2"]["exclusion_reasons"])
    assert by["O3"]["facts"] == {"year": 2019, "km": 98000}
    assert by["O4"]["facts"]["not_stated"] == ["year", "kilometres"]
    shown = {p["offer_id"] for p in res["recommendation"]["listing_pages"]}
    assert shown == {"O3", "O4"}  # O4 stays in: it doesn't state the year or km


def test_price_range_steers_the_recommendation():
    offers = [_offer(i, p, "Acme TX-4400", supplier_type="retailer", price_basis="structured_data")
              for i, p in ((1, 250.0), (2, 320.0), (3, 340.0))]
    res = _filtered({"price_min": 300}, offers, category="tools", name="Acme TX-4400")
    assert res["recommendations"]["lowest"]["offer_id"] == "O2"


def test_filters_are_sent_saved_and_can_be_changed_without_searching(tmp_path):
    with make_client(tmp_path) as c:
        job = research(c, filters={"price_max": 300})
        cid = job["comparison_id"]
        res = c.get(f"/api/comparisons/{cid}").json()["result"]
        assert res["filters"] == {"price_max": 300.0}
        before = [r["id"] for r in c.get("/api/searches/recent").json()]
        r = c.put(f"/api/comparisons/{cid}/filters", json={"price_min": 330})
        assert r.status_code == 200 and r.json()["result"]["filters"] == {"price_min": 330.0}
        assert [r["id"] for r in c.get("/api/searches/recent").json()] == before  # no new search was run
        assert c.put(f"/api/comparisons/{cid}/filters", json={"year_min": 1500}).status_code == 422


def test_defining_words_must_be_in_the_listing():
    assert ex.qualifier_words("hi-rail pickup trucks", []) == ["hi-rail"]
    assert ex.qualifier_words("f250 or f350 truck", ["f250", "f350"]) == []
    q = ["hi-rail"]
    assert ex.missing_qualifiers("2018 Ford F-350 Hy-Rail truck", q) == []
    assert ex.missing_qualifiers("F-550 with Harsco rail gear", q) == []
    assert ex.missing_qualifiers("2026 Ram 1500 Rebel 4x4 Crew Cab", q) == ["hi-rail"]
    assert ex.missing_qualifiers("Used Electric Lift Truck", ["forklift"]) == []  # trade spelling


def test_hi_rail_search_shows_hi_rail_trucks_not_pickups_parts_news_or_rentals():
    offers = [_offer(1, 64990.0, "2026 Ram 1500 Rebel 4x4 Crew Cab 5'7\" Box", supplier_type="unknown"),
              _offer(2, 12.67, "579.1112 by Automann Magnetic Pick-Up Tool 15lb", supplier_type="unknown"),
              _offer(3, 46.0, "Custom Truck makes Canadian acquisition - International Rental News", supplier_type="unknown"),
              _offer(4, 110.0, "Hi-Rail Truck Rentals - Winnipeg - T & B Fleet Services", supplier_type="unknown"),
              _offer(5, 89500.0, "2019 Ford F-350 XL Hi-Rail Pickup, 120,000 km", supplier_type="unknown")]
    res = _run("hi-rail pickup trucks", offers, "vehicle")
    plain = res["recommendation"]
    assert {p["offer_id"] for p in plain["listing_pages"]} == {"O5"}
    by = {o["id"]: o for o in res["offers"]}
    assert by["O1"]["match_level"] == "different" and "hi-rail" in by["O1"]["match_notes"][0]
    assert any("rental or lease rate" in r for r in by["O4"]["exclusion_reasons"])
    assert any("Rentals were found" in n and "T & B Fleet" in n for n in plain["needed"])


def test_no_matching_listings_says_what_to_do():
    res = _run("hi-rail pickup trucks", [_offer(1, 64990.0, "2026 Ram 1500 Rebel 4x4", supplier_type="unknown")],
               "vehicle")
    assert res["recommendation"]["listing_pages"] == []
    assert "No listing found mentions hi-rail" in res["recommendation"]["needed"][0]


def test_scale_models_axle_lots_and_acquisition_news_are_not_trucks():
    assert ex.vehicle_toy("Atlas HO Ford F-350 Hi-Railer Pickup Truck") == "HO"
    assert ex.vehicle_toy("2019 Ford F-350 SD 4x4 Crew Cab HI-Rail Pickup") is None
    assert ex.vehicle_part("Quantity of (2) Ford Pickup Hi-Rail Axles for Sale in BC")
    assert ex.vehicle_part("2025 Ford F350 4x4 Hi-Rail Pickup Truck") is None
    assert ex.article_words("Custom Truck One Source Acquires HiRail Leasing Group")
    assert ex.rental_words("Hi-Rail Trucks for Rent") and ex.rental_words("2025 Ford F350 Hi-Rail Pickup Truck") is None
