"""Small, read-only public retail discovery from actual nearby-business websites.

No retailer routes, prices or inventories are invented. At most three origins,
eight HTTP requests per candidate (including robots and redirects), twenty-four total and
thirty seconds bound discovery. Unsupported stores produce no price evidence.
"""

import http.client
import ipaddress
import json
import math
import os
import re
import socket
import sqlite3
import ssl
import threading
import time
import unicodedata
from contextlib import closing
from decimal import Decimal
from html.parser import HTMLParser
from http.client import HTTPException
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import certifi

from forma_api.sourcing import OfferObservation, price_status
from forma_api.supplier_page import ProductParser, _amount, _products

MAX_ORIGINS = 3
MAX_ORIGIN_REQUESTS = 8
MAX_REQUESTS = 24
MAX_BYTES = 4_000_000
MAX_RUN_BYTES = 8_000_000
RUN_SECONDS = 30
PAGE_SECONDS = 8
USER_AGENT = "FORMA-RetailResearch/1.0"
REFUSAL_SECONDS = 24 * 60 * 60
REFUSAL_STATUSES = frozenset({401, 403, 406, 429, 451})


class RetailFetchError(Exception):
    """A known public-page failure, never an uncertain paid-provider outcome."""


def _refusal_host(host):
    # Store only validated hostnames, never URLs, paths, queries or credentials.
    canonical = urlsplit(public_url("https://" + host)).hostname
    if host.lower().rstrip(".") != canonical:
        raise RetailFetchError("invalid_refusal_host")
    return canonical.removeprefix("www.")


class RetailRefusalStore:
    """A 24-hour host refusal shared across runs; expired receipts stay recorded."""

    def __init__(self, path=None, clock=time.time):
        self.path = Path(path) if path is not None else None
        self.clock = clock
        self.entries = {}
        self.lock = threading.Lock()
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(self.path, timeout=1)) as connection:
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS retail_refusals "
                        "(host TEXT PRIMARY KEY, reason TEXT NOT NULL, observed_at REAL NOT NULL)"
                    )
                    connection.commit()
            except (OSError, sqlite3.Error) as exc:
                raise RetailFetchError("refusal_store_unavailable") from exc

    def record(self, host, reason, observed_at=None):
        """Record an actual access refusal, including an imported past receipt."""
        host, reason = _refusal_host(host), str(reason)
        now = self.clock()
        observed_at = now if observed_at is None else observed_at
        if (
            reason not in {str(status) for status in REFUSAL_STATUSES}
            or type(observed_at) not in {int, float}
            or not math.isfinite(observed_at)
            or observed_at > now
        ):
            raise ValueError("An actual refusal and finite past timestamp are required")
        with self.lock:
            if self.path is None:
                if observed_at >= self.entries.get(host, ("", float("-inf")))[1]:
                    self.entries[host] = (reason, observed_at)
                return
            try:
                with closing(sqlite3.connect(self.path, timeout=1)) as connection:
                    connection.execute(
                        "INSERT INTO retail_refusals VALUES (?,?,?) "
                        "ON CONFLICT(host) DO UPDATE SET reason=excluded.reason, observed_at=excluded.observed_at "
                        "WHERE excluded.observed_at >= retail_refusals.observed_at",
                        (host, reason, observed_at),
                    )
                    connection.commit()
            except sqlite3.Error as exc:
                raise RetailFetchError("refusal_store_unavailable") from exc

    def denied(self, host):
        host = _refusal_host(host)
        with self.lock:
            if self.path is None:
                row = self.entries.get(host)
            else:
                try:
                    with closing(sqlite3.connect(self.path, timeout=1)) as connection:
                        row = connection.execute(
                            "SELECT reason, observed_at FROM retail_refusals WHERE host=?",
                            (host,),
                        ).fetchone()
                except sqlite3.Error as exc:
                    raise RetailFetchError("refusal_store_unavailable") from exc
        return row is not None and self.clock() < row[1] + REFUSAL_SECONDS


