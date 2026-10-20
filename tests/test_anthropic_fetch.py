"""Fallback reading through Anthropic web fetch: only for what this server can't connect to, robots.txt obeyed,
page limit, FX parsed by the app. Stub SDK client - no network."""

import json
import re
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from app import fetch
from app.config import Settings
from app.db import Database
from app.fetch import PageFetcher
from app.fx import SOURCE_LABEL, SOURCE_LABEL_VIA, FxService
from app.llm import ClaudeAnalyst
from app.main import create_app
from app.providers.anthropic_fetch import TOOL_TYPE, VIA, AnthropicFetcher, AnthropicFetchError, AnthropicPageReader
from tests.fakeweb import FakeWeb, tavily_result
from tests.test_api import research

UNREACHABLE = "https://www.unreachable-tools.ca/acme-tx-4400"
PAGE_TEXT = ("# Acme TX-4400 Torque Widget | Unreachable Tools\n\n" + "Shop by department. " * 400 +
             "\n\nAcme TX-4400 Torque Widget Our price: $318.50 CAD. In stock, ships in 2 days.")


def now_iso(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(microsecond=0).isoformat()


def fetch_ok(url, text, title=None, retrieved_at=None):
    return NS(stop_reason="end_turn", content=[
        NS(type="server_tool_use", name="web_fetch", input={"url": url}),
        NS(type="web_fetch_tool_result", content=NS(type="web_fetch_result", url=url, retrieved_at=retrieved_at or now_iso(),
                                                    content=NS(type="document", title=title,
                                                               source=NS(type="text", media_type="text/plain", data=text)))),
        NS(type="text", text="done")],
        usage=NS(input_tokens=2600, output_tokens=40, server_tool_use=NS(web_search_requests=0, web_fetch_requests=1)))


def fetch_error(code="url_not_accessible"):
    return NS(stop_reason="end_turn", content=[
        NS(type="web_fetch_tool_result", content=NS(type="web_fetch_tool_result_error", error_code=code))],
        usage=NS(input_tokens=300, output_tokens=10, server_tool_use=NS(web_search_requests=0, web_fetch_requests=1)))


class StubFetchClient:
    """Answers web_fetch requests from a {url: response} map; unknown URLs get an error block."""

    def __init__(self, pages):
        self.pages = pages
        self.urls: list[str] = []
        self.calls: list[dict] = []
        self.messages = self

    async def create(self, **kw):
        self.calls.append(kw)
        assert kw["tools"][0]["type"] == TOOL_TYPE and kw["tools"][0]["max_uses"] == 1
        url = kw["messages"][0]["content"].rsplit(": ", 1)[1]
        self.urls.append(url)
        r = self.pages.get(url)
        if isinstance(r, Exception):
            raise r
        if r is None:
            return fetch_error()
        return fetch_ok(url, r) if isinstance(r, str) else r


def fetcher(pages):
    client = StubFetchClient(pages)
    return AnthropicFetcher("k", model="claude-opus-5-5", base_url="x", client=client), client


# --- AnthropicFetcher ------------------------------------------------------------------------------------------------

async def test_fetcher_returns_document_text_and_counts_usage():
    f, client = fetcher({"https://a.example.com/p": fetch_ok("https://a.example.com/p", "hello", title="Page A",
                                                             retrieved_at="2026-10-20T12:00:00+00:00")})
    doc = await f.fetch("https://a.example.com/p")
    assert (doc.text, doc.title, doc.retrieved_at) == ("hello", "Page A", "2026-10-20T12:00:00+00:00")
    assert f.requests == 1 and f.tokens == {"input_tokens": 2600, "output_tokens": 40}
    assert client.calls[0]["tools"][0]["max_content_tokens"] == 6000


async def test_fetcher_error_block_and_non_text_and_api_errors():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    pdf = fetch_ok("https://a.example.com/x.pdf", "")
    pdf.content[1].content.content.source = NS(type="base64", media_type="application/pdf", data="JVBER")
    f, _ = fetcher({"https://a.example.com/blocked": fetch_error("url_not_allowed"),
                    "https://a.example.com/x.pdf": pdf,
                    "https://a.example.com/down": anthropic.APIConnectionError(request=req)})
    with pytest.raises(AnthropicFetchError, match="url_not_allowed"):
        await f.fetch("https://a.example.com/blocked")
    with pytest.raises(AnthropicFetchError, match="not text"):
        await f.fetch("https://a.example.com/x.pdf")
    with pytest.raises(AnthropicFetchError, match="cannot reach api.anthropic.com"):
        await f.fetch("https://a.example.com/down")


# --- which direct failures count as "our network couldn't connect" --------------------------------------------------

def page_fetcher(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PageFetcher(client, user_agent="test-agent", timeout_s=2, max_bytes=100_000)


async def test_network_failures_are_tagged_but_site_refusals_are_not(monkeypatch):
    async def resolver(host):
        if host == "nodns.example.com":
            raise OSError("Name or service not known")
        return ["10.0.0.5"] if host == "lan.example.com" else ["93.184.216.34"]
    monkeypatch.setattr(fetch, "resolve_host", resolver)

    def handler(req):
        host, path = req.url.host, req.url.path
        if host == "conn.example.com" and path != "/robots.txt":
            raise httpx.ConnectError("refused", request=req)
        if host == "slow.example.com" and path != "/robots.txt":
            raise httpx.ReadTimeout("slow", request=req)
        if host == "norobots.example.com" and path == "/robots.txt":
            raise httpx.ConnectError("refused", request=req)
        if host == "robots500.example.com" and path == "/robots.txt":
            return httpx.Response(500)
        if path == "/robots.txt":
            body = "User-agent: *\nDisallow: /private" if host == "polite.example.com" else ""
            return httpx.Response(200, text=body)
        if host == "forbidden.example.com":
            return httpx.Response(403, text="no")
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})

    pf = page_fetcher(handler)
    tagged = {u: (await pf.fetch(u)) for u in [
        "https://nodns.example.com/p", "https://conn.example.com/p", "https://slow.example.com/p",
        "https://norobots.example.com/p", "https://robots500.example.com/p", "https://forbidden.example.com/p",
        "https://polite.example.com/private/p", "https://lan.example.com/p", "https://ok.example.com/p"]}
    net = {u for u, r in tagged.items() if r.network_failure}
    assert net == {"https://nodns.example.com/p", "https://conn.example.com/p", "https://slow.example.com/p",
                   "https://norobots.example.com/p"}
    assert "could not be reached" in tagged["https://norobots.example.com/p"].error
    assert "robots.txt" in tagged["https://polite.example.com/private/p"].error
    assert tagged["https://ok.example.com/p"].ok


