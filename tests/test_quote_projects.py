"""A multi-item project cannot call unlike or incomplete quotes comparable."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.quote_projects import evaluate, rfq_text


def example():
    return {"title": "Ore dock power", "ship_to": "Thunder Bay, ON",
            "items": [{"id": "cable", "part": "TK500-03", "description": "3C 500 kcmil Cu 1 kV TECK",
                       "quantity": 92, "unit": "m"},
                      {"id": "splice", "part": "5734C", "description": "1 kV 3C cold shrink splice",
                       "quantity": 1, "unit": "each"}],
            "suppliers": [{"name": "One", "valid_until": "2099-01-01", "shipping_cad": 0,
                           "specs_confirmed": True, "lines": {"cable": {"unit_price_cad": 284.40},
                                                               "splice": {"unit_price_cad": 1300}}},
                          {"name": "Two", "valid_until": "2099-01-01", "shipping_cad": None,
                           "specs_confirmed": True, "lines": {"cable": {"unit_price_cad": 280}}},
                          {"name": "Three", "valid_until": "2026-10-10", "shipping_cad": 0,
                           "specs_confirmed": True, "lines": {"cable": {"unit_price_cad": 270},
                                                               "splice": {"unit_price_cad": 1200}}}]}


def test_complete_current_delivered_only_and_full_rfq():
    result = evaluate(example())
    assert [s["name"] for s in result["comparable_suppliers"]] == ["One"]
    assert result["comparable_suppliers"][0]["total_cad"] == 27464.80
    assert "1 item(s) not priced" in result["suppliers"][1]["issues"]
    assert "Thunder Bay shipping/pickup unconfirmed" in result["suppliers"][1]["issues"]
    assert "price expired" in result["suppliers"][2]["issues"]
    draft = rfq_text(example())
    assert "92 m" in draft and "TK500-03" in draft and "freight" in draft


def test_project_api_roundtrip_and_validation(tmp_path):
    app = create_app(Settings(database_path=tmp_path / "project.db"))
    with TestClient(app) as client:
        response = client.post("/api/quote-projects", json=example())
        assert response.status_code == 200, response.text
        pid = response.json()["id"]
        assert client.get("/api/quote-projects").json()[0]["id"] == pid
        body = client.get(f"/api/quote-projects/{pid}").json()
        assert len(body["items"]) == 2 and len(body["suppliers"]) == 3
        body["suppliers"][0]["lines"]["splice"]["unit_price_cad"] = 1000
        response = client.put(f"/api/quote-projects/{pid}", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["comparable_suppliers"][0]["total_cad"] == 27164.80
        bad = example(); bad["items"].append(bad["items"][0])
        assert client.post("/api/quote-projects", json=bad).status_code == 400
        bad = example(); bad["suppliers"].append({"name": " one ", "lines": {}})
        assert client.post("/api/quote-projects", json=bad).status_code == 400
