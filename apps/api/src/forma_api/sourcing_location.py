"""Explicit, coarse location and bounded public OpenStreetMap lookups.

Public endpoints are demo services, configurable for a hosted provider. No IP
location, autocomplete, background search or provider/model credentials are used.
"""

import json
import math
import os
import sqlite3
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import Field, StrictBool, field_validator, model_validator

from forma_domain.models import Record

Category = Literal["hardware", "stationery", "doityourself", "craft"]
ATTRIBUTION = (
    "© OpenStreetMap contributors, ODbL. https://www.openstreetmap.org/copyright"
)


class LocationChoice(Record):
    id: str
    label: str = Field(min_length=1, max_length=500)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)
    location_basis: Literal["city_center"] = "city_center"
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)


class ConfirmedLocation(Record):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)
    location_basis: Literal["city_center", "device"]
    label: str = Field(min_length=1, max_length=500)
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    confirmed: Literal[True]
    transfer_consented: StrictBool

    @model_validator(mode="after")
    def explicit_location(self):
        if not self.transfer_consented:
            raise ValueError(
                "Consent to send this approximate point to OpenStreetMap is required"
            )
        if self.location_basis == "device" and not self.accuracy_m:
            raise ValueError("Device location needs reported accuracy")
        if self.location_basis == "city_center" and self.accuracy_m is not None:
            raise ValueError(
                "City-center distance does not establish your location accuracy"
            )
        return self

    def coarse(self):
        # Rounding at three decimals moves a point by at most 79m on Earth.
        if self.location_basis != "device":
            return self
        return self.model_copy(
            update={
                "latitude": round(self.latitude, 3),
                "longitude": round(self.longitude, 3),
                "accuracy_m": self.accuracy_m + 80,
            }
        )