# --- AnthropicPageReader -------------------------------------------------------------------------------------------

async def test_reader_obeys_robots_fetched_via_anthropic():
    f, client = fetcher({"https://shop.example.com/robots.txt": "User-agent: *\nDisallow: /cart\n",
                         "https://shop.example.com/item": "Item text $10.00"})
    reader = AnthropicPageReader(f, user_agent="test-agent", max_pages=4)
    ok = await reader.read("https://shop.example.com/item")
    assert ok.ok and ok.text == "Item text $10.00" and ok.via == VIA
    blocked = await reader.read("https://shop.example.com/cart")
    assert not blocked.ok and "disallowed" in blocked.error
    # robots.txt read once per site; the disallowed page itself is never requested
    assert client.urls == ["https://shop.example.com/robots.txt", "https://shop.example.com/item"]


async def test_reader_skips_page_when_robots_cannot_be_read():
    f, client = fetcher({"https://shop.example.com/item": "Item text"})  # robots.txt -> error block
    reader = AnthropicPageReader(f, user_agent="test-agent", max_pages=4)
    r = await reader.read("https://shop.example.com/item")
    assert not r.ok and "robots.txt could not be read" in r.error
    assert client.urls == ["https://shop.example.com/robots.txt"]


async def test_reader_page_limit_and_safety_check(monkeypatch):
    f, client = fetcher({"https://a.example.com/robots.txt": "", "https://a.example.com/1": "one",
                         "https://a.example.com/2": "two"})
    reader = AnthropicPageReader(f, user_agent="test-agent", max_pages=1)
    assert (await reader.read("https://a.example.com/1")).ok
    second = await reader.read("https://a.example.com/2")
    assert not second.ok and "limit reached" in second.error
    for bad in ["http://10.0.0.8/admin", "https://a.example.com:8443/x", "file:///etc/passwd"]:
        r = await reader.read(bad)
        assert not r.ok and r.error.startswith("Not fetched")
    assert "https://a.example.com/2" not in client.urls and len(client.urls) == 2


