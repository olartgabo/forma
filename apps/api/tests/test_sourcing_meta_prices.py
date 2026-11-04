"""Meta finds actual URLs; permitted structured sources establish numeric prices."""

import json
import ssl

import pytest

from forma_api.model_gateway import GatewayError
from forma_api.retail_evidence import PinnedHTTPSConnection, inspect_retail_html
from forma_api.sourcing import OfferObservation, ResearchRequest
from forma_api.sourcing_gateway import SourcingGateway


class Transport:
    def post(self, path, payload, timeout):
        self.payload = payload
        return {
            "id": "resp_known",
            "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "output": [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {"type": "search"},
                    "results": [
                        {
                            "title": "Fiskars scissors 1 pc",
                            "url": "https://retailer.example/products/scissors",
                            "snippet": "",
                        },
                        {
                            "title": "Fiskars scissors",
                            "url": "https://www.facebook.com/marketplace/item/12",
                            "snippet": "USD 1",
                        },
                    ],
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "The source has no price excerpt. https://invented.example/scissors USD 1",
                            "annotations": [],
                        }
                    ],
                },
            ],
        }


def request():
    return ResearchRequest(
        expected_revision_id="inventory-one",
        idempotency_key="one-generation",
        item="Fiskars scissors",
        area="San Francisco",
        currency="USD",
        provider_transfer_consented=True,
        location={
            "latitude": 37.775,
            "longitude": -122.419,
            "accuracy_m": 20,
            "location_basis": "device",
            "label": "San Francisco",
            "city": "San Francisco",
            "region": "California",
            "country_code": "US",
            "confirmed": True,
            "transfer_consented": True,
        },
    )


def test_exact_tool_urls_drive_inspection_even_without_model_urls_or_excerpts():
    calls = []
    t = Transport()
    verified = OfferObservation(
        title="Fiskars scissors",
        url="https://retailer.example/products/scissors",
        price="12.99",
        currency="USD",
        price_status="listed",
    )
    g = SourcingGateway(t, price_lookup=lambda *args: calls.append(args) or (verified,))
    offers, usage = g.research(request())
    assert calls == [
        ("Fiskars scissors", "USD", ("https://retailer.example/products/scissors",))
    ]
    assert offers == (verified,) and usage.input_tokens == 100
    assert t.payload["tools"][0]["user_location"] == {
        "type": "approximate",
        "country": "US",
        "city": "San Francisco",
        "region": "California",
    }
    transferred = json.dumps(t.payload)
    assert "37.775" not in transferred and "-122.419" not in transferred
    assert t.payload["max_tool_calls"] == 1


def test_refused_or_unpriced_source_never_accepts_model_invented_price():
    offers, _ = SourcingGateway(Transport(), price_lookup=lambda *args: ()).research(
        request()
    )
    assert len(offers) == 1 and offers[0].price is None
    assert offers[0].price_status == "price_unknown"
    assert offers[0].url == "https://retailer.example/products/scissors"


def test_terminal_output_limit_is_known_incomplete_and_preserves_usage():
    with pytest.raises(GatewayError) as error:
        SourcingGateway(Transport()).parse_response(
            {
                "id": "resp_incomplete",
                "status": "incomplete",
                "usage": {"input_tokens": 5077, "output_tokens": 2200},
            },
            request(),
        )
    assert error.value.code == "research_incomplete"
    assert error.value.sourcing_usage.output_tokens == 2200
    assert error.value.sourcing_response_id == "resp_incomplete"


def test_portable_ca_bundle_keeps_certificate_and_hostname_verification():
    connection = PinnedHTTPSConnection("retailer.example", "8.8.8.8", 1)
    assert connection._context.verify_mode == ssl.CERT_REQUIRED
    assert connection._context.check_hostname
    assert connection._context.get_ca_certs()


@pytest.mark.parametrize(
    "qualifier",
    [
        "From $12.50",
        "From USD12.50",
        "From US$12.50",
        "From £12.50",
        "From Bs.12.50",
        "From 12.50",
    ],
)
def test_partial_price_qualifiers_cannot_become_exact_product_prices(qualifier):
    html = (
        "<h1>Fiskars scissors</h1><p>"
        + qualifier
        + '</p><script type="application/ld+json">'
        + json.dumps(
            {
                "@type": "Product",
                "name": "Fiskars scissors",
                "url": "https://retailer.example/scissors",
                "offers": {"@type": "Offer", "price": "12.50", "priceCurrency": "USD"},
            }
        )
        + "</script>"
    )
    result = inspect_retail_html(
        "https://retailer.example/scissors", html, "USD", "Fiskars scissors"
    )
    assert result.price is None and result.price_status == "partial_price"