def _robots_octets(value, *, pattern=False):
    """Compare URI octets without decoding reserved escapes or folding paths."""
    unreserved = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    result, index = [], 0
    while index < len(value):
        char = value[index]
        if char == "%" and re.fullmatch(
            r"[0-9A-Fa-f]{2}", value[index + 1 : index + 3]
        ):
            byte = int(value[index + 1 : index + 3], 16)
            result.append(chr(byte) if chr(byte) in unreserved else f"%{byte:02X}")
            index += 3
            continue
        if not pattern and char in "*$":
            result.append(f"%{ord(char):02X}")
        elif ord(char) > 127 or char == " ":
            result.extend(f"%{byte:02X}" for byte in char.encode("utf-8"))
        else:
            result.append(char)
        index += 1
    return "".join(result)


def _robots_match(pattern, path, terminal):
    """Bounded wildcard matching without regex backtracking on source patterns."""
    parts = pattern.split("*")
    if not path.startswith(parts[0]):
        return False
    cursor = len(parts[0])
    if len(parts) == 1:
        return not terminal or cursor == len(path)
    for part in parts[1:-1]:
        match = path.find(part, cursor)
        if match < 0:
            return False
        cursor = match + len(part)
    last = parts[-1]
    if terminal:
        return path.endswith(last) and len(path) - len(last) >= cursor
    return path.find(last, cursor) >= 0


class RetailRobots:
    """Bounded applicable-group, octet, wildcard and specificity REP matching."""

    def __init__(self, text):
        self.groups = []
        agents, directives = [], []
        rule_count = 0
        for line in text.lstrip("\ufeff").splitlines():
            line = line.split("#", 1)[0]
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key, value = key.strip().casefold(), value.strip()
            if key == "user-agent":
                if directives:
                    self.groups.append((agents, directives))
                    agents, directives = [], []
                if value:
                    agents.append(value.casefold())
            elif agents and key in {"allow", "disallow", "crawl-delay", "request-rate"}:
                if len(value) > 2048:
                    raise RetailFetchError("robots_limit")
                directives.append((key, value))
                rule_count += 1
            if len(self.groups) > 256 or rule_count > 2048:
                raise RetailFetchError("robots_limit")
        if agents:
            self.groups.append((agents, directives))

    def _applicable(self, agent):
        agent = agent.casefold()
        matches, fallback = [], []
        for agents, directives in self.groups:
            specificity = max(
                (len(name) for name in agents if name != "*" and name in agent),
                default=0,
            )
            if specificity:
                matches.append((specificity, directives))
            elif "*" in agents:
                fallback.extend(directives)
        if not matches:
            return fallback
        best = max(score for score, _ in matches)
        return [
            rule
            for score, directives in matches
            if score == best
            for rule in directives
        ]

    def rate_limited(self, agent):
        return any(
            key in {"crawl-delay", "request-rate"} and value
            for key, value in self._applicable(agent)
        )

    def can_fetch(self, agent, url):
        parts = urlsplit(url)
        path = _robots_octets(
            (parts.path or "/") + ("?" + parts.query if parts.query else "")
        )
        matches = []
        for key, value in self._applicable(agent):
            if key not in {"allow", "disallow"} or not value:
                continue
            terminal = value.endswith("$")
            pattern = _robots_octets(value[:-1] if terminal else value, pattern=True)
            if _robots_match(pattern, path, terminal):
                effective = pattern if terminal else pattern.rstrip("*")
                specificity = len(re.sub(r"%[0-9A-F]{2}", "x", effective)) + int(
                    terminal
                )
                matches.append((specificity, key == "allow"))
        # Longest matching path wins. Allow wins equal-specificity ties.
        return max(matches, default=(0, True))[1]