# --- FX ------------------------------------------------------------------------------------------------------------

BOC_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1"
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
BOC_JSON = json.dumps({"observations": [{"d": YESTERDAY, "FXUSDCAD": {"v": "1.3925"}}]})


def fx_service(tmp_path, handler, fallback):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return FxService(Database(tmp_path / "fx.db"), client, fallback=fallback)


def refuse(req):
    raise httpx.ConnectError("proxy refused", request=req)


async def test_fx_falls_back_only_when_bank_of_canada_unreachable(tmp_path):
    f, _ = fetcher({BOC_URL: BOC_JSON})
    svc = fx_service(tmp_path, refuse, f)
    rate = await svc.rate("USD")
    assert (rate.rate_to_cad, rate.rate_date, rate.source) == (1.3925, YESTERDAY, SOURCE_LABEL_VIA)
    assert svc.errors == {}

    # The Bank answered (an error) - that answer stands; no fallback
    f2, client2 = fetcher({BOC_URL: BOC_JSON})
    svc2 = fx_service(tmp_path / "b", lambda req: httpx.Response(503, text="maintenance"), f2)
    assert await svc2.rate("EUR") is None and client2.urls == []
    assert "HTTPStatusError" in svc2.errors["EUR"]


async def test_fx_fallback_garbage_is_an_error_not_a_rate(tmp_path):
    f, _ = fetcher({BOC_URL: "<html>Please enable JavaScript</html>"})
    svc = fx_service(tmp_path, refuse, f)
    assert await svc.rate("USD") is None
    assert "also failed" in svc.errors["USD"]
    svc_none = fx_service(tmp_path, refuse, None)
    assert await svc_none.rate("GBP") is None and "ConnectError" in svc_none.errors["GBP"]


async def test_fx_fallback_rejects_an_old_cached_copy(tmp_path):
    old = (date.today() - timedelta(days=30)).isoformat()
    f, _ = fetcher({BOC_URL: json.dumps({"observations": [{"d": old, "FXUSDCAD": {"v": "1.36"}}]})})
    svc = fx_service(tmp_path, refuse, f)
    assert await svc.rate("USD") is None
    assert f"rate is from {old}, 30 days old" in svc.errors["USD"]


async def test_fx_direct_still_preferred(tmp_path):
    f, client = fetcher({BOC_URL: BOC_JSON})
    svc = fx_service(tmp_path, lambda req: httpx.Response(200, json={"observations": [
        {"d": "2026-10-19", "FXUSDCAD": {"v": "1.38"}}]}), f)
    rate = await svc.rate("USD")
    assert rate.source == SOURCE_LABEL and client.urls == []


# --- end to end ------------------------------------------------------------------------------------------------------

