"""The AI layer must only keep facts it can verify word-for-word in the sources."""

import json
from types import SimpleNamespace

import anthropic
import httpx

from app.config import Settings
from app.evidence import OfferBuilder, Source
from app.llm import ClaudeAnalyst


def src(sid: str, text: str, title: str = "Page", type_: str = "retailer", country: str | None = "CA") -> Source:
    return Source(id=sid, url=f"https://shop{sid}.ca/item", domain=f"shop{sid}.ca", title=title, snippet="",
                  type=type_, name=f"Shop {sid}", country=country, country_basis="domain suffix", in_directory=False,
                  purposes=["price"], queries=[], provider="Tavily", retrieved_at="2026-10-20T00:00:00+00:00",
                  page_text=text)


class FakeMessages:
    def __init__(self, payload, stop_reason="end_turn", raise_exc=None):
        self.payload, self.stop_reason, self.raise_exc, self.calls = payload, stop_reason, raise_exc, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return SimpleNamespace(stop_reason=self.stop_reason, model="claude-opus-5-5",
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload))],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=200))


def analyst(payload, **kw):
    msgs = FakeMessages(payload, **kw)
    client = SimpleNamespace(messages=msgs, beta=SimpleNamespace(messages=msgs))
    a = ClaudeAnalyst(Settings(anthropic_api_key="test"), client=client)
    return a, msgs


IDENT = SimpleNamespace(name="Acme TX-4400", model_tokens=["TX-4400"], key_specs=[])


def offer(sid, price_text, quote, **extra):
    base = {"source_id": sid, "product_title": "Acme TX-4400", "supplier_name": "", "price_text": price_text,
            "currency_stated": "", "pack_quantity": 0, "condition": "not stated", "evidence_quote": quote,
            "shipping_text": "", "warranty": "", "moq": "", "availability": ""}
    return base | extra


async def test_verified_offer_kept_fabricated_rejected():
    sources = [src("S1", "Acme TX-4400 torque widget. Our price: $312.50 each. Ships in 2 business days."),
               src("S2", "Acme TX-4400 - contact us for details.")]
    payload = {
        "offers": [
            offer("S1", "$312.50", "Our price: $312.50 each", shipping_text="Ships in 2 business days",
                  currency_stated="CAD"),
            offer("S2", "$299.00", "Acme TX-4400 $299.00"),  # not in the source -> rejected
            offer("S1", "$300.00", "Our price: $312.50 each"),  # price not in its quote -> rejected
            offer("S9", "$1.00", "x"),  # unknown source -> rejected
        ],
        "quality": {"praise": [], "criticism": [], "reliability_issues": [], "overall_note": ""},
        "alternatives": [],
    }
    a, msgs = analyst(payload)
    builder = OfferBuilder(["Acme"])
    out = await a.extract(IDENT, sources, builder)
    v = out["verification"]
    assert (v["offers_kept"], v["offers_rejected"], v["points_kept"], v["points_rejected"]) == (1, 3, 0, 0)
    assert set(v["offer_rejection_reasons"]) == {"quote not found in source text", "price not inside its quote",
                                                  "unknown source"}
    [o] = builder.offers
    assert o.price == 312.5 and o.price_basis == "llm_verified" and o.source_id == "S1"
    # "CAD" isn't written in the quoted text, so the currency is inferred from the .ca seller, not trusted from the AI
    assert o.currency == "CAD" and o.currency_basis == "inferred from seller country"
    assert o.shipping_text == "Ships in 2 business days"
    # the request asks for structured JSON; the default model (Haiku 5.5) has no server-side fallback to ask for
    call = msgs.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["model"] == "claude-haiku-5-5" and "fallbacks" not in call and "betas" not in call


async def test_server_side_fallbacks_requested_only_for_models_that_accept_them():
    msgs = FakeMessages({"product_summary": "x", "brand": "", "category": "", "key_specs": [], "search_queries": []})
    client = SimpleNamespace(messages=msgs, beta=SimpleNamespace(messages=msgs))
    opus = ClaudeAnalyst(Settings(anthropic_api_key="test", anthropic_model="claude-opus-5-5"), client=client)
    await opus.plan("Acme TX-4400", "model")
    assert msgs.calls[-1]["fallbacks"] == "default" and msgs.calls[-1]["betas"] == ["server-side-fallback-2026-07-01"]