def public_url(value, origin=None):
    """Validate shape; DNS validation happens immediately before every request."""
    if not isinstance(value, str) or len(value) > 2000:
        raise RetailFetchError("invalid_url")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or not host
            or "." not in host
            or host.endswith(".")
            or "\\" in value
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            or any(
                host == name or host.endswith("." + name)
                for name in (
                    "facebook.com",
                    "fb.com",
                    "fb.me",
                    "meta.com",
                    "meta.ai",
                    "instagram.com",
                    "facebook.net",
                    "fbcdn.net",
                    "messenger.com",
                    "whatsapp.com",
                    "threads.net",
                    "localhost",
                    "local",
                    "internal",
                )
            )
        ):
            raise RetailFetchError("invalid_url")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise RetailFetchError("literal_ip")
        if any(
            re.search(
                r"token|secret|password|authorization|api.?key|session|signature",
                key,
                re.I,
            )
            for key, _ in parse_qsl(parsed.query)
        ):
            raise RetailFetchError("sensitive_query")
        normalized = urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
        if (
            origin is not None
            and urlsplit(normalized).netloc != urlsplit(origin).netloc
        ):
            raise RetailFetchError("foreign_origin")
        return normalized
    except (ValueError, UnicodeError):
        raise RetailFetchError("invalid_url") from None


def public_addresses(host, resolver=socket.getaddrinfo):
    addresses = []
    for info in resolver(host, 443, type=socket.SOCK_STREAM):
        address = info[4][0]
        ip = ipaddress.ip_address(address)
        if (
            not ip.is_global
            or ip.is_multicast
            or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped)
        ):
            raise RetailFetchError("nonpublic_address")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise RetailFetchError("no_address")
    return addresses


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(
            host,
            port=443,
            timeout=timeout,
            context=ssl.create_default_context(cafile=certifi.where()),
        )
        self.address = address

    def connect(self):
        # The TCP destination cannot be changed by a second DNS resolution. The
        # original hostname still controls SNI and certificate verification.
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


