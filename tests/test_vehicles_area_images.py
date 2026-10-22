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
