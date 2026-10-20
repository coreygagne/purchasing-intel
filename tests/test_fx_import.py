import httpx

from app.db import Database
from app.fx import FxService
from app.import_costs import clean_assumptions, delivered_estimate
from tests.fakeweb import FakeWeb


async def test_fx_rate_fetched_and_cached():
    fw = FakeWeb(fx_rate="1.3800")
    db = Database(":memory:")
    fx = FxService(db, httpx.AsyncClient(transport=fw.transport()))
    r = await fx.rate("USD")
    assert (r.rate_to_cad, r.rate_date) == (1.38, "2026-10-19")
    n = len(fw.calls)
    await fx.rate("USD")
    assert len(fw.calls) == n  # served from the SQLite cache
    assert (await fx.rate("CAD")).rate_to_cad == 1.0


async def test_fx_unavailable_is_reported_not_assumed():
    fx = FxService(Database(":memory:"), httpx.AsyncClient(transport=FakeWeb(fx_ok=False).transport()))
    assert await fx.rate("EUR") is None
    assert "EUR" in fx.errors
    assert await fx.rate("XYZ") is None and "No Bank of Canada series" in fx.errors["XYZ"]


def test_assumptions_validation():
    a = clean_assumptions({"duty_pct": "6.5", "brokerage_cad": -5, "surtax_pct": "abc", "intl_shipping_cad": 40})
    assert a == {"intl_shipping_cad": 40.0, "domestic_shipping_cad": None, "duty_pct": 6.5, "surtax_pct": None,
                 "brokerage_cad": None}


def test_domestic_delivered_calculated_when_shipping_quoted():
    est = delivered_estimate({"price_cad": 100.0, "currency": "CAD", "country": "CA", "shipping_cost": 0.0,
                              "shipping_text": "Free shipping"}, clean_assumptions({}))
    assert est["value"] == 100.0 and est["complete"] and est["label"] == "calculated" and est["kind"] == "delivered"


def test_domestic_missing_shipping_is_incomplete():
    est = delivered_estimate({"price_cad": 100.0, "currency": "CAD", "country": "CA"}, clean_assumptions({}))
    assert not est["complete"] and est["missing"] == ["shipping"]


def test_import_landed_estimate_with_user_assumptions():
    offer = {"price_cad": 138.0, "currency": "USD", "country": "US", "fx_rate": 1.38}
    est = delivered_estimate(offer, clean_assumptions({"intl_shipping_cad": 20, "duty_pct": 5, "surtax_pct": 25,
                                                       "brokerage_cad": 15}))
    # 138 + 20 shipping + 6.90 duty + 34.50 surtax + 15 brokerage
    assert est["value"] == 214.4 and est["complete"] and est["label"] == "estimated"
    gst = next(c for c in est["components"] if c["label"].startswith("GST"))
    assert gst["value"] == round((138 + 6.9 + 34.5) * 0.05, 2) and gst["basis"] == "rate"


def test_import_without_assumptions_lists_unknowns():
    est = delivered_estimate({"price_cad": 138.0, "currency": "USD", "country": "US"}, clean_assumptions({}))
    assert set(est["missing"]) == {"shipping", "duty", "surtax", "brokerage"}
    assert est["value"] == 138.0 and not est["complete"]


def test_quantity_uses_pack_size_and_counts_shipping_once():
    est = delivered_estimate({"price_cad": 50.0, "currency": "CAD", "country": "CA", "pack_qty": 20,
                              "shipping_cost": 10.0}, clean_assumptions({}), quantity=50)
    # 3 boxes of 20 cover 50 units
    assert est["units"] == 60 and est["value"] == 160.0 and est["per_unit"] == round(160 / 60, 2)