class RetailHTTP:
    def __init__(
        self,
        resolver=socket.getaddrinfo,
        connection=PinnedHTTPSConnection,
        clock=time.monotonic,
        refusal_store=None,
    ):
        self.resolver, self.connection, self.clock = resolver, connection, clock
        self.deadline = clock() + RUN_SECONDS
        self.requests = 0
        self.bytes_read = 0
        self.origin_requests = {}
        self.expired = threading.Event()
        self.active = None
        self.page_guard = None
        self.rules = {}
        self.blocked = set()
        if refusal_store is None:
            path = (
                Path(os.environ.get("FORMA_DATA_DIR", ".local/forma"))
                / "retail-refusals.sqlite3"
                if connection is PinnedHTTPSConnection
                and resolver is socket.getaddrinfo
                else None
            )
            refusal_store = RetailRefusalStore(path)
            if path is not None:
                # Real November 4 acceptance refusals travel with this release;
                # deploying must not become a way to retry those same hosts.
                # These expire normally after 24h and contain no private data.
                for host, status, observed in (
                    ("papersource.com", 403, 1793796528.5170028),
                    ("doitbest.com", 406, 1793795367.0),
                ):
                    if observed <= time.time():
                        refusal_store.record(host, status, observed_at=observed)
        self.refusal_store = refusal_store

    def _check_refusal(self, origin):
        host = urlsplit(origin).hostname
        if origin in self.blocked or self.refusal_store.denied(host):
            raise RetailFetchError("access_refused")

    def stop(self):
        self.expired.set()
        self._interrupt_active()

    def _interrupt_active(self):
        connection = self.active
        if connection and connection.sock:
            try:
                connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _remaining(self, deadline):
        remaining = min(deadline, self.deadline) - self.clock()
        if self.expired.is_set() or remaining <= 0:
            raise RetailFetchError("deadline")
        return remaining

    def _get(self, url, origin, robots=False, budget_origin=None):
        guard = object()
        previous_guard = self.page_guard
        self.page_guard = guard

        def expire_page():
            if self.page_guard is guard:
                self._interrupt_active()

        watchdog = threading.Timer(
            min(PAGE_SECONDS, self._remaining(self.deadline)), expire_page
        )
        watchdog.daemon = True
        watchdog.start()
        try:
            return self._request(url, origin, robots, budget_origin or origin)
        finally:
            self.page_guard = previous_guard
            watchdog.cancel()

    def _request(self, url, origin, robots, budget_origin):
        deadline = min(self.deadline, self.clock() + PAGE_SECONDS)
        current = public_url(url, origin)
        for redirect_index in range(3):
            if (
                self.requests >= MAX_REQUESTS
                or self.origin_requests.get(budget_origin, 0) >= MAX_ORIGIN_REQUESTS
                or self.bytes_read >= MAX_RUN_BYTES
            ):
                raise RetailFetchError("request_limit")
            self._remaining(deadline)
            parsed = urlsplit(current)
            actual_origin = "https://" + parsed.netloc
            self._check_refusal(actual_origin)
            addresses = public_addresses(parsed.hostname, self.resolver)
            self.requests += 1
            self.origin_requests[budget_origin] = (
                self.origin_requests.get(budget_origin, 0) + 1
            )
            connection = self.connection(
                parsed.hostname, addresses[0], self._remaining(deadline)
            )
            self.active = connection
            try:
                connection.connect()
                self._remaining(deadline)
                connection.request(
                    "GET",
                    parsed.path + ("?" + parsed.query if parsed.query else ""),
                    headers={
                        "Host": parsed.hostname,
                        "User-Agent": USER_AGENT,
                        "Accept": "text/plain" if robots else "text/html",
                        "Accept-Encoding": "identity",
                    },
                )
                response = connection.getresponse()
                if response.status in REFUSAL_STATUSES:
                    self.blocked.add(actual_origin)
                    self.refusal_store.record(parsed.hostname, response.status)
                    raise RetailFetchError("access_refused")
                if response.status in {301, 302, 303, 307, 308}:
                    if redirect_index == 2:
                        raise RetailFetchError("redirect_limit")
                    target = public_url(
                        urljoin(current, response.getheader("Location", ""))
                    )
                    target_origin = "https://" + urlsplit(target).netloc
                    if not robots:
                        # A server's explicit redirect may establish its official
                        # storefront origin. HTML links never gain that power.
                        self._ensure_rules(target_origin, budget_origin)
                        self._remaining(deadline)
                        if not self.rules[target_origin].can_fetch(USER_AGENT, target):
                            raise RetailFetchError("robots_disallowed")
                    current = target
                    continue
                if robots and response.status in {404, 410}:
                    return current, ""
                if response.status != 200 or response.getheader(
                    "Content-Encoding", "identity"
                ).lower() not in {"", "identity"}:
                    raise RetailFetchError("unsupported_response")
                content_type = response.getheader("Content-Type", "").lower()
                if robots and content_type.split(";", 1)[0].strip() != "text/plain":
                    raise RetailFetchError("not_robots_text")
                if (
                    not robots
                    and "text/html" not in content_type
                    and "application/xhtml+xml" not in content_type
                ):
                    raise RetailFetchError("not_html")
                raw = bytearray()
                while True:
                    remaining = self._remaining(deadline)
                    if self.bytes_read >= MAX_RUN_BYTES:
                        raise RetailFetchError("run_byte_limit")
                    if connection.sock:
                        connection.sock.settimeout(remaining)
                    chunk = response.read1(
                        min(
                            65536,
                            MAX_BYTES + 1 - len(raw),
                            MAX_RUN_BYTES - self.bytes_read,
                        )
                    )
                    if not chunk:
                        return current, raw.decode("utf-8", "replace")
                    raw.extend(chunk)
                    self.bytes_read += len(chunk)
                    if len(raw) > MAX_BYTES:
                        raise RetailFetchError("page_limit")
            finally:
                connection.close()
                self.active = None
        raise RetailFetchError("redirect_limit")

    def _ensure_rules(self, origin, budget_origin):
        self._check_refusal(origin)
        if origin not in self.rules:
            _, text = self._get(
                origin + "/robots.txt", origin, robots=True, budget_origin=budget_origin
            )
            rules = RetailRobots(text)
            # RFC 9309: a robots redirect can cross authorities. Its fetched
            # plain-text rules still apply to the authority that requested it,
            # never an authorization to crawl the robots hosting authority.
            if rules.rate_limited(USER_AGENT):
                self.blocked.add(origin)
                raise RetailFetchError("robots_unsupported_rule")
            self.rules[origin] = rules

    def page(self, url, origin, budget_origin=None):
        budget_origin = budget_origin or origin
        self._ensure_rules(origin, budget_origin)
        url = public_url(url, origin)
        if not self.rules[origin].can_fetch(USER_AGENT, url):
            raise RetailFetchError("robots_disallowed")
        return self._get(url, origin, budget_origin=budget_origin)


