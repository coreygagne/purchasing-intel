"""Search by photo (Claude reads the label; nothing it can't read is kept) and clearing the recent list."""

import base64
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.fakeweb import FakeWeb
from tests.test_api import make_client, research
from tests.test_llm import analyst

PNG = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                  "1f15c4890000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082")).decode()
READING = {"what": "Portable two-way radio", "label_text": ["MOTOROLA", "XPR3300", "IP67"], "brand": "Motorola",
           "model_numbers": ["XPR 3300", "XPR 7550"], "search_query": "Motorola XPR 3300 XPR7550 portable radio",
           "confidence": "medium", "notes": "Antenna hides part of the label."}


async def test_photo_reading_keeps_only_what_is_printed():
    a, msgs = analyst(READING)
    out = await a.identify_photo("image/png", "aGVsbG8=")
    sent = msgs.calls[0]["messages"][0]["content"]
    assert sent[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="}}
    assert sent[1]["type"] == "text"
    assert out["model_numbers"] == ["XPR 3300"]  # 'XPR 7550' isn't printed on the photo
    assert out["removed"] == ["XPR 7550"] and "XPR7550" not in out["search_query"]  # listed once
    assert out["search_query"].startswith("Motorola XPR 3300") and out["brand"] == "Motorola"


async def test_photo_reading_drops_a_brand_that_is_not_printed():
    a, _ = analyst(READING | {"brand": "Kenwood", "search_query": "Kenwood radio"})
    out = await a.identify_photo("image/jpeg", "aGVsbG8=")
    assert out["brand"] == "" and "Kenwood" in out["removed"]


def test_photo_endpoint_without_ai_key_offers_google_lens(tmp_path):
    with make_client(tmp_path) as c:
        r = c.post("/api/photo", json={"image": PNG})
        assert r.status_code == 503 and r.json()["google_lens"].startswith("https://lens.google.com")


def test_photo_endpoint_reads_photo_and_counts_spend_but_not_as_a_search(tmp_path):
    a, _ = analyst(READING)
    app = create_app(Settings(tavily_api_key="tvly-test-key", anthropic_api_key="test",
                              database_path=tmp_path / "p.db"), transport=FakeWeb().transport(), llm=a)
    with TestClient(app) as c:
        assert c.post("/api/photo", json={"image": "data:text/plain;base64,aGVsbG8="}).status_code == 400
        r = c.post("/api/photo", json={"image": PNG})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["model_numbers"] == ["XPR 3300"] and body["cost_usd"] > 0 and "check it" in body["label"]
        assert c.get("/api/searches/recent").json() == []  # a photo reading isn't a search
        assert c.get("/api/status").json()["spend"]["month_usd"] >= 0  # counted (rounded to cents)
        assert app.state.db.month_spend() > 0


def test_clear_recent_searches_keeps_saved_comparisons_and_spend(tmp_path):
    with make_client(tmp_path) as c:
        job = research(c)
        cid = job["comparison_id"]
        c.patch(f"/api/comparisons/{cid}", json={"saved": True, "title": "Keep me"})
        db = c.app.state.db
        db.finish_search(1, "done", cid, cost_usd=0.02)
        assert len(c.get("/api/searches/recent").json()) == 1
        assert c.delete("/api/searches/recent").json()["cleared"] == 1
        assert c.get("/api/searches/recent").json() == []
        assert [x["title"] for x in c.get("/api/comparisons?saved=true").json()] == ["Keep me"]
        assert db.month_spend() == 0.02  # the month's spend still counts cleared searches


def test_lists_show_each_comparisons_outcome(tmp_path):
    with make_client(tmp_path) as c:
        job = research(c)
        recent = c.get("/api/searches/recent").json()[0]
        assert recent["verdict"]["kind"] in ("ok", "hold") and recent["verdict"]["text"]
        cid = job["comparison_id"]
        c.patch(f"/api/comparisons/{cid}", json={"saved": True})
        saved = c.get("/api/comparisons?saved=true").json()[0]
        assert saved["verdict"] == recent["verdict"]


async def test_typed_words_lead_and_the_photo_adds_detail():
    a, msgs = analyst(READING | {"model_numbers": [], "search_query": "portable radio with antenna",
                                 "label_text": ["IP67"], "brand": ""})
    out = await a.identify_photo("image/png", "aGVsbG8=", context="Motorola R7 two-way radio")
    prompt = msgs.calls[0]["messages"][0]["content"][1]["text"]
    assert "<their_words>Motorola R7 two-way radio</their_words>" in prompt
    assert out["search_query"].startswith("Motorola R7 two-way radio")  # their words lead
    assert out["context"] == "Motorola R7 two-way radio"


async def test_model_number_typed_is_kept_even_if_the_photo_does_not_show_it():
    a, _ = analyst(READING | {"model_numbers": [], "label_text": [], "brand": "",
                              "search_query": "f250 hi-rail pickup white crew cab"})
    out = await a.identify_photo("image/png", "aGVsbG8=", context="f250 hi-rail")
    assert "f250" in out["search_query"].lower() and "f250" not in [r.lower() for r in out["removed"]]


def test_photo_notes_go_into_quote_requests():
    from app.rfq import rfq_drafts
    vendor = {"id": "V1", "name": "Rail Trucks Ltd", "quote_opportunity": True, "type": "industrial distributor",
              "emails": [], "phones": [], "tier_label": "Thunder Bay", "quote_reasons": [], "website": None}
    body = rfq_drafts([vendor], {"name": "hi-rail pickup truck"}, 1, None,
                      {"photo_notes": "white crew-cab pickup with rail gear; label reads HY-RAIL"}, None, "vehicle")[0]["body"]
    assert "From our reference photo: white crew-cab pickup with rail gear" in body
