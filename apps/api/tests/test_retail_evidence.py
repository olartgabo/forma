"""Offline retail evidence/security tests; these assert no live retailer success."""

import io
import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from forma_api.retail_evidence import (
    MAX_BYTES,
    MAX_RUN_BYTES,
    PinnedHTTPSConnection,
    RetailFetchError,
    RetailHTTP,
    RetailRefusalStore,
    RetailRobots,
    discover_offers,
    inspect_retail_html,
    public_addresses,
    public_url,
)

ORIGIN = "https://tools.example"


def product(name="Utility cutter", price="12.50", currency="USD", **extra):
    return {
        "@type": "Product",
        "name": name,
        "offers": {
            "@type": "Offer",
            "price": price,
            "priceCurrency": currency,
            **extra,
        },
    }


def document(*products, title="Utility cutter", text=""):
    return f'<h1>{title}</h1><p>{text}</p><script type="application/ld+json">{json.dumps(list(products))}</script>'


class FakeSocket:
    def settimeout(self, value):
        pass

    def shutdown(self, how):
        pass


class FakeResponse:
    def __init__(self, body="", status=200, **headers):
        self.body = io.BytesIO(body.encode() if isinstance(body, str) else body)
        self.status = status
        self.explicit_content_type = "Content-Type" in headers
        self.headers = {"Content-Type": "text/html", **headers}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, size):
        return self.body.read(size)


def client(pages, addresses=("93.184.216.34",), refusal_store=None):
    calls, destinations = [], []

    class Connection:
        def __init__(self, host, address, timeout):
            destinations.append((host, address))
            self.host = host
            self.sock = FakeSocket()

        def connect(self):
            pass

        def request(self, method, path, headers):
            assert method == "GET"
            assert "Cookie" not in headers and "Authorization" not in headers
            calls.append(path)
            key = (self.host, path) if (self.host, path) in pages else path
            self.response = pages[key]
            if (
                path.startswith("/robots.txt")
                and not self.response.explicit_content_type
            ):
                self.response.headers["Content-Type"] = "text/plain"

        def getresponse(self):
            return self.response

        def close(self):
            pass

    def resolver(host, port, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in addresses
        ]

    return (
        RetailHTTP(
            resolver=resolver, connection=Connection, refusal_store=refusal_store
        ),
        calls,
        destinations,
    )


@pytest.mark.parametrize("status", [401, 403, 406, 429, 451])
def test_refusal_persists_between_transports_and_www_paths_before_dns(tmp_path, status):
    path = tmp_path / "retail-refusals.sqlite3"
    first, calls, _ = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/product": FakeResponse("", status=status),
        },
        refusal_store=RetailRefusalStore(path),
    )
    with pytest.raises(RetailFetchError, match="access_refused"):
        first.page(ORIGIN + "/product", ORIGIN)
    assert calls == ["/robots.txt", "/product"]
    second, calls, _ = client({}, refusal_store=RetailRefusalStore(path))
    second.resolver = Mock(side_effect=AssertionError("Denied hosts must not resolve"))
    for origin in (ORIGIN, "https://www.tools.example"):
        for suffix in ("/", "/other?query=cutter"):
            with pytest.raises(RetailFetchError, match="access_refused"):
                second.page(origin + suffix, origin)
    assert calls == []
    second.resolver.assert_not_called()
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT * FROM retail_refusals").fetchone()
    assert row[0:2] == ("tools.example", str(status))
    assert len(row) == 3  # Only hostname, reason and time, never the requested URL.


def test_robots_406_persists_without_fetching_page_or_following_location(tmp_path):
    path = tmp_path / "retail-refusals.sqlite3"
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse(
                "", status=406, Location="https://different.example/"
            )
        },
        refusal_store=RetailRefusalStore(path),
    )
    with pytest.raises(RetailFetchError, match="access_refused"):
        http.page(ORIGIN + "/product", ORIGIN)
    assert calls == ["/robots.txt"]
    next_run, calls, _ = client({}, refusal_store=RetailRefusalStore(path))
    next_run.resolver = Mock(side_effect=AssertionError("No refusal retries"))
    with pytest.raises(RetailFetchError, match="access_refused"):
        next_run.page(ORIGIN + "/other", ORIGIN)
    assert calls == []
    next_run.resolver.assert_not_called()


