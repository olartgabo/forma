"""Coarse reverse lookup shares the map limiter and cannot replace GPS."""

from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

from forma_api.sourcing_location import (
    ConfirmedLocation,
    LocationServiceError,
    reverse_location,
)


def point():
    return ConfirmedLocation(
        latitude=37.774912,
        longitude=-122.419423,
        accuracy_m=25,
        location_basis="device",
        label="Approximate device area",
        confirmed=True,
        transfer_consented=True,
    )


def test_reverse_uses_only_rounded_point_city_zoom_and_keeps_device_origin(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return {
            "lat": "0",
            "lon": "0",
            "address": {
                "city": "San Francisco",
                "state": "California",
                "country": "United States",
                "country_code": "us",
                "house_number": "Never expose",
                "road": "Home",
            },
        }

    result = reverse_location(point(), fetch, tmp_path / "cache.db")
    assert result.location.latitude == 37.775 and result.location.longitude == -122.419
    assert (
        result.location.accuracy_m == 25 and result.location.location_basis == "device"
    )
    assert (
        result.location.city == "San Francisco" and result.location.country_code == "US"
    )
    assert result.suggested_currency == "USD"
    assert "Home" not in result.location.label and "Never" not in result.location.label
    query = parse_qs(urlsplit(calls[0]).query)
    assert (
        query["lat"] == ["37.775"]
        and query["lon"] == ["-122.419"]
        and query["zoom"] == ["10"]
    )
    assert reverse_location(point(), fetch, tmp_path / "cache.db") == result
    assert len(calls) == 1


@pytest.mark.parametrize(
    "country,currency", [("bo", "BOB"), ("de", "EUR"), ("gb", "GBP"), ("zz", None)]
)
def test_currency_is_editable_country_suggestion_not_fixed_city(
    tmp_path, country, currency
):
    result = reverse_location(
        point(),
        lambda url: {"address": {"city": "Any city", "country_code": country}},
        tmp_path / "cache.db",
    )
    assert result.suggested_currency == currency


def test_invalid_reverse_result_and_missing_consent_fail_without_model_calls(tmp_path):
    with pytest.raises(LocationServiceError):
        reverse_location(
            point(), lambda url: {"error": "Unable to geocode"}, tmp_path / "cache.db"
        )
    with pytest.raises(ValidationError):
        ConfirmedLocation(**{**point().model_dump(), "transfer_consented": False})
