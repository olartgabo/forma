"""Map lookups use injected transport; these tests make no network calls."""

import json
from http.client import HTTPResponse
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

from forma_api.sourcing_location import (
    ConfirmedLocation,
    LocationServiceError,
    NearbyRequest,
    _json_request,
    geocode_city,
    haversine_m,
    nearby_places,
    overpass_places,
)


@pytest.mark.parametrize("text_size", [20, 70000])
def test_real_http_response_eof_closes_fp_without_losing_json(monkeypatch, text_size):
    """Exercise HTTPResponse.read1's real Content-Length/closed-fp behavior."""
    payload = json.dumps({"name": "a" * text_size}).encode()
    timeouts = []

    class WireFile(BytesIO):
        raw = SimpleNamespace(_sock=SimpleNamespace(settimeout=timeouts.append))

    wire = WireFile(
        b"HTTP/1.1 200 OK\r\nContent-Length: "
        + str(len(payload)).encode()
        + b"\r\n\r\n"
        + payload
    )
    response = HTTPResponse(SimpleNamespace(makefile=lambda mode: wire), method="GET")
    response.begin()
    requests = []

    def open_response(request, timeout):
        requests.append((request.full_url, timeout))
        return response

    monkeypatch.setattr(
        "forma_api.sourcing_location.build_opener",
        lambda handler: SimpleNamespace(open=open_response),
    )
    assert _json_request("https://nominatim.openstreetmap.org/search?q=city") == {
        "name": "a" * text_size
    }
    assert response.fp is None
    assert requests == [("https://nominatim.openstreetmap.org/search?q=city", 25)]
    assert len(timeouts) == (1 if text_size < 65536 else 2)
    assert all(0 < value <= 25 for value in timeouts)


def point(**changes):
    return ConfirmedLocation(
        latitude=37.77491,
        longitude=-122.41942,
        accuracy_m=20,
        location_basis="device",
        label="My approximate area",
        confirmed=True,
        transfer_consented=True,
        **changes,
    )


def test_location_requires_consent_confirmation_and_real_accuracy():
    values = point().model_dump()
    for changes in (
        {"confirmed": False},
        {"transfer_consented": False},
        {"accuracy_m": None},
        {"latitude": float("nan")},
        {"longitude": 181},
    ):
        with pytest.raises(ValidationError):
            ConfirmedLocation(**{**values, **changes})
    coarse = point().coarse()
    assert (coarse.latitude, coarse.longitude, coarse.accuracy_m) == (
        37.775,
        -122.419,
        100,
    )


def test_city_choices_preserve_ambiguity_and_cache_across_calls(tmp_path):
    calls = []
    rows = [
        {
            "osm_type": "relation",
            "osm_id": index,
            "display_name": name,
            "lat": "-17.39",
            "lon": "-66.16",
            "address": {"country_code": "bo"},
        }
        for index, name in enumerate(
            (
                "Cochabamba, city",
                "Cochabamba, state",
                "Cochabamba, district",
                "ignored",
            ),
            1,
        )
    ]

    def fetch(url):
        calls.append(url)
        return rows

    path = tmp_path / "cache.sqlite3"
    choices = geocode_city("Cochabamba", fetch, path).choices
    assert len(choices) == 3 and choices[0].country_code == "BO"
    assert choices[0].accuracy_m is None and choices[0].location_basis == "city_center"
    assert "confirmed" not in choices[0].model_dump()
    assert geocode_city("COCHABAMBA", fetch, path).choices == choices
    assert len(calls) == 1
    assert parse_qs(urlsplit(calls[0]).query)["limit"] == ["3"]


def test_geocoder_global_clock_survives_new_connection(tmp_path, monkeypatch):
    current = [100]
    sleeps = []
    monkeypatch.setattr("forma_api.sourcing_location.time.time", lambda: current[0])
    monkeypatch.setattr("forma_api.sourcing_location.time.sleep", sleeps.append)
    path = tmp_path / "cache.sqlite3"
    geocode_city("city one", lambda url: [], path)
    current[0] = 100.2
    geocode_city("city two", lambda url: [], path)
    assert sleeps == [pytest.approx(0.85)]