@pytest.mark.parametrize("robots", [True, False])
def test_persisted_refusal_checks_every_redirect_before_destination_dns(
    tmp_path, robots
):
    store = RetailRefusalStore(tmp_path / "retail-refusals.sqlite3")
    store.record("tools.example", 403)
    source = "https://allowed.example"
    pages = {
        "/robots.txt": FakeResponse(
            "",
            status=302 if robots else 404,
            Location="https://www.tools.example/robots.txt",
        ),
        "/": FakeResponse("", status=302, Location=ORIGIN + "/different-product"),
    }
    http, calls, destinations = client(pages, refusal_store=store)
    original_resolver = http.resolver
    resolved = []

    def resolver(host, *args, **kwargs):
        resolved.append(host)
        assert host == "allowed.example"
        return original_resolver(host, *args, **kwargs)

    http.resolver = resolver
    with pytest.raises(RetailFetchError, match="access_refused"):
        http.page(source + "/", source)
    assert resolved == ["allowed.example"] * (1 if robots else 2)
    assert calls == (["/robots.txt"] if robots else ["/robots.txt", "/"])
    assert all(host == "allowed.example" for host, _ in destinations)


def test_refusal_expires_at_24_hours_without_deleting_or_extending_receipt(tmp_path):
    now = [100_000.0]
    path = tmp_path / "retail-refusals.sqlite3"
    store = RetailRefusalStore(path, clock=lambda: now[0])
    store.record("www.tools.example", "429", observed_at=now[0] - 86399)
    assert store.denied("tools.example")
    now[0] += 1
    assert not RetailRefusalStore(path, clock=lambda: now[0]).denied(
        "www.tools.example"
    )
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT observed_at FROM retail_refusals").fetchone()[0]
            == 13601
        )


def test_concurrent_store_writers_preserve_newest_refusal(tmp_path):
    path = tmp_path / "retail-refusals.sqlite3"
    stores = [RetailRefusalStore(path, clock=lambda: 2000) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda index: stores[index % 8].record(
                    "www.tools.example" if index % 2 else "tools.example",
                    403,
                    observed_at=1000 + index,
                ),
                range(32),
            )
        )
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM retail_refusals").fetchall() == [
            ("tools.example", "403", 1031.0)
        ]
    assert all(store.denied("tools.example") for store in stores)


@pytest.mark.parametrize("timestamp", [float("inf"), float("nan"), 2001, True])
def test_refusal_import_rejects_invalid_or_future_timestamps(timestamp):
    store = RetailRefusalStore(clock=lambda: 2000)
    with pytest.raises(ValueError):
        store.record("tools.example", 403, observed_at=timestamp)
    assert not store.denied("tools.example")


def test_real_default_store_uses_data_directory_and_fake_transport_is_ephemeral(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("FORMA_DATA_DIR", str(tmp_path))
    real = RetailHTTP()
    assert real.refusal_store.path == tmp_path / "retail-refusals.sqlite3"
    fake, _, _ = client({})
    assert fake.refusal_store.path is None


def test_discovers_observed_search_form_and_product_without_invented_routes():
    http, calls, destinations = client(
        {
            "/robots.txt": FakeResponse("User-agent: *\nDisallow: /private"),
            "/": FakeResponse(
                '<form method="get" action="/catalogue"><input name="q" type="search"><input name="secret" value="never-forward"></form>'
            ),
            "/catalogue?q=utility+cutter": FakeResponse(
                '<a href="/actual-item">Utility cutter</a><a href="https://other.example/p">Utility cutter</a>'
            ),
            "/actual-item": FakeResponse(document(product())),
        }
    )
    offers = discover_offers("utility cutter", "USD", [ORIGIN], http=http)
    assert len(offers) == 1 and offers[0].price == "12.50"
    assert offers[0].url == ORIGIN + "/actual-item"
    assert offers[0].price_status == "listed"
    assert "unverified" in offers[0].location
    assert calls == ["/robots.txt", "/", "/catalogue?q=utility+cutter", "/actual-item"]
    assert destinations == [("tools.example", "93.184.216.34")] * 4


def test_category_product_links_precede_older_generic_search_fallback():
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/": FakeResponse(
                '<a href="/collection/cutters">Utility cutter collection</a><form action="/search"><input name="q"></form>'
            ),
            "/collection/cutters": FakeResponse(
                '<a href="/products/cutter">Utility cutter</a>'
            ),
            "/products/cutter": FakeResponse(document(product())),
            "/search?q=cutter": FakeResponse("", status=403),
        }
    )
    offers = discover_offers("cutter", "USD", [ORIGIN], http=http)
    assert offers[0].price == "12.50"
    assert calls == ["/robots.txt", "/", "/collection/cutters", "/products/cutter"]


