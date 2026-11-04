import json

import pytest

from forma_api.model_gateway import GatewayError
from forma_api.sourcing import ResearchRequest
from forma_api.supplier_page import (
    MAX_PAGE_BYTES,
    SupplierPageGateway,
    fetch_supplier_page,
    inspect_supplier_html,
    supported_supplier_url,
)

URL = "https://www.tramontinastore.com.bo/shop/example/product-12"


def product(price="24.50", currency="BOB", **extra):
    return {
        "@type": "Product",
        "name": "A pair of scissors",
        "offers": {"@type": "Offer", "price": price, "priceCurrency": currency},
        **extra,
    }


def document(value, text=""):
    return (
        '<h1>A pair of scissors</h1><script type="application/ld+json">'
        + json.dumps(value)
        + "</script>"
        + text
    )


@pytest.mark.parametrize(
    "value",
    [product(), [product()], {"@graph": [{"@type": "Organization"}, product()]}],
)
def test_jsonld_products_keep_current_offer_and_exact_source(value):
    offer = inspect_supplier_html(URL, document(value, "<del>30.00 Bs.</del>"), "BOB")
    assert offer.title == "A pair of scissors"
    assert offer.price == "24.50" and offer.price_status == "listed"
    assert offer.url == URL
    assert "unverified" in offer.location and "Unconfirmed" in offer.availability


@pytest.mark.parametrize(
    "price", ["0", "-1", "NaN", "Infinity", True, None, "1000000001", "1e8", "24.5 BOB"]
)
def test_invalid_or_zero_prices_remain_unknown(price):
    offer = inspect_supplier_html(URL, document(product(price)), "BOB")
    assert offer.price is None and offer.price_status == "price_unknown"


def test_currency_and_mixed_offer_prices_cannot_be_comparable():
    assert (
        inspect_supplier_html(URL, document(product(currency="USD")), "BOB").price
        is None
    )
    value = product()
    value["offers"] = [
        {"price": "20", "priceCurrency": "BOB"},
        {"price": "35", "priceCurrency": "BOB"},
    ]
    offer = inspect_supplier_html(URL, document(value), "BOB")
    assert offer.price is None and offer.price_status == "price_conflict"


def test_recommended_products_do_not_replace_main_identity_even_at_same_price():
    main = product()
    recommended = product(name="Kitchen knife")
    offer = inspect_supplier_html(URL, document([main, recommended]), "BOB")
    assert offer.title == "A pair of scissors" and offer.price == "24.50"
    unrelated = [product(name="Knife"), product(name="Fork")]
    offer = inspect_supplier_html(URL, document(unrelated), "BOB")
    assert offer.title == "A pair of scissors" and offer.price is None


def test_explicit_product_url_selects_main_and_ambiguous_duplicate_identity_stays_unknown():
    main = product(name="Scissors", url=URL)
    related = product(name="Other product", url=URL + "-other")
    offer = inspect_supplier_html(URL, document([related, main]), "BOB")
    assert offer.title == "Scissors" and offer.price == "24.50"
    offer = inspect_supplier_html(URL, document([main, main]), "BOB")
    assert offer.price is None


def test_quote_only_placeholder_is_not_a_real_price():
    offer = inspect_supplier_html(
        "https://uyustus.com.bo/productos/scissors/",
        document(product("1"), "<button>COTIZAR</button>"),
        "BOB",
    )
    assert offer.price is None and offer.price_status == "price_unknown"
    assert "quote" in offer.notes


@pytest.mark.parametrize(
    "qualifier",
    [
        "Desde 20 BOB",
        "Depósito 20 BOB; total 100 BOB",
        "Cuota 20 BOB",
        "Installment 20 BOB",
    ],
)
def test_structured_price_cannot_hide_visible_partial_price_qualifier(qualifier):
    offer = inspect_supplier_html(
        URL, document(product("20"), "<p>" + qualifier + "</p>"), "BOB"
    )
    assert offer.price is None and offer.price_status == "partial_price"


def test_odoo_microdata_and_decimal_comma_without_scripts():
    offer = inspect_supplier_html(
        URL,
        '<h1>Scissors</h1><meta itemprop="priceCurrency" content="BOB"><span itemprop="price" content="28,75"></span><script>buyNow()</script>',
        "BOB",
    )
    assert offer.price == "28.75"
    assert offer.title == "Scissors"


