"""End-to-end API workflow against the simulated web (tests only)."""

import io
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.config import Settings
from app.main import create_app
from tests.fakeweb import PRODUCT, SERP_SHOPPING, FakeWeb


def make_client(tmp_path, fw: FakeWeb | None = None, **settings_kw) -> TestClient:
    kw = {"tavily_api_key": "tvly-test-key", "database_path": tmp_path / "test.db"} | settings_kw
    app = create_app(Settings(**kw), transport=(fw or FakeWeb()).transport())
    return TestClient(app)


def wait(client: TestClient, job_id: str, timeout: float = 15) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def research(client: TestClient, query: str = PRODUCT, **body) -> dict:
    r = client.post("/api/research", json={"query": query, **body})
    assert r.status_code == 202, r.text
    return wait(client, r.json()["job_id"])


def test_not_configured_shows_setup_and_refuses(tmp_path):
    with make_client(tmp_path, tavily_api_key=None) as c:
        st = c.get("/api/status").json()
        assert st["ready"] is False and st["setup"]["steps"]
        r = c.post("/api/research", json={"query": "anything"})
        assert r.status_code == 503 and r.json()["error"] == "not_configured"
        assert c.get("/api/searches/recent").json() == []  # nothing was run or invented


def test_status_never_exposes_keys(tmp_path):
    with make_client(tmp_path, serpapi_api_key="serp-secret", anthropic_api_key=None) as c:
        body = c.get("/api/status").text
        assert "tvly-test-key" not in body and "serp-secret" not in body


def test_full_workflow_save_reopen_export(tmp_path):
    fw = FakeWeb(serp_body=SERP_SHOPPING)
    with make_client(tmp_path, fw, serpapi_api_key="serp-test") as c:
        job = research(c, quantity=2)
        assert job["status"] == "done", job
        cid = job["comparison_id"]
        comp = c.get(f"/api/comparisons/{cid}").json()
        res = comp["result"]
        assert comp["saved"] is False and comp["last_researched_at"]
        assert res["providers"]["web"] == "Tavily" and res["providers"]["shopping"] == "SerpApi"
        assert all(q["status"] == "ok" for q in res["queries"])
        # recommendations are separate and explained
        rec = res["recommendations"]
        assert rec["lowest"]["supplier"] == "Canadian Tire" and rec["lowest"]["explanation"]
        assert rec["best_value"]["supplier"] == "KMS Tools"
        assert rec["best_value"]["offer_id"] != rec["lowest"]["offer_id"]
        assert any("Costs CAD 10.00" in e for e in rec["best_value"]["explanation"])
        # non-equivalents are flagged, not compared
        by_sup = {o["supplier"]: o for o in res["offers"] if o["price_basis"] != "snippet" or o["supplier"] == "Amazon.com"}
        assert by_sup["Princess Auto"]["comparable"] is False and "condition: refurbished" in by_sup["Princess Auto"]["exclusion_reasons"]
        assert by_sup["The Home Depot Canada"]["match_level"] == "different"
        quotes = [o for o in res["offers"] if o["price_type"] == "quote_required"]
        assert {o["supplier"] for o in quotes} == {"Grainger Canada", "Tenaquip"}
        amazon = by_sup["Amazon.com"]
        assert amazon["currency"] == "USD" and amazon["price_cad"] == round(219 * 1.38, 2)
        assert amazon["fx_date"] == "2026-10-19" and amazon["price_basis"] == "snippet"
        # conflicting prices are surfaced
        assert any(cf["type"] == "price_disagreement" and cf["supplier"] == "KMS Tools" for cf in res["conflicts"])
        # quality: real structured ratings only, issue quotes verbatim with links
        assert {r["supplier"] for r in res["quality"]["ratings"]} == {"Canadian Tire", "KMS Tools"}
        assert any("overheats" in m["quote"] for m in res["quality"]["issue_mentions"])
        # observations persisted
        hist = c.get(f"/api/comparisons/{cid}/history").json()
        assert len(hist["observations"]) >= 5 and hist["chartable"] is False and "Not enough" in hist["reason"]
        # save + rename + reopen
        c.patch(f"/api/comparisons/{cid}", json={"saved": True, "title": "TX-4400 for shop"})
        saved = c.get("/api/comparisons?saved=true").json()
        assert [s["id"] for s in saved] == [cid] and saved[0]["title"] == "TX-4400 for shop"
        # recent searches
        recent = c.get("/api/searches/recent").json()
        assert recent[0]["status"] == "complete" and recent[0]["comparison_id"] == cid
        # exports
        csv_text = c.get(f"/api/comparisons/{cid}/export.csv").text
        assert "KMS Tools" in csv_text and "Advertised price" in csv_text
        xbytes = c.get(f"/api/comparisons/{cid}/export.xlsx").content
        wb = load_workbook(io.BytesIO(xbytes))
        assert wb.sheetnames == ["Summary", "Offers", "Sources", "Quality evidence", "Price history",
                                 "Import & assumptions"]
        assert wb["Offers"].max_row == len(res["offers"]) + 1