def test_category_refusal_never_falls_back_to_previously_queued_search():
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/": FakeResponse(
                '<a href="/collection/cutters">Utility cutter collection</a><form action="/search"><input name="q"></form>'
            ),
            "/collection/cutters": FakeResponse("", status=403),
        }
    )
    assert discover_offers("cutter", "USD", [ORIGIN, ORIGIN], http=http) == ()
    assert calls == ["/robots.txt", "/", "/collection/cutters"]


def test_global_currency_and_identity_not_recommendation_price():
    main = product("Tijera profesional", "38.7", "BOB")
    other = product("Utility cutter", "1", "BOB")
    result = inspect_retail_html(
        ORIGIN + "/p",
        document(main, other, title="Tijera profesional"),
        "BOB",
        "tijera",
    )
    assert result.price == "38.7"
    assert "Bolivia" not in result.location
    assert (
        inspect_retail_html(
            ORIGIN + "/p",
            document(main, other, title="Tool catalogue"),
            "BOB",
            "tijera",
        )
        is None
    )
    assert inspect_retail_html(ORIGIN + "/p", document(main), "USD", "tijera") is None


@pytest.mark.parametrize(
    "extra",
    [
        {"@type": "AggregateOffer", "lowPrice": "2", "highPrice": "10"},
        {"priceSpecification": {"price": "3"}},
    ],
)
def test_aggregate_or_variant_price_is_not_exact_offer(extra):
    assert (
        inspect_retail_html(ORIGIN, document(product(**extra)), "USD", "cutter") is None
    )


@pytest.mark.parametrize(
    "text,status",
    [
        ("DM for real price", "price_unknown"),
        ("Deposit of 12.50", "partial_price"),
        ("Starting from 12.50", "partial_price"),
    ],
)
def test_bait_and_partial_price_never_becomes_purchase_price(text, status):
    result = inspect_retail_html(
        ORIGIN, document(product(), text=text), "USD", "cutter"
    )
    assert result.price is None and result.price_status == status


def test_conflicting_variants_and_zero_are_not_cheapest_prices():
    data = product()
    data["offers"] = [data["offers"], {"price": "19", "priceCurrency": "USD"}]
    result = inspect_retail_html(ORIGIN, document(data), "USD", "cutter")
    assert result.price_status == "price_conflict" and result.price is None
    assert (
        inspect_retail_html(
            ORIGIN, document(product(price="0"), text="Free delivery"), "USD", "cutter"
        )
        is None
    )


def test_product_must_match_all_requested_material_and_specification_terms():
    assert (
        inspect_retail_html(
            ORIGIN,
            document(product(name="Wood glue"), title="Wood glue"),
            "USD",
            "wood plank",
        )
        is None
    )


def test_short_numbers_and_units_are_required_in_main_product_identity():
    for title in ("Scissors 9 in", "Scissors 8 cm", "Scissors"):
        assert (
            inspect_retail_html(
                ORIGIN,
                document(product(name=title), title=title),
                "USD",
                "scissors 8 in",
            )
            is None
        )
    title = "Scissors 8 in"
    assert (
        inspect_retail_html(
            ORIGIN, document(product(name=title), title=title), "USD", "scissors 8 in"
        ).price
        == "12.50"
    )
    assert (
        inspect_retail_html(
            ORIGIN,
            document(product(name="Utility cutter 9mm"), title="Utility cutter 9mm"),
            "USD",
            "cutter 18mm",
        )
        is None
    )


def test_microdata_must_belong_to_named_main_product():
    html = '<h1>Utility cutter</h1><section itemscope itemtype="https://schema.org/Product"><span itemprop="name">Utility cutter</span><meta itemprop="priceCurrency" content="USD"><meta itemprop="price" content="4.25"></section>'
    assert inspect_retail_html(ORIGIN, html, "USD", "cutter").price == "4.25"
    assert (
        inspect_retail_html(
            ORIGIN,
            html.replace(">Utility cutter</span>", ">Scissors</span>"),
            "USD",
            "cutter",
        )
        is None
    )
    assert (
        inspect_retail_html(
            ORIGIN,
            '<h1>Utility cutter</h1><meta itemprop="priceCurrency" content="USD"><meta itemprop="price" content="1">',
            "USD",
            "cutter",
        )
        is None
    )


