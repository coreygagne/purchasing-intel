"""Low-cost defaults: spend estimates, the monthly limit, and saving keys from the setup screen."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.costs import estimate_usd, token_cost
from app.db import Database
from app.main import create_app
from tests.fakeweb import FakeWeb
from tests.test_api import research

LOCAL = {"base_url": "http://127.0.0.1:8000", "client": ("127.0.0.1", 50123)}
KEY = "sk-ant-api03-" + "A" * 40


def test_estimate_from_reported_usage():
    credits = {"anthropic_web_searches": 6.0, "anthropic_search_model": "claude-haiku-5-5",
               "anthropic_search_tokens": {"input_tokens": 80_000, "output_tokens": 8_000},
               "llm_usage": {"plan": {"model": "claude-haiku-5-5", "input_tokens": 1_000, "output_tokens": 500},
                             "extract": {"model": "claude-haiku-5-5", "input_tokens": 19_000, "output_tokens": 5_000}}}
    # 6 searches x US$0.01 + 100k in x $0.10/M + 13.5k out x $0.50/M
    assert estimate_usd(credits) == pytest.approx(0.06 + 0.01 + 0.00675, abs=1e-4)
    assert token_cost("claude-opus-5-5", {"input_tokens": 1_000_000, "output_tokens": 0}) == 4.0
    assert estimate_usd({"llm_usage": {"plan": {"model": "some-future-model", "input_tokens": 5}}}) is None
    assert estimate_usd({"tavily_credits": 3.0}) == 0.0  # Tavily is plan-based, not billed in dollars here


def test_default_model_is_the_low_cost_one(monkeypatch, tmp_path):
    for var in ("PI_ANTHROPIC_MODEL", "PI_MONTHLY_BUDGET_USD"):
        monkeypatch.delenv(var, raising=False)
    s = load_settings(tmp_path / "missing.env")
    assert s.anthropic_model == "claude-haiku-5-5" and s.monthly_budget_usd == 10.0
    assert Settings().anthropic_model == "claude-haiku-5-5"


def test_month_spend_counts_this_month_only(tmp_path):
    db = Database(tmp_path / "s.db")
    a = db.create_search("a", "a", "model", "quick")
    db.finish_search(a, "complete", cost_usd=0.12)
    b = db.create_search("b", "b", "model", "quick")
    db.finish_search(b, "failed", error="x", cost_usd=0.03)  # failed research still cost something
    with db.tx() as c:
        c.execute("UPDATE searches SET created_at = '2001-01-15T00:00:00+00:00' WHERE id = ?", (a,))
    assert db.month_spend() == pytest.approx(0.03)
    assert db.month_spend(datetime(2001, 1, 20, tzinfo=timezone.utc)) == pytest.approx(0.15)


def test_monthly_limit_blocks_new_research_and_status_reports_spend(tmp_path):
    settings = Settings(tavily_api_key="tvly-test-key", anthropic_api_key=KEY, monthly_budget_usd=0.10,
                        database_path=tmp_path / "b.db")
    app = create_app(settings, transport=FakeWeb().transport(), llm=None)
    app.state.engine.llm = None  # keep the AI step out of this test
    db = app.state.db
    sid = db.create_search("earlier", "earlier", "model", "quick")
    db.finish_search(sid, "complete", cost_usd=0.11)
    with TestClient(app) as c:
        st = c.get("/api/status").json()
        assert st["spend"]["month_usd"] == 0.11 and st["spend"]["budget_usd"] == 0.10
        r = c.post("/api/research", json={"query": "Acme TX-4400 torque widget"})
        assert r.status_code == 402 and r.json()["error"] == "budget" and "US$0.10" in r.json()["message"]


def test_no_limit_when_budget_is_zero_or_no_anthropic_key(tmp_path):
    settings = Settings(tavily_api_key="tvly-test-key", monthly_budget_usd=0.01, database_path=tmp_path / "n.db")
    app = create_app(settings, transport=FakeWeb().transport())
    sid = app.state.db.create_search("x", "x", "model", "quick")
    app.state.db.finish_search(sid, "complete", cost_usd=5.0)
    with TestClient(app) as c:
        assert research(c)["status"] == "done"  # Tavily only: nothing billed by Anthropic


def keys_app(tmp_path, checker=None, **kw):
    settings = Settings(database_path=tmp_path / "k.db", env_file=tmp_path / ".env", **kw)
    calls = []

    async def ok(key):
        calls.append(key)
        return None
    return create_app(settings, transport=FakeWeb().transport(), key_checker=checker or ok), settings, calls


def test_saving_a_key_from_this_computer_makes_the_app_ready(tmp_path):
    app, settings, calls = keys_app(tmp_path)
    with TestClient(app, **LOCAL) as c:
        assert c.get("/api/status").json()["ready"] is False
        r = c.post("/api/setup/keys", json={"anthropic_api_key": f"  {KEY} "},
                   headers={"Origin": "http://127.0.0.1:8000"})
        assert r.status_code == 200, r.text
        assert r.json() == {"saved": ["ANTHROPIC_API_KEY"], "ready": True}
        assert KEY not in r.text  # never echoed back
        st = c.get("/api/status").json()
        assert st["ready"] and st["web_search"] == "Anthropic web search" and KEY not in str(st)
    assert calls == [KEY]
    env = (tmp_path / ".env").read_text()
    assert f"ANTHROPIC_API_KEY={KEY}" in env and "PI_ANTHROPIC_MODEL=claude-haiku-5-5" in env  # from the template
    assert app.state.engine.llm is not None and settings.anthropic_api_key == KEY


def test_saving_updates_an_existing_env_line(tmp_path):
    (tmp_path / ".env").write_text("# mine\nTAVILY_API_KEY=old\nPORT=9000\n")
    app, _, _ = keys_app(tmp_path)
    with TestClient(app, **LOCAL) as c:
        assert c.post("/api/setup/keys", json={"tavily_api_key": "tvly-NEWKEY1234567"}).status_code == 200
    assert (tmp_path / ".env").read_text() == "# mine\nTAVILY_API_KEY=tvly-NEWKEY1234567\nPORT=9000\n"


@pytest.mark.parametrize("client_kw,headers,status", [
    ({"base_url": "http://192.168.1.20:8000", "client": ("192.168.1.55", 1)}, {}, 403),   # another computer
    (LOCAL, {"Origin": "https://evil.example"}, 403),                                     # another website
    ({"base_url": "http://evil.example:8000", "client": ("127.0.0.1", 1)}, {}, 403),       # DNS-rebinding host
])
def test_keys_can_only_be_saved_locally(tmp_path, client_kw, headers, status):
    app, _, calls = keys_app(tmp_path)
    with TestClient(app, **client_kw) as c:
        r = c.post("/api/setup/keys", json={"anthropic_api_key": KEY}, headers=headers)
    assert r.status_code == status and calls == [] and not (tmp_path / ".env").exists()


def test_bad_format_or_rejected_key_is_not_saved(tmp_path):
    async def reject(key):
        return "Anthropic rejected this key. Check that you copied all of it."
    app, _, _ = keys_app(tmp_path, checker=reject)
    with TestClient(app, **LOCAL) as c:
        r = c.post("/api/setup/keys", json={"anthropic_api_key": "tvly-wrong-kind-of-key-1234"})
        assert r.status_code == 400 and "sk-ant-" in r.json()["detail"]
        r = c.post("/api/setup/keys", json={"anthropic_api_key": KEY})
        assert r.status_code == 400 and "rejected" in r.json()["detail"]
        assert c.post("/api/setup/keys", json={}).status_code == 400
        r = c.post("/api/setup/keys", content=f'{{"anthropic_api_key": "{KEY}"}}',
                   headers={"Content-Type": "text/plain"})
        assert r.status_code in (415, 422)  # a plain form post from another page can't save keys
    assert not (tmp_path / ".env").exists()