def test_assumptions_recalculate_without_new_search(tmp_path):
    fw = FakeWeb()
    with make_client(tmp_path, fw) as c:
        cid = research(c)["comparison_id"]
        calls_before = len(fw.calls)
        comp = c.put(f"/api/comparisons/{cid}/assumptions",
                     json={"assumptions": {"intl_shipping_cad": 25, "duty_pct": 0, "surtax_pct": 25,
                                           "brokerage_cad": 12}}).json()
        assert len(fw.calls) == calls_before  # no new web calls
        amazon = next(o for o in comp["result"]["offers"] if o["supplier"] == "Amazon.com")
        d = amazon["delivered"]
        assert d["kind"] == "landed" and d["label"] == "estimated" and d["complete"]
        # the listing quotes FREE delivery, which takes precedence over the shipping assumption
        assert d["value"] == round(amazon["price_cad"] + 0 + amazon["price_cad"] * 0.25 + 12, 2)
        ship = next(x for x in d["components"] if x["label"] == "Shipping")
        assert ship["basis"] == "quoted"
        kms = next(o for o in comp["result"]["offers"] if o["supplier"] == "KMS Tools" and o["comparable"])
        assert kms["delivered"]["kind"] == "delivered" and kms["delivered"]["label"] == "calculated"
        assert comp["assumptions"]["surtax_pct"] == 25.0


def test_duplicate_detection_and_refresh(tmp_path):
    with make_client(tmp_path) as c:
        cid = research(c)["comparison_id"]
        dup = c.post("/api/research", json={"query": "  acme tx-4400 TORQUE widget "}).json()
        assert dup["duplicate"]["id"] == cid
        # refresh updates the same comparison and adds new observations
        job = research(c, comparison_id=cid)
        assert job["comparison_id"] == cid
        hist = c.get(f"/api/comparisons/{cid}/history").json()
        assert len({o["search_id"] for o in hist["observations"]}) == 2


def test_history_chart_only_with_enough_data(tmp_path):
    with make_client(tmp_path) as c:
        cid = research(c)["comparison_id"]
        db = c.app.state.db
        # Two more real observations of the same product on other days -> chartable
        rows = db.observations(comparison_id=cid)
        base = next(r for r in rows if r["supplier"] == "KMS Tools" and r["price_basis"] == "structured_data")
        for day, price in (("2026-10-01", 345.0), ("2026-10-10", 342.0)):
            db.add_observations([{**{k: base[k] for k in base if k != "id"}, "observed_at": f"{day}T12:00:00+00:00",
                                  "price": price, "price_cad": price}])
        hist = c.get(f"/api/comparisons/{cid}/history").json()
        assert hist["chartable"] is True and len(hist["days"]) >= 2


def test_auth_failure_fails_cleanly(tmp_path):
    with make_client(tmp_path, tavily_api_key="tvly-wrong") as c:
        job = research(c)
        assert job["status"] == "failed" and job["error"]["kind"] == "auth"
        assert "API key rejected" in job["error"]["message"]
        assert c.get("/api/comparisons").json() == []  # nothing saved, nothing invented
        assert c.get("/api/searches/recent").json()[0]["status"] == "failed"


def test_partial_provider_failure_still_completes_and_reports(tmp_path):
    fw = FakeWeb(tavily_fail_purposes={"reviews", "issues"})
    with make_client(tmp_path, fw) as c:
        job = research(c)
        assert job["status"] == "done"
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
        failed = [q for q in res["queries"] if q["status"] == "failed"]
        assert {q["purpose"] for q in failed} == {"reviews", "issues"}
        assert failed[0]["error"]["kind"] == "upstream"
        assert any("independent review" in g for g in res["gaps"])