def ga4_product_page(event=None, scopes=None):
    name = "Stainless Steel Scissors 1 pc"
    event = (
        event
        if event is not None
        else {
            "event": "view_item",
            "ecommerce": {
                "currency": "USD",
                "value": 21.99,
                "items": [{"item_id": "6208730", "item_name": name, "price": 21.99}],
            },
        }
    )
    scope = f'<section itemscope itemtype="https://schema.org/Product"><span itemprop="name">{name}</span><meta itemprop="priceCurrency" content="null"><meta itemprop="price" content="21.99"></section>'
    return (
        "<h1>Unrelated account modal</h1><nav>Starting fluid</nav>"
        + (scopes if scopes is not None else scope * 2)
        + "<script>dataLayer=dataLayer.concat("
        + json.dumps([event])
        + ");</script>"
    )


def test_ga4_literal_currency_binds_one_identified_microdata_product():
    result = inspect_retail_html(
        ORIGIN + "/scissors/6208730.html?view=detail",
        ga4_product_page(),
        "USD",
        "scissors",
    )
    assert result.price == "21.99" and result.currency == "USD"
    assert result.title == "Stainless Steel Scissors 1 pc"
    assert result.price_status == "listed"


@pytest.mark.parametrize(
    "change",
    [
        "currency",
        "name",
        "id",
        "price",
        "multiple_items",
        "multiple_events",
        "other_scope",
        "unnamed_scope",
        "other_microprice",
        "other_microcurrency",
        "javascript",
    ],
)
def test_ga4_ambiguous_or_unbound_currency_never_prices_product(change):
    html = ga4_product_page()
    edits = {
        "currency": ('"currency": "USD"', '"currency": "BOB"'),
        "name": (
            '"item_name": "Stainless Steel Scissors 1 pc"',
            '"item_name": "Recommended cutters"',
        ),
        "id": ('"item_id": "6208730"', '"item_id": "620873"'),
        "price": ('"price": 21.99', '"price": 5'),
        "other_scope": (
            "</section>",
            '</section><section itemscope itemtype="https://schema.org/Product"><meta itemprop="name" content="Recommended cutter"></section>',
        ),
        "unnamed_scope": (
            "</section>",
            '</section><section itemscope itemtype="https://schema.org/Product"></section>',
        ),
        "other_microprice": (
            "</section>",
            '<meta itemprop="price" content="5"></section>',
        ),
        "other_microcurrency": ('content="null"', 'content="BOB"'),
        "javascript": ('"price": 21.99', '"price": getPrice()'),
    }
    if change in edits:
        html = html.replace(*edits[change])
    elif change == "multiple_items":
        html = html.replace(
            '"items": [', '"items": [{"item_id":"other","item_name":"Other","price":5},'
        )
    else:
        html += ga4_product_page()
    assert (
        inspect_retail_html(ORIGIN + "/6208730.html", html, "USD", "scissors") is None
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://tools.example/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://user:pass@tools.example/",
        "https://tools.example:444/",
        "https://www.facebook.com/x",
        "https://meta.ai/",
        "https://tools.local/",
        "https://tools.example/?api_key=secret",
        "https://tools.example/\\private",
    ],
)
def test_rejects_unsafe_url_shapes(url):
    with pytest.raises(RetailFetchError):
        public_url(url)


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("169.254.169.254",),
        ("10.0.0.1",),
        ("224.0.0.1",),
        ("239.255.255.250",),
        ("ff02::1",),
        ("::1",),
        ("::ffff:93.184.216.34",),
        ("93.184.216.34", "192.168.1.2"),
    ],
)
def test_dns_rejects_any_nonpublic_or_mapped_answer_before_connect(addresses):
    http, calls, destinations = client({}, addresses)
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == [] and destinations == []


def test_pin_preserves_tls_hostname_and_avoids_second_resolution(monkeypatch):
    raw = Mock()
    connect = Mock(return_value=raw)
    monkeypatch.setattr(socket, "create_connection", connect)
    connection = PinnedHTTPSConnection("tools.example", "93.184.216.34", 3)
    context = Mock()
    connection._context = context
    connection.connect()
    connect.assert_called_once_with(("93.184.216.34", 443), 3)
    context.wrap_socket.assert_called_once_with(raw, server_hostname="tools.example")


def test_robots_disallow_and_access_refusal_stop_without_bypass():
    http, calls, _ = client({"/robots.txt": FakeResponse("User-agent: *\nDisallow: /")})
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == ["/robots.txt"]
    for status in (403, 429):
        http, calls, _ = client({"/robots.txt": FakeResponse("", status=status)})
        assert discover_offers("cutter", "USD", [ORIGIN, ORIGIN], http=http) == ()
        assert calls == ["/robots.txt"]


