from app import extract as ex
from tests.fakeweb import jsonld_page


def test_classify_input():
    assert ex.classify_input("https://www.example.ca/p/123") == "url"
    assert ex.classify_input("Milwaukee 2767-20 impact wrench") == "model"
    assert ex.classify_input("heavy duty 50 ft extension cord 12 gauge") == "text"


def test_model_tokens_skip_units_and_fractions():
    assert ex.model_tokens("DeWalt DCF887B 18V 1/2 in 50ft") == ["DCF887B"]
    assert ex.model_tokens("M18 N95 2026 model") == []
    assert ex.model_tokens("3M 8210 respirator") == ["8210"]


def test_match_levels():
    assert ex.match_offer(["2767-20"], "Milwaukee M18 FUEL 2767-20 tool only").level == "exact"
    assert ex.match_offer(["2767-20"], "Milwaukee 2767-22 kit").level == "variant"
    assert ex.match_offer(["DCF887B"], "DEWALT DCF887 B").level == "exact"
    assert ex.match_offer(["DCF887B"], "DEWALT DCF887D2 kit").level == "variant"
    assert ex.match_offer(["8210"], "3M 8511 respirator").level == "different"
    assert ex.match_offer(["TX-4400"], "Widget TX4400 compatible replacement").level == "compatible"
    assert ex.match_offer([], "anything").level == "unverified"


def test_find_prices_skips_discounts_and_thresholds():
    got = ex.find_prices("Save $50 off! Now CA$1,299.99. Free shipping on orders over $49")
    assert [(p.amount, p.currency) for p in got] == [(1299.99, "CAD")]
    got = ex.find_prices("Was $99 now $79")
    assert [p.amount for p in got] == [79.0]
    got = ex.find_prices("$5/mo financing; Price $400")
    assert [p.amount for p in got] == [400.0]


def test_price_currency_and_ranges():
    p = ex.find_prices("US$1.50-2.30 / piece")[0]
    assert (p.amount, p.high, p.currency, p.is_range) == (1.5, 2.3, "USD", True)
    assert ex.find_prices("Price: 45.00 CAD")[0].currency == "CAD"
    assert ex.find_prices("$349.00")[0].currency is None  # bare "$" is ambiguous


def test_quote_required_and_moq():
    assert ex.quote_required("Please call for pricing") is not None
    assert ex.quote_required("Sign in to see your price") is not None
    assert ex.quote_required("Price $20") is None
    assert ex.moq_text("Min. order: 500 pieces") == "Min. order: 500 pieces"


def test_pack_quantity_not_confused_with_moq():
    assert ex.pack_quantity("3M 8210 Respirator (20/box)")[0] == 20
    assert ex.pack_quantity("Box of 100 nitrile gloves")[0] == 100
    assert ex.pack_quantity("US$45 / piece. Min. order: 200 pieces") is None


def test_warranty_shipping_availability():
    assert ex.warranty_text("Backed by a 5-Year Limited Warranty") == "5-Year Limited Warranty"
    assert ex.shipping_cost_from_text("Free shipping") == 0.0
    assert ex.shipping_cost_from_text("FREE shipping on orders over $75") is None
    assert ex.availability_text("Only 3 left - In Stock") == "in stock"


def test_condition():
    assert ex.detect_condition("Factory reconditioned unit") == "refurbished"
    assert ex.detect_condition("Brand new in box") is None


def test_structured_products_jsonld():
    html = jsonld_page("Acme TX-4400", "339.99", "CAD", rating=(4.6, 87))
    [p] = ex.structured_products(html)
    assert p.name == "Acme TX-4400" and p.mpn == "TX-4400" and p.brand == "Acme"
    assert p.offers[0].price == 339.99 and p.offers[0].currency == "CAD"
    assert p.offers[0].availability == "InStock" and p.offers[0].condition == "new"
    assert (p.rating_value, p.rating_count) == (4.6, 87)


def test_structured_aggregate_offer_and_graph():
    html = ('<script type="application/ld+json">{"@graph":[{"@type":"Product","name":"X","offers":'
            '{"@type":"AggregateOffer","lowPrice":"10.00","highPrice":"15.00","priceCurrency":"USD"}}]}</script>')
    [p] = ex.structured_products(html)
    assert (p.offers[0].price, p.offers[0].price_high, p.offers[0].currency) == (10.0, 15.0, "USD")


def test_structured_meta_fallback_and_bad_json():
    html = ('<script type="application/ld+json">{not json</script>'
            '<meta property="og:title" content="Thing"><meta property="product:price:amount" content="12.50">'
            '<meta property="product:price:currency" content="CAD">')
    [p] = ex.structured_products(html)
    assert p.name == "Thing" and p.offers[0].price == 12.5 and p.offers[0].currency == "CAD"


def test_no_structured_data_returns_empty():
    assert ex.structured_products("<html><body>No data</body></html>") == []