def _fold(value):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value).casefold())
        if not unicodedata.combining(c)
    )


def _tokens(value):
    return set(re.findall(r"[^\W_]{3,}", _fold(value))) - {
        "the",
        "and",
        "for",
        "with",
        "buy",
        "near",
        "para",
        "con",
        "una",
        "del",
        "las",
        "los",
    }


def _matches(item, title):
    wanted = _tokens(item)
    return bool(wanted and wanted.intersection(_tokens(title)))


def _matches_specification(item, title):
    # Discovery can traverse broad category labels, but a price may only be
    # attached to a title containing every substantive requested term. Do not
    # price "wood plank" with a cheaper "wood glue" recommendation.
    wanted = _tokens(item)
    actual = _tokens(title)

    def numbers(value):
        return set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?![\d.,])", _fold(value)))

    def measurements(value):
        units = {
            "millimeter": "mm",
            "millimeters": "mm",
            "millimetre": "mm",
            "millimetres": "mm",
            "centimeter": "cm",
            "centimeters": "cm",
            "centimetre": "cm",
            "centimetres": "cm",
            "inch": "in",
            "inches": "in",
            "feet": "ft",
            "foot": "ft",
        }
        return {
            (number.replace(",", "."), units.get(unit, unit))
            for number, unit in re.findall(
                r"(?<!\w)(\d+(?:[.,]\d+)?)\s*[-]?\s*(mm|millimeters?|millimetres?|cm|centimeters?|centimetres?|inches|inch|in|feet|foot|ft|kg|g|m)\b",
                _fold(value),
            )
        }

    return bool(
        wanted
        and wanted.issubset(actual)
        and numbers(item).issubset(numbers(title))
        and measurements(item).issubset(measurements(title))
    )