def test_shared_robots_redirect_refusal_is_not_retried_from_another_origin():
    http, calls, destinations = client(
        {
            ("one.example", "/robots.txt"): FakeResponse(
                "", status=301, Location="https://central.example/robots.txt"
            ),
            ("central.example", "/robots.txt"): FakeResponse("", status=403),
            ("two.example", "/robots.txt"): FakeResponse(
                "", status=301, Location="https://central.example/robots.txt"
            ),
        }
    )
    assert (
        discover_offers(
            "cutter", "USD", ["https://one.example", "https://two.example"], http=http
        )
        == ()
    )
    assert [host for host, _ in destinations] == [
        "one.example",
        "central.example",
        "two.example",
    ]
    assert len(calls) == http.requests == 3
    assert "https://central.example" in http.blocked


def test_robots_delay_is_respected_without_sleep_or_probe():
    http, calls, _ = client(
        {"/robots.txt": FakeResponse("User-agent: *\nCrawl-delay: 10")}
    )
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == ["/robots.txt"]


@pytest.mark.parametrize(
    "rules",
    ["Crawl-delay: 0.5", "Request-rate: 1/60"],
)
def test_applicable_robots_rate_limits_fail_closed(rules):
    http, calls, _ = client({"/robots.txt": FakeResponse("User-agent: *\n" + rules)})
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == ["/robots.txt"]


def test_shopify_wildcards_deny_only_matching_cart_checkout_and_queries():
    rules = RetailRobots("""User-agent: *
Allow: /
Allow: /products/checkout
Disallow: /cart/
Disallow: /*/cart/
Disallow: /checkout
Disallow: /*/checkout
Disallow: /collections/*sort_by*
Disallow: /*/collections/*%2B*
Disallow: /*?*preview_theme_id=*
Disallow: /*?*ls=*&ls=*
User-agent: adsbot-google
Disallow: /
Crawl-delay: 20
""")
    for path in (
        "/",
        "/products/scissors",
        "/search?q=scissors",
        "/collections/craft-tools",
        "/products/checkout",
    ):
        assert rules.can_fetch("FORMA-RetailResearch/1.0", ORIGIN + path)
    for path in (
        "/checkout",
        "/cart/add",
        "/fr/cart/add",
        "/fr/checkout",
        "/collections/tools?sort_by=price",
        "/fr/collections/craft%2bcutters",
        "/products/a?preview_theme_id=123",
        "/search?ls=1&ls=2",
    ):
        assert not rules.can_fetch("FORMA-RetailResearch/1.0", ORIGIN + path)
    assert not rules.rate_limited("FORMA-RetailResearch/1.0")


def test_exact_and_most_specific_agent_groups_merge_and_override_star():
    rules = RetailRobots("""User-agent: *
Disallow: /
Crawl-delay: 20
User-agent: FORMA
Disallow: /broad
User-agent: forma-retailresearch
Disallow: /private
User-agent: FORMA-RetailResearch
Disallow: /hidden
User-agent: OtherBot
Disallow: /
""")
    for path in ("/", "/products/scissors", "/broad"):
        assert rules.can_fetch("FORMA-RetailResearch/1.0", ORIGIN + path)
    assert not rules.can_fetch("FORMA-RetailResearch/1.0", ORIGIN + "/private")
    assert not rules.can_fetch("FORMA-RetailResearch/1.0", ORIGIN + "/hidden")
    assert not rules.rate_limited("FORMA-RetailResearch/1.0")
    assert not rules.can_fetch("UnknownAgent", ORIGIN + "/products/scissors")


def test_longest_rule_allow_ties_and_terminal_anchor():
    rules = RetailRobots("""User-agent: *
Allow: /
Disallow: /private
Allow: /private/public
Disallow: /tie
Allow: /tie
Disallow: /exact$
Disallow: /a*b*c$
""")
    assert not rules.can_fetch("FORMA", ORIGIN + "/private/secret")
    for path in (
        "/private/public/product",
        "/tie",
        "/exactly",
        "/exact?query=1",
        "/aXYZbXYZc/extra",
    ):
        assert rules.can_fetch("FORMA", ORIGIN + path)
    for path in ("/exact", "/aXYZbXYZc"):
        assert not rules.can_fetch("FORMA", ORIGIN + path)


