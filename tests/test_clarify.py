"""Clarify-first questions: focused, skippable, stored, and turned into stated assumptions."""

from fastapi.testclient import TestClient

from app import clarify as cl
from app.config import Settings
from app.main import create_app
from tests.fakeweb import PRODUCT, FakeWeb
from tests.test_api import research


def client(tmp_path):
    settings = Settings(tavily_api_key="tvly-test-key", database_path=tmp_path / "c.db")
    return TestClient(create_app(settings, transport=FakeWeb().transport()))


def test_questions_fit_the_request():
    cable = [q["id"] for q in cl.questions("300 MCM 3-conductor teck cable")["questions"]]
    assert cable[:3] == ["length", "voltage", "material"] and len(cable) <= cl.MAX_QUESTIONS
    stated = [q["id"] for q in cl.questions("300 ft of 300 MCM 3-conductor copper teck cable 1000V")["questions"]]
    assert not {"length", "voltage", "material"} & set(stated)  # the request already says
    model = [q["id"] for q in cl.questions("Milwaukee 2767-20")["questions"]]
    assert "intended_use" not in model and "specifics" not in model and model[0] == "quantity"
    vague = [q["id"] for q in cl.questions("pump")["questions"]]
    assert "specifics" in vague
    gloves = [q["id"] for q in cl.all_questions("nitrile gloves box of 100")]
    assert "used_ok" not in gloves and "quantity" not in gloves  # no used PPE; pack size stated
    assert "budget_cad" in [q["id"] for q in cl.all_questions("used forklift")]


def test_answers_are_stored_and_not_asked_again(tmp_path):
    with client(tmp_path) as c:
        first = c.post("/api/clarify", json={"query": PRODUCT}).json()
        ids = [q["id"] for q in first["questions"]]
        assert ids and all(q["why"] for q in first["questions"])
        answers = {ids[0]: "2"} | {i: None for i in ids[1:]}  # answer one, skip the rest
        job = research(c, PRODUCT, answers=answers)
        assert job["status"] == "done", job
        again = c.post("/api/clarify", json={"query": PRODUCT}).json()
        assert not {q["id"] for q in again["questions"]} & set(ids)
        assert again["known"][ids[0]] == "2"
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
        assert res["quantity"] == 2 and res["answers"][ids[0]] == "2"
        assert any("didn't say" in a or "No deadline" in a for a in res["stated_assumptions"])


def test_new_only_and_spec_answers_change_the_research(tmp_path):
    with client(tmp_path) as c:
        job = research(c, "300 MCM 3-conductor teck cable",
                       answers={"length": "300 ft", "voltage": "1000 V", "material": "Copper", "used_ok": "New only"})
        assert job["status"] == "done", job
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
    assert not {"used", "auction", "completed_sales"} & {q["channel"] for q in res["queries"]}
    assert res["plan"]["used_ok"] is False
    assert {"1000 V", "copper"} <= {s["label"] for s in res["identity"]["specs"]}
    assert res["identity"]["order_length"]["feet"] == 300
    assert any(a.startswith("New only") for a in res["stated_assumptions"])


def test_apply_answers_states_assumptions_for_skipped_questions():
    out = cl.apply_answers("300 MCM teck cable", {"length": None, "voltage": "Not sure", "material": "Either"}, None)
    text = " ".join(out["assumptions"])
    assert "Length not given" in text and "Voltage rating not given" in text and "material not fixed" in text
    assert out["spec_text"].strip() == "" and out["used_ok"] is True