class LocationSearchRequest(Record):
    city: str = Field(min_length=2, max_length=120)
    transfer_consented: StrictBool

    @field_validator("city")
    @classmethod
    def city_text(cls, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Enter a city or town")
        return value


class LocationSearchResponse(Record):
    choices: tuple[LocationChoice, ...] = Field(default=(), max_length=3)
    attribution: str = ATTRIBUTION


class LocationReverseRequest(Record):
    location: ConfirmedLocation


class LocationReverseResponse(Record):
    location: ConfirmedLocation
    suggested_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    attribution: str = ATTRIBUTION


class NearbyRequest(Record):
    location: ConfirmedLocation
    radius_m: int = Field(default=5000, ge=100, le=10000)
    category: Category = "hardware"


class NearbyPlace(Record):
    id: str
    name: str
    latitude: float
    longitude: float
    distance_m: int
    distance_min_m: int | None = None
    distance_max_m: int | None = None
    address: str
    website: str | None = None
    osm_url: str
    category: Category


class NearbyResponse(Record):
    places: tuple[NearbyPlace, ...] = Field(default=(), max_length=10)
    status: Literal["found", "empty"]
    attribution: str = ATTRIBUTION
    message: str


class LocationServiceError(Exception):
    """Known public-service failure, without a model generation outcome."""


def _origin(env, default):
    origin = os.environ.get(env, default).rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise LocationServiceError(
            "Location service requires a configured HTTPS origin"
        )
    return origin


def _json_request(url, data=None):
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    request = Request(
        url,
        data=data,
        headers={
            "User-Agent": os.environ.get(
                "FORMA_OSM_USER_AGENT",
                "FORMA-hackathon-demo/1.0 (+https://github.com/olartgabo/forma)",
            ),
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        deadline = time.monotonic() + 25
        payload = bytearray()
        with build_opener(NoRedirect()).open(request, timeout=25) as response:
            while len(payload) <= 2_000_000:
                # HTTPResponse.read1 closes fp immediately when Content-Length
                # reaches zero. Successful EOF must not dereference that fp.
                if response.fp is None:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Lookup deadline exceeded")
                response.fp.raw._sock.settimeout(remaining)
                chunk = response.read1(min(65536, 2_000_001 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
        if len(payload) > 2_000_000:
            raise ValueError("Response too large")
        return json.loads(payload)
    except Exception as exc:
        raise LocationServiceError(
            "The map service could not complete this lookup. Try again later."
        ) from exc


def _nominatim_search(params, fetch=None, cache_path=None, *, reverse=False):
    """Shared cross-worker rate limit and 24h cache for explicit lookups."""
    fetch = fetch or _json_request
    origin = _origin("FORMA_NOMINATIM_ORIGIN", "https://nominatim.openstreetmap.org")
    key = origin + ("/reverse?" if reverse else "/search?") + urlencode(params)
    path = Path(
        cache_path
        or os.environ.get(
            "FORMA_OSM_CACHE_PATH",
            str(
                Path(os.environ.get("FORMA_DATA_DIR", ".local/forma"))
                / "osm-lookups.sqlite3"
            ),
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=30) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS city_cache (query TEXT PRIMARY KEY, observed REAL, body TEXT)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS service_clock (id INTEGER PRIMARY KEY, last_call REAL)"
        )
        connection.execute("BEGIN IMMEDIATE")
        cached = connection.execute(
            "SELECT observed,body FROM city_cache WHERE query=?", (key,)
        ).fetchone()
        if cached and time.time() - cached[0] < 86400:
            return json.loads(cached[1])
        previous = connection.execute(
            "SELECT last_call FROM service_clock WHERE id=1"
        ).fetchone()
        delay = 1.05 - (time.time() - previous[0]) if previous else 0
        if delay > 0:
            time.sleep(delay)
        connection.execute(
            "INSERT OR REPLACE INTO service_clock VALUES (1,?)", (time.time(),)
        )
        try:
            raw = fetch(key)
        except Exception:
            connection.commit()  # Failed lookups still count toward 1rps.
            raise
        if not isinstance(raw, dict if reverse else list):
            connection.commit()
            raise LocationServiceError("The map service returned an invalid response")
        connection.execute(
            "DELETE FROM city_cache WHERE observed < ?", (time.time() - 86400,)
        )
        connection.execute(
            "INSERT OR REPLACE INTO city_cache VALUES (?,?,?)",
            (key, time.time(), json.dumps(raw)),
        )
        return raw


def geocode_city(city: str, fetch=None, cache_path=None) -> LocationSearchResponse:
    raw = _nominatim_search(
        {
            "q": city.casefold().strip(),
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 3,
        },
        fetch,
        cache_path,
    )
    choices = []
    for row in raw[:3]:
        if not isinstance(row, dict):
            continue
        try:
            if (
                row.get("osm_type") not in ("node", "way", "relation")
                or int(row.get("osm_id", 0)) <= 0
            ):
                continue
            address = row.get("address") or {}
            if not isinstance(address, dict):
                continue
            country = str(address.get("country_code", "")).upper() or None
            choices.append(
                LocationChoice(
                    id=f"{row['osm_type']}/{row['osm_id']}",
                    label=row["display_name"][:500],
                    latitude=float(row["lat"]),
                    longitude=float(row["lon"]),
                    country_code=country,
                    city=str(
                        address.get("city")
                        or address.get("town")
                        or address.get("village")
                        or ""
                    )[:120]
                    or None,
                    region=str(address.get("state") or address.get("region") or "")[
                        :120
                    ]
                    or None,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return LocationSearchResponse(choices=tuple(choices))


def reverse_location(location: ConfirmedLocation, fetch=None, cache_path=None):
    """Resolve city metadata from a consented rounded point, never replace it.

    Zoom 10 deliberately requests city-level context rather than a home address.
    Both reverse and search share the application-wide rate limit and cache.
    """
    latitude, longitude = round(location.latitude, 3), round(location.longitude, 3)
    raw = _nominatim_search(
        {
            "lat": latitude,
            "lon": longitude,
            "format": "jsonv2",
            "addressdetails": 1,
            "zoom": 10,
        },
        fetch,
        cache_path,
        reverse=True,
    )
    address = raw.get("address")
    if not isinstance(address, dict) or raw.get("error"):
        raise LocationServiceError(
            "Could not identify the city for this approximate location"
        )
    city = (
        str(
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or ""
        )[:120]
        or None
    )
    region = str(address.get("state") or address.get("region") or "")[:120] or None
    country = str(address.get("country_code", "")).upper()
    if len(country) != 2 or not country.isascii() or not country.isalpha():
        raise LocationServiceError("The map service did not identify the country")
    label = ", ".join(
        dict.fromkeys(
            part
            for part in (city, region, str(address.get("country") or country)[:120])
            if part
        )
    )
    # These are editable suggestions from ISO country metadata, not a fixed city
    # or an inferred currency for countries with no unambiguous default here.
    currencies = {
        "US": "USD",
        "BO": "BOB",
        "GB": "GBP",
        "CA": "CAD",
        "AU": "AUD",
        "NZ": "NZD",
        "JP": "JPY",
        "CN": "CNY",
        "IN": "INR",
        "BR": "BRL",
        "AR": "ARS",
        "CL": "CLP",
        "CO": "COP",
        "PE": "PEN",
        "MX": "MXN",
        "CH": "CHF",
        "ZA": "ZAR",
        "KR": "KRW",
        "EC": "USD",
        "SG": "SGD",
    }
    euro = {
        "AT",
        "BE",
        "HR",
        "CY",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PT",
        "SK",
        "SI",
        "ES",
    }
    return LocationReverseResponse(
        location=location.model_copy(
            update={
                "latitude": latitude,
                "longitude": longitude,
                "city": city,
                "region": region,
                "country_code": country,
                "label": label,
            }
        ),
        suggested_currency="EUR" if country in euro else currencies.get(country),
    )


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    delta_lat, delta_lon = lat2 - lat1, math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6371000 * 2 * math.asin(min(1, math.sqrt(a)))


def overpass_places(request: NearbyRequest, fetch=None) -> NearbyResponse:
    fetch = fetch or _json_request
    point = request.location.coarse()
    query = f'[out:json][timeout:20];nwr(around:{request.radius_m},{point.latitude},{point.longitude})["shop"="{request.category}"];out center 30;'
    url = (
        _origin("FORMA_OVERPASS_ORIGIN", "https://overpass-api.de") + "/api/interpreter"
    )
    raw = fetch(url, urlencode({"data": query}).encode())
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("elements"), list)
        or raw.get("remark")
    ):
        raise LocationServiceError(
            "The nearby map service returned an incomplete response"
        )
    return _place_result(request, point, raw["elements"][:30])


def nearby_places(
    request: NearbyRequest, fetch=None, cache_path=None
) -> NearbyResponse:
    """One user-scoped category search, never systematic POI enumeration.

    Public Nominatim special phrases are suitable only for the bounded demo.
    A hosted deployment must configure an appropriate provider for its traffic.
    No retry or second public-service query occurs after a failed request.
    """
    if os.environ.get("FORMA_NEARBY_PROVIDER", "nominatim") == "overpass":
        return overpass_places(request, fetch)
    # These exact special phrases map to shop tags. Plain "hardware" searches
    # names and misses shops named in another language. Brackets force type-only
    # search within the small bounded viewbox (Nominatim Search API docs).
    phrase = {
        "hardware": "[hardware store]",
        "stationery": "[stationery shop]",
        "doityourself": "[do-it-yourself]",
    }.get(request.category)
    if phrase is None:
        return NearbyResponse(
            status="empty",
            message="This map provider does not support craft-shop category searches. Choose hardware, stationery or DIY stores instead.",
        )
    point = request.location.coarse()
    lat_delta = math.degrees(request.radius_m / 6371000)
    lon_delta = min(180, lat_delta / max(0.001, math.cos(math.radians(point.latitude))))
    box = (
        max(-180, point.longitude - lon_delta),
        min(90, point.latitude + lat_delta),
        min(180, point.longitude + lon_delta),
        max(-90, point.latitude - lat_delta),
    )
    raw = _nominatim_search(
        {
            "q": phrase,
            "format": "jsonv2",
            "bounded": 1,
            "viewbox": ",".join(f"{part:.6f}" for part in box),
            "limit": 10,
            "addressdetails": 1,
            "extratags": 1,
        },
        fetch,
        cache_path,
    )
    elements = []
    for row in raw[:10]:
        if not isinstance(row, dict):
            continue
        address = row.get("address", {})
        extra = row.get("extratags") or {}
        if not isinstance(address, dict) or not isinstance(extra, dict):
            continue
        # Only actual shop results in the requested category enter place evidence.
        if (
            row.get("class", row.get("category")) != "shop"
            or row.get("type") != request.category
        ):
            continue
        elements.append(
            {
                "type": row.get("osm_type"),
                "id": row.get("osm_id"),
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "tags": {
                    "name": row.get("name")
                    or row.get("display_name", "").split(",")[0],
                    "shop": request.category,
                    "website": extra.get("website") or extra.get("contact:website"),
                    "addr:housenumber": address.get("house_number"),
                    "addr:street": address.get("road"),
                    "addr:city": address.get("city") or address.get("town"),
                    "addr:postcode": address.get("postcode"),
                },
            }
        )
    return _place_result(request, point, elements)


def _place_result(request, point, elements):
    places = []
    seen = set()
    for row in elements:
        if not isinstance(row, dict):
            continue
        try:
            tags = row.get("tags", {})
            if not isinstance(tags, dict):
                continue
            center = row if "lat" in row else row.get("center", {})
            lat, lon = float(center["lat"]), float(center["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            distance = haversine_m(point.latitude, point.longitude, lat, lon)
            name = tags.get("name")
            if (
                not name
                or distance > request.radius_m
                or tags.get("shop") != request.category
            ):
                continue
            identity = f"{row['type']}/{int(row['id'])}"
            if (
                row["type"] not in ("node", "way", "relation")
                or int(row["id"]) <= 0
                or identity in seen
            ):
                continue
            seen.add(identity)
            website = tags.get("website") or tags.get("contact:website")
            from forma_api.sourcing import permitted_url

            if not isinstance(website, str) or not permitted_url(website):
                website = None
            uncertainty = point.accuracy_m if point.location_basis == "device" else None
            places.append(
                NearbyPlace(
                    id=identity,
                    name=name[:200],
                    latitude=lat,
                    longitude=lon,
                    distance_m=round(distance),
                    distance_min_m=max(0, math.floor(distance - uncertainty))
                    if uncertainty is not None
                    else None,
                    distance_max_m=math.ceil(distance + uncertainty)
                    if uncertainty is not None
                    else None,
                    address=", ".join(
                        str(tags[key])
                        for key in (
                            "addr:housenumber",
                            "addr:street",
                            "addr:city",
                            "addr:postcode",
                        )
                        if tags.get(key)
                    )[:500]
                    or "Address not mapped",
                    website=website,
                    osm_url="https://www.openstreetmap.org/" + identity,
                    category=request.category,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    places.sort(key=lambda place: place.distance_m)
    selected = tuple(places[:10])
    basis = (
        "the selected city center"
        if point.location_basis == "city_center"
        else "your approximate device point"
    )
    return NearbyResponse(
        places=selected,
        status="found" if selected else "empty",
        message=f"Straight-line distances from {basis}; map coverage and branch stock are unverified. Online offers do not confirm nearby pickup."
        if selected
        else "No mapped shops found within this radius. Map coverage may be incomplete; try another category or radius.",
    )
