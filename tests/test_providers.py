import httpx
import pytest

from app.providers.base import ProviderError
from app.providers.serpapi import SerpApiProvider
from app.providers.tavily import TavilyProvider
from tests.fakeweb import SERP_SHOPPING, FakeWeb


def tavily(fw: FakeWeb, key: str = "tvly-test-key") -> TavilyProvider:
    return TavilyProvider(key, httpx.AsyncClient(transport=fw.transport()))


async def test_tavily_success_parses_results_and_counts_credits():
    fw = FakeWeb()
    p = tavily(fw)
    hits = await p.search("Acme TX-4400 torque widget price", purpose="price", country="canada")
    assert [h.url for h in hits][:2] == ["https://www.grainger.ca/en/product/ACME-TX-4400",
                                          "https://www.kmstools.com/acme-tx-4400-torque-widget"]
    assert hits[1].snippet.startswith("Acme TX-4400") and hits[0].rank == 1
    assert p.credits_used == 1.0
    await p.search("x price", purpose="price", depth="advanced")
    assert p.credits_used == 3.0


@pytest.mark.parametrize("status,kind", [(432, "quota"), (433, "quota"), (429, "rate_limit"), (500, "upstream"),
                                         (400, "bad_request")])
async def test_tavily_error_statuses(status, kind):
    p = tavily(FakeWeb(tavily_status=status))
    with pytest.raises(ProviderError) as e:
        await p.search("q price", purpose="price")
    assert e.value.kind == kind and e.value.status == status


async def test_tavily_bad_key_is_auth_error():
    p = tavily(FakeWeb(), key="tvly-wrong")
    with pytest.raises(ProviderError) as e:
        await p.search("q price", purpose="price")
    assert e.value.kind == "auth" and "invalid API key" in e.value.user_message


async def test_tavily_timeout_and_malformed():
    with pytest.raises(ProviderError) as e:
        await tavily(FakeWeb(tavily_timeout=True)).search("q", purpose="price")
    assert e.value.kind == "timeout" and e.value.retryable
    with pytest.raises(ProviderError) as e:
        await tavily(FakeWeb(tavily_body={"unexpected": True})).search("q", purpose="price")
    assert e.value.kind == "bad_response"


async def test_tavily_network_error():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)
    p = TavilyProvider("k", httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    with pytest.raises(ProviderError) as e:
        await p.search("q", purpose="price")
    assert e.value.kind == "network"


def test_missing_key_is_not_configured():
    with pytest.raises(ProviderError) as e:
        TavilyProvider("", httpx.AsyncClient())
    assert e.value.kind == "not_configured"


async def test_serpapi_shopping_parse_and_errors():
    p = SerpApiProvider("k", httpx.AsyncClient(transport=FakeWeb(serp_body=SERP_SHOPPING).transport()))
    items = await p.shopping("Acme TX-4400")
    assert items[0].supplier == "Canadian Tire" and items[0].price_value == 329.99
    assert items[0].rating == 4.4 and items[0].reviews == 120 and items[0].delivery == "Free delivery"
    assert items[1].condition == "used" and items[1].url == "https://www.ebay.ca/itm/123"
    assert p.credits_used == 1

    bad = SerpApiProvider("k", httpx.AsyncClient(transport=FakeWeb(serp_body=None).transport()))
    with pytest.raises(ProviderError) as e:
        await bad.shopping("x")
    assert e.value.kind == "auth"

    empty = SerpApiProvider("k", httpx.AsyncClient(transport=FakeWeb(
        serp_body={"error": "Google hasn't returned any results for this query."}).transport()))
    assert await empty.shopping("x") == []

    quota = SerpApiProvider("k", httpx.AsyncClient(transport=FakeWeb(
        serp_body={"error": "Your account has run out of searches."}, serp_status=429).transport()))
    with pytest.raises(ProviderError) as e:
        await quota.shopping("x")
    assert e.value.kind == "quota"


@pytest.mark.skipif(not __import__("os").environ.get("PI_NETWORK_TESTS"),
                    reason="makes a real outbound call; set PI_NETWORK_TESTS=1 to run")
async def test_proxy_refusal_is_reported_as_network(monkeypatch):
    """Real HTTP stack, real (unreachable/blocked) host: must fail cleanly, never fabricate results."""
    p = TavilyProvider("tvly-invalid", httpx.AsyncClient(timeout=10))
    with pytest.raises(ProviderError) as e:
        await p.search("test", purpose="price")
    # Depending on the machine this is a network/proxy refusal or (with internet) an auth rejection.
    assert e.value.kind in {"network", "auth", "timeout"}