def test_robots_case_and_percent_octets_remain_distinct_where_required():
    rules = RetailRobots("""User-agent: *
Disallow: /Private
Disallow: /encoded%2Fpath
Disallow: /%7Euser
Disallow: /caf%C3%A9
Disallow: /literal%2A
Disallow: /literal%24
""")
    for path in (
        "/Private",
        "/encoded%2fpath",
        "/~user",
        "/%7euser",
        "/café",
        "/caf%c3%a9",
        "/literal%2a",
        "/literal*",
        "/literal$",
    ):
        assert not rules.can_fetch("FORMA", ORIGIN + path)
    for path in ("/private", "/encoded/path", "/literalXYZ"):
        assert rules.can_fetch("FORMA", ORIGIN + path)


@pytest.mark.parametrize(
    "text,path,allowed",
    [
        ("Allow: /page\nDisallow: /*.htm", "/page.htm", False),
        ("Allow: /page\nDisallow: /*.ph", "/page.php5", True),
        ("Allow: /\nDisallow: /$", "/", False),
        ("Allow: /fish\nDisallow: /fish*", "/fishheads", True),
    ],
)
def test_wildcard_and_end_anchor_octets_have_correct_rule_specificity(
    text, path, allowed
):
    assert (
        RetailRobots("User-agent: *\n" + text).can_fetch("FORMA", ORIGIN + path)
        is allowed
    )


def test_allowed_shopify_homepage_and_product_can_produce_observed_price():
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse(
                "User-agent: *\nAllow: /\nDisallow: /checkout\nDisallow: /*?*preview_theme_id=*\nUser-agent: adsbot-google\nDisallow: /"
            ),
            "/": FakeResponse('<a href="/products/cutter">Utility cutter</a>'),
            "/products/cutter": FakeResponse(document(product())),
        }
    )
    result = discover_offers("cutter", "USD", [ORIGIN], http=http)
    assert result[0].price == "12.50"
    assert calls == ["/robots.txt", "/", "/products/cutter"]


def test_robots_parser_has_finite_source_rule_limits():
    with pytest.raises(RetailFetchError, match="robots_limit"):
        RetailRobots("User-agent: *\nDisallow: /" + "x" * 2048)


def test_allow_precedence_and_multiple_agent_groups_cannot_relax_disallow():
    for rules in (
        "User-agent: *\nAllow: /\nDisallow: /private",
        "User-agent: *\nAllow: /\n\nUser-agent: *\nDisallow: /private",
    ):
        http, calls, _ = client(
            {
                "/robots.txt": FakeResponse(rules),
                "/": FakeResponse('<a href="/private">cutter</a>'),
            }
        )
        assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
        assert calls == ["/robots.txt", "/"]


def test_unexpected_worker_failure_is_visible_as_known_retail_error():
    http, _, _ = client({})
    http.page = Mock(side_effect=RuntimeError("internal diagnosis"))
    with pytest.raises(RetailFetchError, match="discovery_failed"):
        discover_offers("cutter", "USD", [ORIGIN], http=http)


def test_redirect_cannot_escape_candidate_origin_or_robots():
    for target in ("https://127.0.0.1/", "/private"):
        http, calls, _ = client(
            {
                "/robots.txt": FakeResponse("User-agent: *\nDisallow: /private"),
                "/": FakeResponse("", status=302, Location=target),
            }
        )
        assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
        assert calls == ["/robots.txt", "/"]


def test_explicit_public_redirect_establishes_storefront_only_after_robots():
    http, calls, destinations = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/": FakeResponse(
                "", status=301, Location="https://storefront.example/retailer/"
            ),
            ("storefront.example", "/robots.txt"): FakeResponse(
                "User-agent: *\nDisallow: /private"
            ),
            ("storefront.example", "/retailer/"): FakeResponse(
                '<form action="/search"><input name="q"></form><a href="https://foreign.example/p">cutter</a>'
            ),
            ("storefront.example", "/search?q=cutter"): FakeResponse(
                '<a href="/p">Utility cutter</a>'
            ),
            ("storefront.example", "/p"): FakeResponse(document(product())),
        }
    )
    offers = discover_offers("cutter", "USD", [ORIGIN], http=http)
    assert len(offers) == 1 and offers[0].url == "https://storefront.example/p"
    assert calls == [
        "/robots.txt",
        "/",
        "/robots.txt",
        "/retailer/",
        "/search?q=cutter",
        "/p",
    ]
    assert http.requests == 6 and http.origin_requests == {ORIGIN: 6}
    assert [host for host, _ in destinations] == ["tools.example"] * 2 + [
        "storefront.example"
    ] * 4


