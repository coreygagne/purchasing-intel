"""Foreign-exchange rates from the Bank of Canada Valet API (free, no key).

https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1
returns {"observations": [{"d": "YYYY-MM-DD", "FXUSDCAD": {"v": "1.3712"}}], ...}
Rates are cached in SQLite for 24 hours. If this server can't reach the API
and an Anthropic key is configured, the same Valet URL is fetched through
Anthropic's web fetch tool and the JSON is parsed here as usual. If neither
works the conversion is reported as unavailable - no rate is ever assumed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from .db import Database
from .providers.anthropic_fetch import VIA, AnthropicFetchError

log = logging.getLogger(__name__)

VALET_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json"
SUPPORTED = {"USD", "EUR", "GBP", "CNY", "JPY", "MXN", "AUD", "NZD", "HKD", "INR", "KRW", "SGD",
             "CHF", "SEK", "NOK", "TWD", "ZAR", "BRL", "SAR", "TRY", "IDR", "MYR", "PEN"}
SOURCE_LABEL = "Bank of Canada daily exchange rate"
SOURCE_LABEL_VIA = f"{SOURCE_LABEL} (fetched via {VIA})"
MAX_FALLBACK_RATE_AGE_DAYS = 10  # a fetched copy can be cached; the Bank publishes every business day


def _parse(data: Any, series: str) -> tuple[float, str]:
    obs = data["observations"][-1]
    value = float(obs[series]["v"])
    if not value > 0:
        raise ValueError("non-positive rate")
    return value, str(obs["d"])


@dataclass
class FxRate:
    currency: str
    rate_to_cad: float
    rate_date: str
    source: str


class FxService:
    def __init__(self, db: Database, client: httpx.AsyncClient, timeout_s: float = 10.0,
                 fallback: Any | None = None):
        self.db = db
        self.client = client
        self.timeout_s = timeout_s
        self.fallback = fallback  # AnthropicFetcher, used only when the direct request can't connect
        self.errors: dict[str, str] = {}

    async def rate(self, currency: str) -> FxRate | None:
        currency = currency.upper()
        if currency == "CAD":
            return FxRate("CAD", 1.0, "", "identity")
        cached = self.db.get_fx(currency)
        if cached:
            return FxRate(currency, cached["rate_to_cad"], cached["rate_date"], cached["source"])
        if currency not in SUPPORTED:
            self.errors[currency] = f"No Bank of Canada series for {currency}"
            return None
        series = f"FX{currency}CAD"
        url = VALET_URL.format(series=series)
        source = SOURCE_LABEL
        try:
            resp = await self.client.get(url, params={"recent": 1}, timeout=self.timeout_s)
            resp.raise_for_status()
            value, rate_date = _parse(resp.json(), series)
        except httpx.TransportError as exc:  # couldn't connect from this server
            if self.fallback is None:
                return self._fail(currency, exc)
            try:
                doc = await self.fallback.fetch(f"{url}?recent=1", max_content_tokens=2000)
                value, rate_date = _parse(json.loads(doc.text), series)
                age = (date.today() - date.fromisoformat(rate_date)).days
                if age > MAX_FALLBACK_RATE_AGE_DAYS:
                    raise ValueError(f"the fetched copy's rate is from {rate_date}, {age} days old")
                source = SOURCE_LABEL_VIA
            except (AnthropicFetchError, ValueError, KeyError, IndexError, TypeError) as exc2:
                return self._fail(currency, exc, f"; {VIA} also failed: {exc2}")
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            return self._fail(currency, exc)
        self.db.put_fx(currency, rate_date, value, source)
        return FxRate(currency, value, rate_date, source)

    def _fail(self, currency: str, exc: Exception, extra: str = "") -> None:
        self.errors[currency] = f"Bank of Canada rate unavailable ({type(exc).__name__}){extra}"
        log.warning("FX lookup failed for %s: %s%s", currency, exc, extra)
        return None

    async def rates(self, currencies: set[str]) -> dict[str, FxRate]:
        out: dict[str, FxRate] = {}
        for cur in sorted(c for c in currencies if c):
            r = await self.rate(cur)
            if r:
                out[cur] = r
        return out
