"""Shared test setup.

The simulated web uses real-looking host names that are not resolvable from a
test machine, so the page fetcher's DNS lookup is replaced with a fixed answer:
hosts ending in ".internal.test" resolve to a private address (to exercise the
SSRF guard); everything else resolves to a public documentation address.
"""

import pytest

from app import fetch


async def fake_resolve(host: str) -> list[str]:
    if host.endswith(".internal.test"):
        return ["10.1.2.3"]
    return ["93.184.216.34"]


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch):
    monkeypatch.setattr(fetch, "resolve_host", fake_resolve)


class _NoNetworkAnthropic:
    """Stands in for a real Anthropic client wherever a test didn't inject a stub, so no test reaches the API."""

    def __init__(self):
        from types import SimpleNamespace

        async def create(**kw):
            from app.providers.anthropic_fetch import AnthropicFetchError
            raise AnthropicFetchError("no Anthropic network access in tests")

        self.messages = SimpleNamespace(create=create)


@pytest.fixture(autouse=True)
def _no_real_anthropic_fetch(monkeypatch):
    from app.providers import anthropic_fetch
    monkeypatch.setattr(anthropic_fetch, "_make_client", lambda *a, **k: _NoNetworkAnthropic())