def test_quota_exhausted_stops_remaining_queries(tmp_path):
    with make_client(tmp_path, FakeWeb(tavily_status=432)) as c:
        job = research(c)
        assert job["status"] == "failed" and job["error"]["kind"] == "quota"


def test_no_results_reports_missing_data(tmp_path):
    fw = FakeWeb(tavily_results={})
    with make_client(tmp_path, fw) as c:
        job = research(c)
        assert job["status"] == "done"
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
        assert res["offers"] == [] and res["recommendations"]["lowest"] is None
        assert any("No published prices" in g for g in res["gaps"])
        assert res["recommendations"]["notes"] == ["No priced listings were found in the search results."]


def test_fx_outage_excludes_foreign_prices_instead_of_guessing(tmp_path):
    with make_client(tmp_path, FakeWeb(fx_ok=False)) as c:
        res = c.get(f"/api/comparisons/{research(c)['comparison_id']}").json()["result"]
        amazon = next(o for o in res["offers"] if o["supplier"] == "Amazon.com")
        assert amazon["price_cad"] is None and not amazon["comparable"]
        assert any("exchange rate" in r for r in amazon["exclusion_reasons"])
        assert any("USD prices could not be converted" in g for g in res["gaps"])


def test_url_input_reads_page_and_uses_it_as_reference(tmp_path):
    fw = FakeWeb()
    with make_client(tmp_path, fw) as c:
        job = research(c, "https://www.kmstools.com/acme-tx-4400-torque-widget")
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
        assert res["identity"]["input_type"] == "url"
        assert res["identity"]["source"] == "product page data (schema.org)"
        assert "TX-4400" in res["identity"]["model_tokens"]
        assert any(o["is_reference"] and o["price"] == 339.99 for o in res["offers"])


def test_url_input_unreadable_page_falls_back_to_url_words(tmp_path):
    fw = FakeWeb()
    fw.pages["https://shop.example.ca/products/acme-tx-4400-torque-widget"] = (403, "no")
    fw.extra_handlers.append(lambda r: __import__("httpx").Response(500, json={"detail": "x"})
                             if r.url.path == "/extract" else None)
    with make_client(tmp_path, fw) as c:
        job = research(c, "https://shop.example.ca/products/acme-tx-4400-torque-widget")
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
        assert "acme tx 4400 torque widget" in res["identity"]["name"]
        assert any("Could not read the page" in g for g in res["gaps"])


def test_robots_txt_disallow_is_respected(tmp_path):
    fw = FakeWeb()
    fw.robots["https://www.kmstools.com"] = (200, "User-agent: *\nDisallow: /")
    with make_client(tmp_path, fw) as c:
        res = c.get(f"/api/comparisons/{research(c)['comparison_id']}").json()["result"]
        assert not any(call.startswith("GET https://www.kmstools.com/acme") for call in fw.calls)
        kms = next(s for s in res["sources"] if s["domain"] == "kmstools.com")
        assert "robots.txt" in kms["fetch"]["error"]


def test_delete_and_404s(tmp_path):
    with make_client(tmp_path) as c:
        cid = research(c)["comparison_id"]
        assert c.delete(f"/api/comparisons/{cid}").status_code == 200
        assert c.get(f"/api/comparisons/{cid}").status_code == 404
        assert c.get("/api/jobs/nope").status_code == 404
        assert c.post("/api/research", json={"query": ""}).status_code == 422


@pytest.mark.parametrize("depth,expected", [("quick", 3), ("standard", 6), ("deep", 8)])
def test_depth_controls_query_count(tmp_path, depth, expected):
    with make_client(tmp_path) as c:
        res = c.get(f"/api/comparisons/{research(c, depth=depth)['comparison_id']}").json()["result"]
        assert len(res["queries"]) == expected
        per = 2 if depth == "deep" else 1
        assert res["credits"]["tavily_credits"] == expected * per


