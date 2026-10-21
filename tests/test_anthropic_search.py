"""Anthropic web search provider: real code paths against a stub SDK client (no network)."""

import json
from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import ClaudeAnalyst
from app.main import create_app
from app.providers import provider_status
from app.providers.anthropic_search import AnthropicSearchProvider
from app.providers.base import ProviderError
from tests.fakeweb import PRODUCT, FakeWeb
from tests.test_api import research


def result(url, title, age=None):
    return NS(type="web_search_result", url=url, title=title, encrypted_content="x", page_age=age)


def cite(url, text, title=None):
    return NS(type="web_search_result_location", url=url, cited_text=text, title=title, encrypted_index="i")


def search_response(results, cites, stop="end_turn", model_text="The best deal is $1.00 everywhere (model's own words)"):
    return NS(stop_reason=stop, model="claude-opus-5-5",
              content=[NS(type="server_tool_use", id="t1", name="web_search", input={"query": "q"},
                          to_dict=lambda: {"type": "server_tool_use", "id": "t1", "name": "web_search",
                                           "input": {"query": "q"}}),
                       NS(type="web_search_tool_result", tool_use_id="t1", content=results,
                          to_dict=lambda: {"type": "web_search_tool_result", "tool_use_id": "t1", "content": []}),
                       NS(type="text", text=model_text, citations=cites,
                          to_dict=lambda: {"type": "text", "text": model_text})],
              usage=NS(input_tokens=1200, output_tokens=150, server_tool_use=NS(web_search_requests=1,
                                                                                 web_fetch_requests=0)))


class StubMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


def provider(responses):
    msgs = StubMessages(responses)
    client = NS(messages=msgs, beta=NS(messages=msgs))
    return AnthropicSearchProvider("", model="claude-opus-5-5", base_url="x", client=client), msgs


KMS = "https://www.kmstools.com/acme-tx-4400-torque-widget"
REVIEW = "https://www.protoolreviews.com/acme-tx-4400-review/"


async def test_results_and_verbatim_snippets_only():
    p, msgs = provider([search_response(
        [result(KMS, "Acme TX-4400 - KMS Tools", "2 days ago"), result(REVIEW, "Acme TX-4400 Review")],
        [cite(KMS, "Acme TX-4400 torque widget $349.99 In stock"), cite(KMS, "3-year limited warranty")])])
    hits = await p.search("Acme TX-4400 price", purpose="price", country="canada", max_results=8)
    assert [h.url for h in hits] == [KMS, REVIEW]
    assert hits[0].snippet == "Acme TX-4400 torque widget $349.99 In stock … 3-year limited warranty"
    assert hits[1].snippet == ""                       # nothing cited -> no evidence text, never model prose
    assert "$1.00" not in " ".join(h.snippet for h in hits)
    assert hits[0].published_date == "2 days ago" and hits[0].provider == "Anthropic web search"
    tool = msgs.calls[0]["tools"][0]
    assert tool["type"] == "web_search_20250305" and tool["user_location"]["city"] == "Thunder Bay"
    assert msgs.calls[0]["fallbacks"] == "default"
    assert p.credits_used == 1 and p.tokens["input_tokens"] == 1200


async def test_no_location_for_non_canada_queries():
    p, msgs = provider([search_response([result(KMS, "t")], [])])
    await p.search("Acme TX-4400 review", purpose="reviews")
    assert "user_location" not in msgs.calls[0]["tools"][0]


async def test_pause_turn_is_resumed():
    first = search_response([result(KMS, "KMS")], [cite(KMS, "Acme TX-4400 $349.99")], stop="pause_turn")
    second = search_response([result(REVIEW, "Review")], [cite(REVIEW, "The Acme TX-4400 is well built")])
    p, msgs = provider([first, second])
    hits = await p.search("q", purpose="price")
    assert [h.url for h in hits] == [KMS, REVIEW] and len(msgs.calls) == 2
    assert msgs.calls[1]["messages"][-1]["role"] == "assistant"


@pytest.mark.parametrize("code,kind", [("too_many_requests", "rate_limit"), ("unavailable", "upstream"),
                                       ("query_too_long", "bad_request")])