async def test_quality_points_need_verbatim_quotes():
    sources = [src("S1", "After two years the clutch overheats under continuous use, otherwise solid.",
                   type_="forum / user discussion")]
    payload = {
        "offers": [],
        "quality": {
            "criticism": [{"point": "Clutch overheats in continuous use", "source_ids": ["S1"],
                           "quotes": ["the clutch overheats under continuous use"]}],
            "praise": [{"point": "Rated 4.9 stars by 10,000 users", "source_ids": ["S1"],
                        "quotes": ["4.9 stars from 10,000 users"]}],  # invented -> dropped
            "reliability_issues": [{"point": "Battery fails", "source_ids": ["S7"], "quotes": ["battery"]}],
            "overall_note": "Single anecdotal source.",
        },
        "alternatives": [{"name": "Other widget", "why_considered": "x", "source_id": "S1", "quote": "not present"}],
    }
    a, _ = analyst(payload)
    out = await a.extract(IDENT, sources, OfferBuilder([]))
    q = out["quality"]
    assert [p["point"] for p in q["criticism"]] == ["Clutch overheats in continuous use"]
    assert q["praise"] == [] and q["reliability_issues"] == []
    assert q["verification"]["points_kept"] == 1 and q["verification"]["points_rejected"] == 2
    assert out["alternatives"] == []


async def test_refusal_and_truncation_raise_clear_errors():
    from app.llm import LlmError
    a, _ = analyst({}, stop_reason="refusal")
    try:
        await a.plan("x", "text")
        raise AssertionError("expected LlmError")
    except LlmError as e:
        assert "declined" in str(e)
    a, _ = analyst({}, stop_reason="max_tokens")
    try:
        await a.plan("x", "text")
        raise AssertionError("expected LlmError")
    except LlmError as e:
        assert "cut off" in str(e)


async def test_auth_error_is_reported():
    from app.llm import LlmError
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    a, _ = analyst({}, raise_exc=exc)
    try:
        await a.plan("x", "text")
        raise AssertionError("expected LlmError")
    except LlmError as e:
        assert "rejected the saved API key" in str(e) and "Add or change API keys" in str(e)
    assert a.key_rejected  # later AI steps are skipped and the status badge says so


def test_rejected_ai_key_shows_in_status_and_skips_ai_reading(tmp_path):
    from fastapi.testclient import TestClient
    from types import SimpleNamespace as NS
    from app.config import Settings
    from app.llm import ClaudeAnalyst
    from app.main import create_app
    from tests.fakeweb import FakeWeb
    from tests.test_api import research
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    calls = []

    async def create(**kw):
        calls.append(kw)
        raise anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    stub = NS(create=create)
    settings = Settings(tavily_api_key="tvly-test-key", anthropic_api_key="sk-ant-old", database_path=tmp_path / "a.db")
    app = create_app(settings, transport=FakeWeb().transport(),
                     llm=ClaudeAnalyst(settings, client=NS(messages=stub, beta=NS(messages=stub))))
    with TestClient(app) as c:
        assert c.get("/api/status").json()["ai_key_rejected"] is False
        job = research(c)
        assert job["status"] == "done", job  # searching still works
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
        assert c.get("/api/status").json()["ai_key_rejected"] is True
    assert len(calls) == 1  # the AI reading step wasn't attempted after the planning call was refused
    assert any("AI evidence reading skipped" in g for g in res["gaps"])


async def test_plan_trims_output():
    a, _ = analyst({"product_summary": "s", "brand": "Acme", "category": "tools",
                    "key_specs": ["drive size", "max torque", "", "a", "b", "c", "d"],
                    "search_queries": ["q1", "q2", "q3", "q4"]})
    p = await a.plan("Acme widget", "text")
    assert p["search_queries"] == ["q1", "q2", "q3"] and len(p["key_specs"]) == 6 and p["_usage"]["input_tokens"] == 1000