def test_foreign_redirect_robots_refusal_blocks_destination_content():
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/": FakeResponse(
                "", status=302, Location="https://storefront.example/retailer/"
            ),
            ("storefront.example", "/robots.txt"): FakeResponse(
                "User-agent: *\nDisallow: /"
            ),
        }
    )
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == ["/robots.txt", "/", "/robots.txt"]


def test_public_robots_redirect_rules_apply_to_original_authority():
    http, calls, destinations = client(
        {
            "/robots.txt": FakeResponse(
                "",
                status=301,
                Location="https://central.example/robots.txt?member=shop",
            ),
            ("central.example", "/robots.txt?member=shop"): FakeResponse(
                "User-agent: *\nDisallow: /private"
            ),
            "/": FakeResponse('<a href="/private">cutter</a>'),
        }
    )
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == ["/robots.txt", "/robots.txt?member=shop", "/"]
    assert set(http.rules) == {ORIGIN}
    assert not http.rules[ORIGIN].can_fetch(
        "FORMA-RetailResearch/1.0", ORIGIN + "/private"
    )
    assert [host for host, _ in destinations] == [
        "tools.example",
        "central.example",
        "tools.example",
    ]


@pytest.mark.parametrize(
    "content_type", ["text/html", "application/json", "text/plain-unsafe"]
)
def test_redirected_robots_must_be_plain_text_before_any_page_fetch(content_type):
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse(
                "", status=302, Location="https://central.example/robots.txt"
            ),
            ("central.example", "/robots.txt"): FakeResponse(
                "<html>not robots</html>", **{"Content-Type": content_type}
            ),
        }
    )
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == ["/robots.txt", "/robots.txt"]
    assert not http.rules


def test_robots_redirect_never_connects_to_private_dns_or_meta():
    for target in (
        "https://private.example/robots.txt",
        "https://www.facebook.com/robots.txt",
        "https://127.0.0.1/robots.txt",
    ):
        http, calls, _ = client(
            {"/robots.txt": FakeResponse("", status=302, Location=target)}
        )
        http.resolver = lambda host, port, **kw: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1" if host == "private.example" else "93.184.216.34", port),
            )
        ]
        assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
        assert calls == ["/robots.txt"]


def test_robots_redirect_chain_stops_after_two_hops():
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse(
                "", status=301, Location="https://central.example/robots.txt"
            ),
            ("central.example", "/robots.txt"): FakeResponse(
                "", status=302, Location="https://second.example/robots.txt"
            ),
            ("second.example", "/robots.txt"): FakeResponse(
                "", status=302, Location="https://never.example/robots.txt"
            ),
        }
    )
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert len(calls) == 3 and not http.rules


def test_foreign_redirect_checks_public_dns_before_destination_robots():
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/": FakeResponse(
                "", status=302, Location="https://private.example/retailer/"
            ),
        }
    )
    http.resolver = lambda host, port, **kw: [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("127.0.0.1" if host == "private.example" else "93.184.216.34", port),
        )
    ]
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == ["/robots.txt", "/"]


def test_redirect_hops_cannot_bypass_total_per_candidate_budget():
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/": FakeResponse("", status=301, Location="/one"),
            "/one": FakeResponse("", status=302, Location="/two"),
            "/two": FakeResponse(
                "", status=302, Location="https://not-fetched.example/"
            ),
        }
    )
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == ["/robots.txt", "/", "/one", "/two"]


def test_request_and_body_limits_do_not_continue_crawling():
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/": FakeResponse('<a href="/a">cutter</a>'),
            "/a": FakeResponse('<a href="/b">cutter</a>'),
            "/b": FakeResponse('<a href="/c">cutter</a>'),
            "/c": FakeResponse('<a href="/d">cutter</a>'),
            "/d": FakeResponse('<a href="/e">cutter</a>'),
            "/e": FakeResponse('<a href="/f">cutter</a>'),
            "/f": FakeResponse('<a href="/g">cutter</a>'),
        }
    )
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert len(calls) == 8
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/": FakeResponse(b"a" * (MAX_BYTES + 1)),
        }
    )
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert len(calls) == 2


def test_large_legitimate_html_below_four_megabytes_can_supply_price():
    html = document(product()) + " " * 1_100_000
    http, calls, _ = client(
        {"/robots.txt": FakeResponse("", status=404), "/": FakeResponse(html)}
    )
    result = discover_offers("cutter", "USD", [ORIGIN], http=http)
    assert result[0].price == "12.50"
    assert http.bytes_read == len(html.encode())
    assert calls == ["/robots.txt", "/"]