def test_nearby_query_is_scoped_coarse_and_distances_are_honest():
    calls = []
    raw = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 37.776,
                "lon": -122.419,
                "tags": {
                    "name": "Hardware",
                    "shop": "hardware",
                    "website": "https://hardware.example/",
                    "addr:street": "Market Street",
                },
            },
            {
                "type": "node",
                "id": 2,
                "lat": -17.39,
                "lon": -66.16,
                "tags": {"name": "Outside radius", "shop": "hardware"},
            },
            {
                "type": "node",
                "id": 3,
                "lat": 37.775,
                "lon": -122.419,
                "tags": {"name": "Wrong kind", "shop": "stationery"},
            },
        ]
    }
    result = overpass_places(
        NearbyRequest(location=point(), radius_m=1000),
        lambda url, data: calls.append((url, data)) or raw,
    )
    query = parse_qs(calls[0][1].decode())["data"][0]
    assert "around:1000,37.775,-122.419" in query and "timeout:20" in query
    assert len(result.places) == 1 and result.places[0].distance_m == 111
    place = result.places[0]
    assert (place.distance_min_m, place.distance_max_m) == (11, 212)
    assert place.osm_url == "https://www.openstreetmap.org/node/1"
    assert (
        "stock are unverified" in result.message
        and "OpenStreetMap" in result.attribution
    )


def test_city_center_has_no_fake_user_distance_range():
    location = ConfirmedLocation(
        latitude=-17.39,
        longitude=-66.16,
        location_basis="city_center",
        label="Cochabamba",
        confirmed=True,
        transfer_consented=True,
    )
    rows = {
        "elements": [
            {
                "type": "way",
                "id": 4,
                "center": {"lat": -17.3901, "lon": -66.1601},
                "tags": {
                    "name": "Tools",
                    "shop": "hardware",
                    "website": "http://tools.example",
                },
            }
        ]
    }
    result = overpass_places(NearbyRequest(location=location), lambda *args: rows)
    assert result.places[0].distance_min_m is None
    assert result.places[0].distance_max_m is None
    assert result.places[0].website is None
    assert "selected city center" in result.message


def test_empty_incomplete_and_boundaries():
    request = NearbyRequest(location=point())
    assert overpass_places(request, lambda *args: {"elements": []}).status == "empty"
    with pytest.raises(LocationServiceError):
        overpass_places(request, lambda *args: {"elements": [], "remark": "timeout"})
    for changes in ({"radius_m": 10001}, {"category": 'hardware"];out;'}):
        with pytest.raises(ValidationError):
            NearbyRequest(location=point(), **changes)
    assert haversine_m(0, 0, 0, 1) == pytest.approx(111195, abs=1)
    assert json.loads(request.model_dump_json())["location"]["confirmed"] is True


def test_bounded_nominatim_is_single_cached_category_lookup(tmp_path):
    calls = []
    row = {
        "osm_type": "node",
        "osm_id": 10,
        "category": "shop",
        "type": "hardware",
        "lat": 37.776,
        "lon": -122.419,
        "name": "Sourced hardware",
        "address": {"road": "Market Street"},
        "extratags": {"website": "https://hardware.example/"},
    }
    result = nearby_places(
        NearbyRequest(location=point(), radius_m=5000),
        lambda url: calls.append(url) or [row],
        tmp_path / "cache.sqlite3",
    )
    params = parse_qs(urlsplit(calls[0]).query)
    assert params["bounded"] == ["1"] and params["q"] == ["[hardware store]"]
    assert params["limit"] == ["10"] and len(params["viewbox"][0].split(",")) == 4
    assert result.places[0].name == "Sourced hardware"
    assert result.places[0].website == "https://hardware.example/"
    assert (
        nearby_places(
            NearbyRequest(location=point(), radius_m=5000),
            lambda url: pytest.fail("Cached query must not dispatch"),
            tmp_path / "cache.sqlite3",
        )
        == result
    )


@pytest.mark.parametrize(
    "category,phrase",
    [
        ("hardware", "[hardware store]"),
        ("stationery", "[stationery shop]"),
        ("doityourself", "[do-it-yourself]"),
    ],
)
def test_nominatim_categories_use_documented_typed_search_not_name_keyword(
    tmp_path, category, phrase
):
    calls = []
    # Names deliberately contain none of the English category keywords.
    row = {
        "osm_type": "node",
        "osm_id": 12,
        "category": "shop",
        "type": category,
        "lat": 37.776,
        "lon": -122.419,
        "name": "Tienda San Martín",
        "address": {},
        "extratags": {},
    }
    result = nearby_places(
        NearbyRequest(location=point(), category=category),
        lambda url: calls.append(url) or [row],
        tmp_path / "cache.sqlite3",
    )
    assert len(calls) == 1
    assert parse_qs(urlsplit(calls[0]).query)["q"] == [phrase]
    assert result.places[0].name == "Tienda San Martín"
    assert result.places[0].category == category


def test_unsupported_craft_category_does_not_send_undocumented_query(tmp_path):
    result = nearby_places(
        NearbyRequest(location=point(), category="craft"),
        lambda url: pytest.fail("Unsupported category must not dispatch a name search"),
        tmp_path / "cache.sqlite3",
    )
    assert result.status == "empty" and result.places == ()
    assert "does not support craft-shop" in result.message
