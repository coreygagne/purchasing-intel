"""Foreign-exchange rates from the Bank of Canada Valet API (free, no key).

https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1
returns {"observations": [{"d": "YYYY-MM-DD", "FXUSDCAD": {"v": "1.3712"}}], ...}
Rates are cached in SQLite for 24 hours. If the API is unreachable the
conversion is reported as unavailable - no rate is ever assumed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from .db import Database

log = logging.getLogger(__name__)

VALET_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json"
SUPPORTED = {"USD", "EUR", "GBP", "CNY", "JPY", "MXN", "AUD", "NZD", "HKD", "INR", "KRW", "SGD",
             "CHF", "SEK", "NOK", "TWD", "ZAR", "BRL", "SAR", "TRY", "IDR", "MYR", "PEN"}
SOURCE_LABEL = "Bank of Canada daily exchange rate"


@dataclass
class FxRate:
    currency: str
    rate_to_cad: float
    rate_date: str
    source: str


class FxService:
    def __init__(self, db: Database, client: httpx.AsyncClient, timeout_s: float = 10.0):
        self.db = db
        self.client = client
        self.timeout_s = timeout_s
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
        try:
            resp = await self.client.get(VALET_URL.format(series=series), params={"recent": 1},
                                         timeout=self.timeout_s)
            resp.raise_for_status()
            data = resp.json()
            obs = data["observations"][-1]
            value = float(obs[series]["v"])
            rate_date = str(obs["d"])
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            self.errors[currency] = f"Bank of Canada rate unavailable ({type(exc).__name__})"
            log.warning("FX lookup failed for %s: %s", currency, exc)
            return None
        self.db.put_fx(currency, rate_date, value, SOURCE_LABEL)
        return FxRate(currency, value, rate_date, SOURCE_LABEL)

    async def rates(self, currencies: set[str]) -> dict[str, FxRate]:
        out: dict[str, FxRate] = {}
        for cur in sorted(c for c in currencies if c):
            r = await self.rate(cur)
            if r:
                out[cur] = r
        return out
