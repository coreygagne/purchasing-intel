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
