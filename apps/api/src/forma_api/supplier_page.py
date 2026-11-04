"""Explicit product-page inspection for two supported public retail sites.

No model, arbitrary URL fetch, credentials, purchase or physical-state authority.
"""

import http.client
import json
import re
import socket
import threading
import time
import unicodedata
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from forma_api.model_gateway import GatewayError
from forma_api.sourcing import OfferObservation, price_status

HOSTS = frozenset(
    {
        "tramontinastore.com.bo",
        "www.tramontinastore.com.bo",
        "uyustus.com.bo",
        "www.uyustus.com.bo",
    }
)
MAX_PAGE_BYTES = 2_000_000
PAGE_TIMEOUT = 8


def supported_supplier_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        url = urlsplit(value)
        path = unquote(url.path)
        return bool(
            url.scheme == "https"
            and url.hostname in HOSTS
            and not url.username
            and not url.password
            and url.port is None
            and not url.query
            and not url.fragment
            and "\\" not in path
            and not any(piece in {".", ".."} for piece in path.split("/"))
            and path.startswith(
                "/shop/" if "tramontinastore" in url.hostname else "/productos/"
            )
            and len(path.strip("/").split("/")) >= 2
            and not any(ord(c) < 32 for c in value)
        )
    except ValueError:
        return False


def fetch_supplier_page(url):
    """Bound the whole GET, including connect, redirects and trickled bodies."""
    if not supported_supplier_url(url):
        raise GatewayError("supplier_page_error")
    deadline = time.monotonic() + PAGE_TIMEOUT
    expired = threading.Event()
    shared, result = {}, {}

    def fetch():
        current = url
        try:
            for _ in range(3):
                if expired.is_set() or time.monotonic() >= deadline:
                    raise GatewayError("supplier_page_error")
                parsed = urlsplit(current)
                connection = http.client.HTTPSConnection(
                    parsed.hostname, timeout=max(0.01, deadline - time.monotonic())
                )
                shared["connection"] = connection
                try:
                    connection.connect()
                    if (
                        expired.is_set()
                        or time.monotonic() >= deadline
                        or connection.sock is None
                    ):
                        raise GatewayError("supplier_page_error")
                    connection.request(
                        "GET",
                        parsed.path,
                        headers={
                            "User-Agent": "FORMA product-page inspection",
                            "Accept": "text/html",
                            "Accept-Encoding": "identity",
                        },
                    )
                    response = connection.getresponse()
                    if response.status in {301, 302, 303, 307, 308}:
                        target = urljoin(current, response.getheader("Location", ""))
                        if not supported_supplier_url(target):
                            raise GatewayError("supplier_page_error")
                        current = target
                        continue
                    if (
                        response.status != 200
                        or "text/html"
                        not in response.getheader("Content-Type", "").lower()
                    ):
                        raise GatewayError("supplier_page_error")
                    if response.getheader(
                        "Content-Encoding", "identity"
                    ).lower() not in {"", "identity"}:
                        raise GatewayError("supplier_page_error")
                    raw = bytearray()
                    while True:
                        remaining = deadline - time.monotonic()
                        if expired.is_set() or remaining <= 0:
                            raise GatewayError("supplier_page_error")
                        if connection.sock:
                            connection.sock.settimeout(remaining)
                        chunk = response.read1(
                            min(65536, MAX_PAGE_BYTES + 1 - len(raw))
                        )
                        if not chunk:
                            result["page"] = (current, raw.decode("utf-8", "replace"))
                            return
                        raw.extend(chunk)
                        if len(raw) > MAX_PAGE_BYTES:
                            raise GatewayError("supplier_page_error")
                finally:
                    connection.close()
            raise GatewayError("supplier_page_error")
        except Exception:
            result["error"] = True

    worker = threading.Thread(target=fetch, daemon=True, name="forma-supplier-page")
    worker.start()
    worker.join(PAGE_TIMEOUT)
    if worker.is_alive():
        expired.set()
        connection = shared.get("connection")
        sock = connection.sock if connection else None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        raise GatewayError("supplier_page_error")
    if result.get("error") or "page" not in result:
        raise GatewayError("supplier_page_error")
    return result["page"]


class ProductParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.json_scripts, self.current_json, self.text = [], None, []
        self.meta, self.h1, self.h1_depth, self.capture = {}, [], 0, None
        self.hidden = 0
        self.depth = 0
        self.product_scopes, self.active_products = [], []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.depth += 1
        if "Product" in {
            kind.rsplit("/", 1)[-1] for kind in attrs.get("itemtype", "").split()
        }:
            scope = {"depth": self.depth, "names": []}
            self.product_scopes.append(scope)
            self.active_products.append(scope)
        if tag == "script":
            self.hidden += 1
            if attrs.get("type", "").lower() == "application/ld+json":
                self.current_json = []
        elif tag == "style":
            self.hidden += 1
        if tag == "h1":
            self.h1_depth += 1
        key = attrs.get("itemprop") or attrs.get("property")
        if key and attrs.get("content") is not None:
            self.meta.setdefault(key, []).append(attrs["content"])
            if key == "name" and self.active_products:
                self.active_products[-1]["names"].append(attrs["content"])
        elif key in {"price", "priceCurrency", "name"}:
            self.capture = (
                tag,
                key,
                [],
                self.active_products[-1] if self.active_products else None,
            )

    def handle_endtag(self, tag):
        if tag == "script":
            if self.current_json is not None:
                self.json_scripts.append("".join(self.current_json))
                self.current_json = None
            self.hidden = max(0, self.hidden - 1)
        elif tag == "style":
            self.hidden = max(0, self.hidden - 1)
        if tag == "h1":
            self.h1_depth = max(0, self.h1_depth - 1)
        if self.capture and self.capture[0] == tag:
            self.meta.setdefault(self.capture[1], []).append(" ".join(self.capture[2]))
            if self.capture[1] == "name" and self.capture[3] is not None:
                self.capture[3]["names"].append(" ".join(self.capture[2]))
            self.capture = None
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.active_products = [
                scope for scope in self.active_products if scope["depth"] < self.depth
            ]
            self.depth = max(0, self.depth - 1)

    def handle_data(self, text):
        if self.current_json is not None:
            self.current_json.append(text)
        if not self.hidden:
            self.text.append(text)
            if self.h1_depth:
                self.h1.append(text)
            if self.capture:
                self.capture[2].append(text)