class StubAnalyst:
    """AI stub: quotes the price from the page text the fallback delivered."""

    def __init__(self):
        self.calls = []
        self.messages = self
        self.beta = NS(messages=self)

    async def create(self, **kw):
        self.calls.append(kw)
        schema = kw["output_config"]["format"]["schema"]
        prompt = kw["messages"][0]["content"]
        if "search_queries" in schema["properties"]:
            payload = {"product_summary": "torque widget", "brand": "Acme", "category": "tools", "key_specs": [],
                       "search_queries": []}
        else:
            m = re.search(r'<source id="(S\d+)" type="[^"]*" url="' + re.escape(UNREACHABLE) + '"', prompt)
            offers = []
            if m and "Our price: $318.50" in prompt:
                offers.append({"source_id": m.group(1), "product_title": "Acme TX-4400 Torque Widget",
                               "supplier_name": "", "price_text": "$318.50", "currency_stated": "CAD",
                               "pack_quantity": 0, "condition": "new",
                               "evidence_quote": "Acme TX-4400 Torque Widget Our price: $318.50 CAD",
                               "shipping_text": "", "warranty": "", "moq": "", "availability": "In stock"})
            payload = {"offers": offers, "quality": {"praise": [], "criticism": [], "reliability_issues": [],
                                                     "overall_note": ""}, "alternatives": []}
        return NS(stop_reason="end_turn", model="claude-opus-5-5", content=[NS(type="text", text=json.dumps(payload))],
                  usage=NS(input_tokens=500, output_tokens=100))


def test_research_reads_unreachable_page_and_fx_via_fallback(tmp_path):
    fw = FakeWeb()
    fw.tavily_results["price"].append(tavily_result(UNREACHABLE, "Acme TX-4400 Torque Widget - Unreachable Tools",
                                                    "Acme TX-4400 torque widget. In stock."))

    def no_route(req):  # this server can't connect to these hosts
        if req.url.host in ("www.unreachable-tools.ca", "www.bankofcanada.ca"):
            raise httpx.ConnectError("proxy refused", request=req)
        return None
    fw.extra_handlers.append(no_route)
    fetch_client = StubFetchClient({"https://www.unreachable-tools.ca/robots.txt": "User-agent: *\nAllow: /\n",
                                    UNREACHABLE: PAGE_TEXT, BOC_URL: BOC_JSON})
    settings = Settings(tavily_api_key="tvly-test-key", anthropic_api_key="k", database_path=tmp_path / "e.db")
    llm = ClaudeAnalyst(settings, client=StubAnalyst())
    app = create_app(settings, transport=fw.transport(), llm=llm, anthropic_client=fetch_client)
    with TestClient(app) as c:
        job = research(c)
        assert job["status"] == "done", job
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]

    src = next(s for s in res["sources"] if s["url"] == UNREACHABLE)
    assert src["fetch"]["ok"] and src["fetch"]["via"] == VIA and "network error" in src["fetch"]["direct_error"]
    offer = next(o for o in res["offers"] if o["source_id"] == src["id"] and o["price"] is not None)
    assert (offer["price"], offer["currency"], offer["price_basis"]) == (318.5, "CAD", "llm_verified")
    assert res["fetch"]["via_anthropic"] == 1
    # USD listing converted with the Bank of Canada rate fetched through the fallback
    assert res["fx"]["USD"]["source"] == SOURCE_LABEL_VIA and res["fx"]["USD"]["rate_to_cad"] == 1.3925
    assert res["credits"]["anthropic_web_fetches"] == 3 and res["credits"]["llm_usage"]["web_fetch"]["input_tokens"] > 0
    # Sites that answered (403 Grainger, 503 Amazon) are never routed around
    assert not any("grainger" in u or "amazon" in u for u in fetch_client.urls)
    assert set(fetch_client.urls) == {"https://www.unreachable-tools.ca/robots.txt", UNREACHABLE, BOC_URL}