def test_eight_megabyte_whole_run_body_limit_prevents_later_dispatch():
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/a": FakeResponse("x" * 3_000_000),
            "/b": FakeResponse("x" * 3_000_000),
            "/c": FakeResponse("x" * 3_000_000),
        }
    )
    http.page(ORIGIN + "/a", ORIGIN)
    http.page(ORIGIN + "/b", ORIGIN)
    with pytest.raises(RetailFetchError, match="run_byte_limit"):
        http.page(ORIGIN + "/c", ORIGIN)
    assert http.bytes_read == MAX_RUN_BYTES
    with pytest.raises(RetailFetchError):
        http.page(ORIGIN + "/never", ORIGIN)
    assert calls == ["/robots.txt", "/a", "/b", "/c"]


def test_fair_budget_continues_after_nonpriced_origin_to_second_real_offer():
    http, calls, destinations = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/": FakeResponse('<a href="/a">cutter</a>'),
            "/a": FakeResponse('<a href="/b">cutter</a>'),
            "/b": FakeResponse('<a href="/c">cutter</a>'),
            "/c": FakeResponse('<a href="/d">cutter</a>'),
            "/d": FakeResponse('<a href="/e">cutter</a>'),
            "/e": FakeResponse('<a href="/f">cutter</a>'),
            "/f": FakeResponse('<a href="/g">cutter</a>'),
            ("priced.example", "/robots.txt"): FakeResponse("", status=404),
            ("priced.example", "/"): FakeResponse(
                '<a href="/product">Utility cutter</a>'
            ),
            ("priced.example", "/product"): FakeResponse(document(product())),
        }
    )
    offers = discover_offers(
        "utility cutter", "USD", [ORIGIN, "https://priced.example"], http=http
    )
    assert len(offers) == 1 and offers[0].url == "https://priced.example/product"
    assert offers[0].price == "12.50"
    assert len(calls) == 11
    assert [host for host, _ in destinations] == ["tools.example"] * 8 + [
        "priced.example"
    ] * 3
    assert http.origin_requests == {ORIGIN: 8, "https://priced.example": 3}


def test_three_distinct_origins_and_twenty_four_total_requests_are_hard_caps():
    def pages_for(host):
        return {
            (host, "/robots.txt"): FakeResponse("", status=404),
            (host, "/"): FakeResponse('<a href="/a">cutter</a>'),
            (host, "/a"): FakeResponse('<a href="/b">cutter</a>'),
            (host, "/b"): FakeResponse('<a href="/c">cutter</a>'),
            (host, "/c"): FakeResponse('<a href="/d">cutter</a>'),
            (host, "/d"): FakeResponse('<a href="/e">cutter</a>'),
            (host, "/e"): FakeResponse('<a href="/f">cutter</a>'),
            (host, "/f"): FakeResponse('<a href="/g">cutter</a>'),
        }

    pages = {}
    for host in ("one.example", "two.example", "three.example"):
        pages.update(pages_for(host))
    http, calls, destinations = client(pages)
    assert (
        discover_offers(
            "cutter",
            "USD",
            [
                "https://one.example",
                "https://one.example/other",
                "https://two.example",
                "https://three.example",
                "https://four.example",
            ],
            http=http,
        )
        == ()
    )
    assert len(calls) == 24 and len(http.origin_requests) == 3
    assert set(http.origin_requests.values()) == {8}
    assert all(host != "four.example" for host, _ in destinations)


def test_foreign_post_and_hidden_search_forms_are_never_executed():
    http, calls, _ = client(
        {
            "/robots.txt": FakeResponse("", status=404),
            "/": FakeResponse(
                '<form action="https://other.example/search"><input name="q"></form><form method="post" action="/search"><input name="q"></form><form action="/search"><input type="hidden" name="q"></form>'
            ),
        }
    )
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == ["/robots.txt", "/"]


def test_expired_deadline_prevents_dns_or_network_dispatch():
    resolver = Mock()
    http = RetailHTTP(resolver=resolver)
    http.deadline = http.clock() - 1
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    resolver.assert_not_called()


def test_public_addresses_are_revalidated_on_every_request():
    answers = iter(
        [
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
        ]
    )
    http, calls, _ = client({"/robots.txt": FakeResponse("", status=404)})
    http.resolver = lambda *a, **kw: next(answers)
    assert discover_offers("cutter", "USD", [ORIGIN], http=http) == ()
    assert calls == ["/robots.txt"]
    assert public_addresses(
        "tools.example",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    ) == ["93.184.216.34"]