async def test_search_error_codes(code, kind):
    p, _ = provider([search_response(NS(type="web_search_tool_result_error", error_code=code), [])])
    with pytest.raises(ProviderError) as e:
        await p.search("q", purpose="price")
    assert e.value.kind == kind


async def test_max_uses_exceeded_is_not_an_error():
    p, _ = provider([search_response(NS(type="web_search_tool_result_error", error_code="max_uses_exceeded"),
                                     [cite(KMS, "Acme TX-4400 $349.99")])])
    hits = await p.search("q", purpose="price")
    assert [h.url for h in hits] == [KMS]


@pytest.mark.parametrize("exc_cls,status,kind", [(anthropic.AuthenticationError, 401, "auth"),
                                                 (anthropic.RateLimitError, 429, "rate_limit"),
                                                 (anthropic.InternalServerError, 500, "upstream")])
async def test_api_errors_are_classified(exc_cls, status, kind):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = exc_cls("boom", response=httpx.Response(status, request=req), body=None)
    p, _ = provider([exc])
    with pytest.raises(ProviderError) as e:
        await p.search("q", purpose="price")
    assert e.value.kind == kind


def test_anthropic_key_alone_makes_the_app_ready():
    st = provider_status(Settings(anthropic_api_key="k"))
    assert st["ready"] and st["web_search"] == "Anthropic web search"
    assert provider_status(Settings(anthropic_api_key="k", tavily_api_key="t"))["web_search"] == "Tavily"
    assert provider_status(Settings(anthropic_api_key="k", tavily_api_key="t",
                                    search_provider="anthropic"))["web_search"] == "Anthropic web search"


def test_end_to_end_with_anthropic_search_only(tmp_path):
    """Search + AI both through one (stubbed) Anthropic client; Tavily is never called."""
    class Stub:
        def __init__(self):
            self.calls = []

        async def create(self, **kw):
            self.calls.append(kw)
            if kw.get("tools"):  # a web search call
                q = kw["messages"][0]["content"].splitlines()[0]  # "Search the web for: <query>"
                if q.endswith(" review"):
                    return search_response([result(REVIEW, "Acme TX-4400 Review - Pro Tool Reviews")],
                                           [cite(REVIEW, "The Acme TX-4400 is well-built and reliable in our testing.")])
                return search_response([result(KMS, "Acme TX-4400 Torque Widget - KMS Tools")],
                                       [cite(KMS, "Acme TX-4400 torque widget $349.99 In stock")])
            schema = kw["output_config"]["format"]["schema"]
            if "search_queries" in schema["properties"]:
                payload = {"product_summary": "s", "brand": "Acme", "category": "tools", "key_specs": [],
                           "search_queries": []}
            else:
                payload = {"offers": [], "alternatives": [], "quality": {"praise": [], "criticism": [],
                                                                         "reliability_issues": [], "overall_note": ""}}
            return NS(stop_reason="end_turn", model="m", content=[NS(type="text", text=json.dumps(payload))],
                      usage=NS(input_tokens=10, output_tokens=5))

    stub = Stub()
    client = NS(messages=stub, beta=NS(messages=stub))
    settings = Settings(anthropic_api_key="k", database_path=tmp_path / "a.db")
    fw = FakeWeb()
    app = create_app(settings, transport=fw.transport(), llm=ClaudeAnalyst(settings, client=client),
                     anthropic_client=client)
    with TestClient(app) as c:
        job = research(c, PRODUCT, depth="quick")
        assert job["status"] == "done", job
        res = c.get(f"/api/comparisons/{job['comparison_id']}").json()["result"]
        assert res["providers"]["web"] == "Anthropic web search"
        assert not any("api.tavily.com" in call for call in fw.calls)
        # one billed web search per planned search (the stub reports one each)
        assert res["credits"]["anthropic_web_searches"] == len(res["queries"]) >= 8
        kms = [o for o in res["offers"] if o["supplier"] == "KMS Tools"]
        assert kms and kms[0]["price"] in (339.99, 349.99)   # page data (fake page) or the cited snippet