def test_price_from_old_page_copy_is_dated_and_not_strong_evidence(tmp_path):
    fw = FakeWeb()
    fw.tavily_results["price"].append(tavily_result(UNREACHABLE, "Acme TX-4400 Torque Widget - Unreachable Tools",
                                                    "Acme TX-4400 torque widget. In stock."))
    fw.extra_handlers.append(lambda req: (_ for _ in ()).throw(httpx.ConnectError("x", request=req))
                             if req.url.host == "www.unreachable-tools.ca" else None)
    copy_date = now_iso(days_ago=26)
    fetch_client = StubFetchClient({"https://www.unreachable-tools.ca/robots.txt": "",
                                    UNREACHABLE: fetch_ok(UNREACHABLE, PAGE_TEXT, retrieved_at=copy_date)})
    settings = Settings(tavily_api_key="tvly-test-key", anthropic_api_key="k", database_path=tmp_path / "o.db")
    app = create_app(settings, transport=fw.transport(), llm=ClaudeAnalyst(settings, client=StubAnalyst()),
                     anthropic_client=fetch_client)
    with TestClient(app) as c:
        job = research(c)
        assert job["status"] == "done", job
        cid = job["comparison_id"]
        res = c.get(f"/api/comparisons/{cid}").json()["result"]
        hist = c.get(f"/api/comparisons/{cid}/history").json()
    src = next(s for s in res["sources"] if s["url"] == UNREACHABLE)
    offer = next(o for o in res["offers"] if o["source_id"] == src["id"] and o["price_basis"] == "llm_verified")
    assert offer["observed_at"] == copy_date and offer["confidence"] == "low"
    assert any("copy of the page dated" in f and "26 days before" in f for f in offer["flags"])
    # cheapest price at CAD 318.50, but a month-old copy is not recommended as today's price
    assert res["recommendations"]["lowest"]["offer_id"] != offer["id"]
    assert hist is not None


def test_fallback_off_without_key_or_when_disabled(tmp_path):
    assert not Settings(anthropic_api_key=None).fetch_fallback_enabled
    assert not Settings(anthropic_api_key="k", fetch_via_anthropic=False).fetch_fallback_enabled
    fw = FakeWeb()
    fw.extra_handlers.append(lambda req: (_ for _ in ()).throw(httpx.ConnectError("x", request=req))
                             if req.url.host == "www.kmstools.com" else None)
    fetch_client = StubFetchClient({})
    settings = Settings(tavily_api_key="tvly-test-key", anthropic_api_key="k", fetch_via_anthropic=False,
                        database_path=tmp_path / "f.db")
    app = create_app(settings, transport=fw.transport(), llm=ClaudeAnalyst(settings, client=StubAnalyst()),
                     anthropic_client=fetch_client)
    with TestClient(app) as c:
        job = research(c)
        assert job["status"] == "done"
        assert c.get("/api/status").json()["fetch_fallback"] is False
    assert fetch_client.urls == []


def test_pasted_link_unreachable_is_identified_via_fallback(tmp_path):
    fw = FakeWeb()
    fw.extra_handlers.append(lambda req: (_ for _ in ()).throw(httpx.ConnectError("x", request=req))
                             if req.url.host == "www.unreachable-tools.ca" else None)
    page = fetch_ok(UNREACHABLE, PAGE_TEXT, title="Acme TX-4400 Torque Widget | Unreachable Tools")
    fetch_client = StubFetchClient({"https://www.unreachable-tools.ca/robots.txt": "", UNREACHABLE: page})
    settings = Settings(tavily_api_key="tvly-test-key", anthropic_api_key="k", database_path=tmp_path / "u.db")
    app = create_app(settings, transport=fw.transport(), llm=ClaudeAnalyst(settings, client=StubAnalyst()),
                     anthropic_client=fetch_client)
    with TestClient(app) as c:
        job = research(c, UNREACHABLE)
        assert job["status"] == "done", job
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
    ident = res["identity"]
    assert ident["name"].startswith("Acme TX-4400 Torque Widget") and "TX-4400" in ident["model_tokens"]
    assert VIA in ident["source"]
    ref = next(s for s in res["sources"] if "input_url" in s["purposes"])
    assert ref["fetch"]["ok"] and ref["fetch"]["via"] == VIA
    assert fetch_client.urls.count(UNREACHABLE) == 1  # not read a second time as a search result