def _products(value):
    if isinstance(value, list):
        for child in value:
            yield from _products(child)
    elif isinstance(value, dict):
        if value.get("@type") == "Product" or "Product" in (
            value.get("@type") if isinstance(value.get("@type"), list) else []
        ):
            yield value
        if "@graph" in value:
            yield from _products(value["@graph"])


def _amount(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip().replace(",", ".")
    if not re.fullmatch(r"\d{1,10}(?:\.\d{1,6})?", text):
        return None
    try:
        amount = Decimal(text)
        return format(amount, "f") if 0 < amount <= Decimal("1000000000") else None
    except InvalidOperation:
        return None


def inspect_supplier_html(url, html, currency):
    if not supported_supplier_url(url) or len(html.encode("utf-8")) > MAX_PAGE_BYTES:
        raise GatewayError("supplier_page_error")
    parser = ProductParser()
    parser.feed(html)
    products = []
    for script in parser.json_scripts:
        try:
            products.extend(_products(json.loads(script)))
        except (ValueError, RecursionError):
            continue
    title = (
        " ".join(parser.h1).strip()
        or (parser.meta.get("og:title") or ["Supplier product"])[0]
    )

    def normalize(value):
        return " ".join(str(value).split()).casefold()

    # A recommendation's microdata cannot price the main page heading. Until
    # values are fully scoped, any unnamed or conflicting Product scope makes
    # the global metadata fallback ambiguous. JSON-LD identity stays separate.
    metadata_identity_known = all(
        scope["names"]
        and all(normalize(name) == normalize(title) for name in scope["names"])
        for scope in parser.product_scopes
    )
    # JSON-LD can include recommendations. Never let the last Product block
    # silently replace the main page identity, even when prices happen to match.
    identity_unknown = False
    if products:
        explicit = [p for p in products if p.get("url") == url or p.get("@id") == url]

        by_name = [
            p
            for p in products
            if parser.h1 and normalize(p.get("name", "")) == normalize(title)
        ]
        selected = explicit if explicit else by_name
        if len(selected) == 1:
            products = selected
        elif (
            len(products) == 1
            and not parser.h1
            and not products[0].get("url")
            and not products[0].get("@id")
        ):
            pass
        else:
            products, identity_unknown = [], True
    prices = set()
    for product in products:
        title = str(product.get("name") or title)
        offers = product.get("offers", [])
        for offer in offers if isinstance(offers, list) else [offers]:
            if not isinstance(offer, dict) or offer.get("priceCurrency") != currency:
                continue
            value = _amount(offer.get("price"))
            if value:
                prices.add(value)
    currencies = parser.meta.get("priceCurrency", []) + parser.meta.get(
        "product:price:currency", []
    )
    if currency in currencies and not identity_unknown and metadata_identity_known:
        for raw in parser.meta.get("price", []) + parser.meta.get(
            "product:price:amount", []
        ):
            value = _amount(raw)
            if value:
                prices.add(value)
    quoted = bool(
        re.search(
            r"\bcotizar\b|consultar\s+(?:el\s+)?precio|precio\s+(?:al\s+privado|a\s+consultar)|\bdm\b",
            " ".join(parser.text),
            re.IGNORECASE,
        )
    )
    status, price = "price_unknown", None
    if not quoted and len({Decimal(p) for p in prices}) == 1:
        folded = "".join(
            c
            for c in unicodedata.normalize("NFKD", " ".join(parser.text))
            if not unicodedata.combining(c)
        )
        price, status = price_status(next(iter(prices)), folded)
    elif not quoted and len(prices) > 1:
        status = "price_conflict"
    notes = "Published supplier-page claim; confirm quantity, condition, delivery and all extra charges. Nearby pickup and stock are not verified."
    if quoted:
        notes = (
            "This page asks for a quote; its displayed amount is not a confirmed item price. "
            + notes
        )
    return OfferObservation(
        title=title[:200],
        url=url,
        price=price,
        currency=currency,
        price_status=status,
        availability="Unconfirmed; check with supplier",
        location="Bolivia online supplier; local pickup unverified",
        notes=notes[:600],
    )


class SupplierPageGateway:
    def __init__(self, fetch=fetch_supplier_page):
        self.fetch = fetch

    def research(self, request):
        url, html = self.fetch(request.supplier_url)
        return (inspect_supplier_html(url, html, request.currency),), None