def test_related_microdata_price_does_not_price_main_page_heading():
    html = '<h1>Main scissors</h1><section itemscope itemtype="https://schema.org/Product"><meta itemprop="name" content="Related knife"><meta itemprop="priceCurrency" content="BOB"><meta itemprop="price" content="20"></section>'
    offer = inspect_supplier_html(URL, html, "BOB")
    assert offer.title == "Main scissors" and offer.price is None
    assert offer.price_status == "price_unknown"


def test_matching_named_main_microdata_scope_can_supply_price():
    html = '<section itemscope itemtype="https://schema.org/Product"><h1 itemprop="name">Main scissors</h1><div itemprop="offers" itemscope itemtype="https://schema.org/Offer"><meta itemprop="priceCurrency" content="BOB"><meta itemprop="price" content="20"></div></section>'
    offer = inspect_supplier_html(URL, html, "BOB")
    assert offer.title == "Main scissors" and offer.price == "20"


def test_related_microdata_also_blocks_unscoped_og_price_but_not_valid_jsonld():
    html = '<h1>Main scissors</h1><meta property="product:price:currency" content="BOB"><meta property="product:price:amount" content="20"><section itemscope itemtype="https://schema.org/Product"><span itemprop="name">Related knife</span></section>'
    assert inspect_supplier_html(URL, html, "BOB").price is None
    html += (
        '<script type="application/ld+json">'
        + json.dumps(product("31", name="Main scissors"))
        + "</script>"
    )
    assert inspect_supplier_html(URL, html, "BOB").price == "31"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.tramontinastore.com.bo/shop/a",
        "https://www.tramontinastore.com.bo:443/shop/a",
        "https://uyustus.com.bo.evil.test/productos/a",
        "https://127.0.0.1/shop/a",
        "https://user@uyustus.com.bo/productos/a",
        "https://uyustus.com.bo/admin",
        "https://www.tramontinastore.com.bo/shop/../admin",
        "https://www.tramontinastore.com.bo/shop/%2e%2e/admin",
        "https://www.tramontinastore.com.bo/shop/a?redirect=https://evil.test",
        "https://www.tramontinastore.com.bo/shop/a#private",
    ],
)
def test_only_supported_public_product_urls_are_permitted(url):
    assert not supported_supplier_url(url)
    with pytest.raises(GatewayError):
        fetch_supplier_page(url)


def test_response_size_and_missing_structured_price():
    with pytest.raises(GatewayError):
        inspect_supplier_html(URL, "x" * (MAX_PAGE_BYTES + 1), "BOB")
    offer = inspect_supplier_html(
        URL, "<h1>Scissors</h1><p>Price twenty bolivianos</p>", "BOB"
    )
    assert offer.price is None


def test_gateway_does_not_call_meta_or_invent_usage():
    calls = []
    gateway = SupplierPageGateway(
        lambda url: (calls.append(url) or url, document(product()))
    )
    request = ResearchRequest(
        expected_revision_id="inventory-a",
        idempotency_key="inspect-1",
        item="Scissors",
        area="La Paz",
        currency="BOB",
        source="supplier_page",
        supplier_url=URL,
    )
    offers, usage = gateway.research(request)
    assert calls == [URL] and offers[0].price == "24.50" and usage is None


def test_fetch_checks_redirect_target_before_following(monkeypatch):
    class Sock:
        def settimeout(self, _):
            pass

    class Response:
        status = 302

        def getheader(self, name, default=""):
            return "https://127.0.0.1/private" if name == "Location" else default

    calls = []

    class Connection:
        def __init__(self, host, timeout):
            self.sock = None
            calls.append(host)

        def connect(self):
            self.sock = Sock()

        def request(self, method, path, headers):
            calls.append((method, path, headers))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        "forma_api.supplier_page.http.client.HTTPSConnection", Connection
    )
    with pytest.raises(GatewayError):
        fetch_supplier_page(URL)
    assert calls[0] == "www.tramontinastore.com.bo" and len(calls) == 2
    assert "Authorization" not in calls[1][2]