class RetailProductParser(ProductParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.script = [], None

    def handle_starttag(self, tag, attributes):
        super().handle_starttag(tag, attributes)
        if tag == "script":
            self.script = []

    def handle_data(self, text):
        super().handle_data(text)
        if self.script is not None:
            self.script.append(text)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "script" and self.script is not None:
            self.scripts.append("".join(self.script))
            self.script = None


def _ga4_microdata_price(parser, url, currency):
    """Decode literal JSON only; never execute source JavaScript or infer currency."""
    names = []
    for scope in parser.product_scopes:
        if not scope["names"]:
            return None
        names.extend(" ".join(name.split()) for name in scope["names"])
    if not names or len(set(names)) != 1:
        return None
    events = []
    decoder = json.JSONDecoder()
    for script in parser.scripts:
        for match in re.finditer(r"\bdataLayer\s*\.\s*(?:concat|push)\s*\(\s*", script):
            try:
                literal, end = decoder.raw_decode(script[match.end() :])
            except (ValueError, RecursionError):
                continue
            if not script[match.end() + end :].lstrip().startswith(")"):
                continue
            for event in literal if isinstance(literal, list) else [literal]:
                if isinstance(event, dict) and event.get("event") == "view_item":
                    events.append(event)
    if len(events) != 1:
        return None
    commerce = events[0].get("ecommerce")
    if not isinstance(commerce, dict) or commerce.get("currency") != currency:
        return None
    items = commerce.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        return None
    item = items[0]
    identifier = item.get("item_id")
    if (
        item.get("item_name") != names[0]
        or not isinstance(identifier, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identifier)
        or not re.search(
            r"(?<![A-Za-z0-9])" + re.escape(identifier) + r"(?![A-Za-z0-9])",
            unquote(urlsplit(url).path),
        )
        or item.get("quantity", 1) != 1
    ):
        return None
    amount = _amount(item.get("price"))
    raw_prices = parser.meta.get("price", [])
    if (
        not amount
        or not raw_prices
        or any(
            _amount(raw) is None or Decimal(_amount(raw)) != Decimal(amount)
            for raw in raw_prices
        )
    ):
        return None
    if any(
        raw.strip() not in {"", "null", currency}
        for raw in parser.meta.get("priceCurrency", [])
    ):
        return None
    if "value" in commerce and (
        _amount(commerce["value"]) is None
        or Decimal(_amount(commerce["value"])) != Decimal(amount)
    ):
        return None
    return names[0], amount


def inspect_retail_html(url, html, currency, item):
    """Only the page's identified main Product may establish a price claim."""
    parser = RetailProductParser()
    parser.feed(html)
    title = " ".join(parser.h1).strip()
    products = []
    for script in parser.json_scripts:
        try:
            products.extend(_products(json.loads(script)))
        except (ValueError, RecursionError):
            continue
    explicit = [p for p in products if p.get("url") == url or p.get("@id") == url]
    by_name = [
        p
        for p in products
        if title and _fold(p.get("name", "")).strip() == _fold(title).strip()
    ]
    selected = explicit or by_name
    if (
        not selected
        and len(products) == 1
        and not title
        and not products[0].get("url")
        and not products[0].get("@id")
    ):
        selected = products
    if len(selected) > 1:
        return None
    if selected:
        title = str(selected[0].get("name") or title)
    ga4 = _ga4_microdata_price(parser, url, currency) if not products else None
    if ga4:
        title = ga4[0]
    if not title or not _matches_specification(item, title):
        return None
    prices = set()
    if ga4:
        prices.add(ga4[1])
    for product in selected:
        offers = product.get("offers", [])
        for offer in offers if isinstance(offers, list) else [offers]:
            if not isinstance(offer, dict) or offer.get("priceCurrency") != currency:
                continue
            # Aggregate/range prices, installments and variant price specs are
            # deliberately not interpreted as an exact unit purchase price.
            if (
                offer.get("@type") == "AggregateOffer"
                or "lowPrice" in offer
                or "highPrice" in offer
                or offer.get("priceSpecification")
            ):
                continue
            value = _amount(offer.get("price"))
            if value:
                prices.add(value)
    metadata_identity = bool(parser.product_scopes) and all(
        scope["names"]
        and all(_fold(name).strip() == _fold(title).strip() for name in scope["names"])
        for scope in parser.product_scopes
    )
    if (
        not products
        and metadata_identity
        and currency in parser.meta.get("priceCurrency", [])
    ):
        for raw in parser.meta.get("price", []):
            value = _amount(raw)
            if value:
                prices.add(value)
    if not prices:
        return None
    price, status = (None, "price_conflict")
    if len({Decimal(p) for p in prices}) == 1:
        price, status = price_status(next(iter(prices)), _fold(" ".join(parser.text)))
    return OfferObservation(
        title=title[:200],
        url=url,
        price=price,
        currency=currency,
        price_status=status,
        availability="Unconfirmed; check with retailer",
        location="Online offer; nearby branch stock unverified",
        notes="Observed public retailer-page price claim. Confirm requested specification, quantity, condition, taxes, delivery and other charges. Business location does not establish local stock or pickup.",
    )


class RetailLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.forms = [], []
        self.anchor, self.form = None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.anchor = [
                attrs["href"],
                [attrs.get("title", ""), attrs.get("aria-label", "")],
            ]
        if tag == "form":
            self.form = [
                attrs.get("action", ""),
                attrs.get("method", "get").lower(),
                [],
            ]
        if (
            tag == "input"
            and self.form is not None
            and attrs.get("name", "").lower() in {"search", "q", "s"}
            and attrs.get("type", "text").lower() in {"text", "search"}
        ):
            self.form[2].append(attrs["name"])

    def handle_data(self, text):
        if self.anchor is not None:
            self.anchor[1].append(text)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            self.links.append((self.anchor[0], " ".join(self.anchor[1])))
            self.anchor = None
        if tag == "form" and self.form is not None:
            self.forms.append(self.form)
            self.form = None


def discover_offers(item, currency, websites, *, http=None):
    """Return observed offers; bounded across three actual business origins.

    The outer deadline also bounds stalled DNS/TLS. Every subsequent dispatch
    checks the same cancellation flag; late DNS cannot initiate a request.
    """
    client = http or RetailHTTP()
    found = []
    errors = []

    def collect():
        visited = set()
        origins = set()
        for website in list(websites)[:20]:
            try:
                initial = public_url(website)
                parsed = urlsplit(initial)
                origin = "https://" + parsed.netloc
                if origin in origins:
                    continue
                if len(origins) >= MAX_ORIGINS:
                    break
                origins.add(origin)
                active_origin = origin
                queue = [initial]
                while (
                    queue
                    and client.requests < MAX_REQUESTS
                    and client.origin_requests.get(origin, 0) < MAX_ORIGIN_REQUESTS
                    and not client.expired.is_set()
                ):
                    target = queue.pop(0)
                    if target in visited:
                        continue
                    visited.add(target)
                    actual, html = client.page(
                        target, active_origin, budget_origin=origin
                    )
                    active_origin = "https://" + urlsplit(actual).netloc
                    offer = inspect_retail_html(actual, html, currency, item)
                    if offer is not None:
                        found.append(offer)
                        break
                    links = RetailLinks()
                    links.feed(html)
                    candidates = []
                    for href, label in links.links:
                        if not _matches(item, label):
                            continue
                        try:
                            candidates.append(
                                public_url(urljoin(actual, href), active_origin)
                            )
                        except RetailFetchError:
                            continue
                    for action, method, names in links.forms:
                        if method != "get" or len(names) != 1:
                            continue
                        try:
                            search = public_url(urljoin(actual, action), active_origin)
                            parts = urlsplit(search)
                            # Only the user's search term is forwarded, never
                            # hidden fields or action-query credentials.
                            search = urlunsplit(
                                (
                                    parts.scheme,
                                    parts.netloc,
                                    parts.path,
                                    urlencode({names[0]: item}),
                                    "",
                                )
                            )
                            candidates.append(search)
                        except RetailFetchError:
                            continue
                    # Follow newly observed relevant links before older generic
                    # search fallbacks. A category may already expose the exact
                    # product; all remaining GETs still honor robots/refusals.
                    queue[0:0] = [
                        candidate
                        for candidate in candidates[:10]
                        if candidate not in visited
                    ]
            except (RetailFetchError, OSError, ValueError, HTTPException):
                continue

    def run():
        try:
            collect()
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=run, daemon=True, name="forma-retail-discovery")
    worker.start()
    worker.join(max(0, client.deadline - client.clock()))
    if worker.is_alive():
        client.stop()
    if errors:
        raise RetailFetchError("discovery_failed") from errors[0]
    return tuple(found[:5])
