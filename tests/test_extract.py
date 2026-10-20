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


def test_ebay_style_spaced_currency_prefixes():
    # verbatim formats seen in live search results (2026-10-20)
    got = ex.find_prices("Milwaukee 2767-20 C $235.20 Was C $294.00 (20% off)")
    assert [(p.amount, p.currency) for p in got] == [(235.2, "CAD")]
    # "Approximately C $..." is a converted display price, not the listing price
    assert [(p.amount, p.currency) for p in ex.find_prices("Price: US $359.54 Approximately C $501.38")] == \
        [(359.54, "USD")]
    assert [(p.amount, p.currency) for p in ex.find_prices("**$389.00 CAD**")] == [(389.0, "CAD")]



# Verbatim snippets returned by a live Anthropic web search on 2026-10-20 (real text, not invented).
LIVE = {
    "ebay_review": "… Has more torque than my $800 Snap On at almost a quarter of the price.",
    "ebay_ca": "# Milwaukee M18 FUEL Impact Wrench - 2767-20 Price:  US $359.54  Approximately C $501.38  + $112.62 shipping  ## Oops!",
    "dominion": "# Milwaukee ### $MIL 2767-20 GEN II HTIW 1/2\" RING BARE Part Number: 276720  Retail Price:  $414.00 / ea "
                "Your Price:  $279.00 / ea Availability: Call",
    "mississauga": "# Milwaukee 2767-20 M18 FUEL High Torque 1/2\"  Impact Wrench with Friction Ring (Tool Only) "
                   "**$389.00 CAD**  Unit price /  **Unavailable**",
    "kijiji": "Does not come with battery but can ...  NEW Milwaukee M18 FUEL High Torque 1/2\" Impact Wrench (2767-20)  $295.00",
}


def test_live_snippets_listing_prices():
    t = ["2767-20"]
    assert ex.listing_prices(LIVE["ebay_review"], t) == []                       # anecdote, not an offer
    assert [(p.amount, p.currency) for p in ex.listing_prices(LIVE["ebay_ca"], t)] == [(359.54, "USD")]
    assert ex.shipping_text(LIVE["ebay_ca"]) == "+ $112.62 shipping"
    assert ex.shipping_cost_from_text(ex.shipping_text(LIVE["ebay_ca"])) == 112.62
    assert [p.amount for p in ex.listing_prices(LIVE["dominion"], t)] == [279.0]  # "Retail Price" is list price
    assert [(p.amount, p.currency) for p in ex.listing_prices(LIVE["mississauga"], t)] == [(389.0, "CAD")]
    assert ex.availability_text(LIVE["mississauga"]) == "unavailable"
    assert [p.amount for p in ex.listing_prices(LIVE["kijiji"], t)] == [295.0]