def test_ai_layer_integration_with_verification(tmp_path):
    """AI on (stub client): extra queries used, verified text price added, invented claims dropped."""
    import json as _json
    from types import SimpleNamespace

    from app.llm import ClaudeAnalyst

    class StubMessages:
        def __init__(self):
            self.calls = []

        async def create(self, **kw):
            self.calls.append(kw)
            schema = kw["output_config"]["format"]["schema"]
            if "search_queries" in schema["properties"]:
                payload = {"product_summary": "torque widget", "brand": "Acme", "category": "hand tools",
                           "key_specs": ["drive size", "max torque"],
                           "search_queries": ["Acme TX-4400 Thunder Bay distributor"]}
            else:
                payload = {
                    "offers": [
                        # Tenaquip page text has no price -> this invented price must be rejected
                        {"source_id": "S5", "product_title": "Acme TX-4400", "supplier_name": "Tenaquip",
                         "price_text": "$310.00", "currency_stated": "CAD", "pack_quantity": 0,
                         "condition": "new", "evidence_quote": "Acme TX-4400 $310.00", "shipping_text": "",
                         "warranty": "", "moq": "", "availability": ""}],
                    "quality": {
                        "praise": [{"point": "Reviewers call it well-built and reliable", "source_ids": ["S8"],
                                    "quotes": ["well-built and reliable in our testing"]}],
                        "criticism": [{"point": "Clutch can overheat in continuous use", "source_ids": ["S8"],
                                       "quotes": ["the clutch overheats under continuous use"]}],
                        "reliability_issues": [{"point": "98% failure rate", "source_ids": ["S8"],
                                                "quotes": ["98% of units fail"]}],
                        "overall_note": "Two sources, one professional, one anecdotal."},
                    "alternatives": []}
            return SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                                   content=[SimpleNamespace(type="text", text=_json.dumps(payload))],
                                   usage=SimpleNamespace(input_tokens=500, output_tokens=100))

    stub = StubMessages()
    settings = Settings(tavily_api_key="tvly-test-key", anthropic_api_key="test", database_path=tmp_path / "a.db")
    llm = ClaudeAnalyst(settings, client=SimpleNamespace(messages=stub, beta=SimpleNamespace(messages=stub)))
    app = create_app(settings, transport=FakeWeb().transport(), llm=llm)
    with TestClient(app) as c:
        job = research(c)
        assert job["status"] == "done", job
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
        assert res["providers"]["llm"] == "claude-opus-5-5"
        assert any(q["purpose"] == "ai_suggested" for q in res["queries"])
        assert res["identity"]["key_specs"] == ["drive size", "max torque"]
        summary = res["quality"]["summary"]
        assert [p["point"] for p in summary["praise"]] == ["Reviewers call it well-built and reliable"]
        assert summary["reliability_issues"] == []  # the invented statistic was dropped
        assert summary["verification"]["points_rejected"] == 1
        assert not any(o["price_basis"] == "llm_verified" for o in res["offers"])
        assert "llm_usage" in res["credits"]


def test_spec_differences_from_page_data(tmp_path):
    from tests.fakeweb import jsonld_page
    fw = FakeWeb()
    html = jsonld_page("Acme TX-4400 Torque Widget", "339.99", "CAD")
    fw.pages["https://www.kmstools.com/acme-tx-4400-torque-widget"] = (200, html.replace(
        '"sku": "SKU-998877"', '"sku": "SKU-998877", "additionalProperty": [{"name": "Max torque", "value": "400 ft-lb"}]'))
    fw.pages["https://www.homedepot.ca/product/acme-tx-4400-kit/100200"] = (200, jsonld_page(
        "Acme TX-4400 Torque Widget Kit", "429.00", "CAD").replace(
        '"sku": "SKU-998877"', '"sku": "SKU-1", "additionalProperty": [{"name": "Max torque", "value": "350 ft-lb"}]'))
    with make_client(tmp_path, fw) as c:
        res = c.get(f"/api/comparisons/{research(c)['comparison_id']}").json()["result"]
        [d] = res["spec_differences"]
        assert d["spec"] == "max torque" and {v["value"] for v in d["values"]} == {"400 ft-lb", "350 ft-lb"}


def test_network_outage_reports_network_kind(tmp_path):
    import httpx

    fw = FakeWeb()

    def unreachable(request):
        if request.url.host == "api.tavily.com":
            raise httpx.ConnectError("connection refused", request=request)
        return None
    fw.extra_handlers.append(unreachable)
    with make_client(tmp_path, fw) as c:
        job = research(c)
        assert job["status"] == "failed" and job["error"]["kind"] == "network"
        assert c.get("/api/comparisons").json() == []
