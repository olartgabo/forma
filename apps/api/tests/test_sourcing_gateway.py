import json

import pytest

from forma_api.model_gateway import GatewayError
from forma_api.sourcing import ResearchRequest, permitted_url, price_status
from forma_api.sourcing_gateway import SourcingGateway

REQUEST = dict(
    expected_revision_id="inventory-a",
    idempotency_key="research-1",
    item="tape 2 rolls",
    area="La Paz",
    currency="BOB",
    provider_transfer_consented=True,
)


class Fake:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, payload, timeout):
        self.calls.append((path, payload, timeout))
        return self.response


def response(offers, citations=None, searched=True):
    return {
        "status": "completed",
        "output": (
            [{"type": "web_search_call", "status": "completed"}] if searched else []
        )
        + [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"offers": offers}),
                        "annotations": [
                            {"type": "url_citation", "url": u}
                            for u in (citations or ["https://shop.example/tape"])
                        ],
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 20, "output_tokens": 30},
    }


def offer(**kw):
    return dict(
        title="Tape",
        url="https://shop.example/tape",
        price="20",
        currency="BOB",
        notes="Shipping unknown",
        **kw,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://shop.example",
        "https://facebook.com/marketplace/x",
        "https://m.facebook.com/x",
        "https://meta.ai/x",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://user:pass@shop.example/x",
        "https://shop.example:22/x",
    ],
)
def test_source_policy(url):
    assert not permitted_url(url)


@pytest.mark.parametrize(
    "price,text,status",
    [
        ("0", "DM for price", "price_unknown"),
        ("0", "gratis retiro", "listed_free"),
        ("2", "desde 2", "partial_price"),
        ("0", "tape", "price_unknown"),
        ("-1", "", "price_unknown"),
        ("NaN", "", "price_unknown"),
        ("20", "delivery unknown", "listed"),
    ],
)
def test_prices(price, text, status):
    assert price_status(price, text)[1] == status


def test_citations_search_and_standard_model():
    fake = Fake(response([offer()]))
    offers, usage = SourcingGateway(fake).research(ResearchRequest(**REQUEST))
    assert len(offers) == 1 and usage.input_tokens == 20
    path, payload, timeout = fake.calls[0]
    assert path == "/responses" and payload["model"] == "muse-spark-1.3"
    assert payload["tools"][0]["type"] == "web_search" and timeout == 30
    assert "expected_revision_id" not in payload["input"][1]["content"]
    assert "provider_transfer_consented" not in payload["input"][1]["content"]


@pytest.mark.parametrize(
    "searched,citations",
    [
        (False, None),
        (True, ["https://facebook.com/marketplace/x"]),
        (True, ["https://other.example/x"]),
    ],
)
def test_no_grounded_sources_means_no_offers(searched, citations):
    fake = Fake(response([offer()], citations, searched))
    assert SourcingGateway(fake).research(ResearchRequest(**REQUEST))[0] == ()


def test_invalid_provider_payload_safe():
    with pytest.raises(GatewayError):
        SourcingGateway(Fake({"output": "private data"})).research(
            ResearchRequest(**REQUEST)
        )


def test_default_factory_uses_only_server_key_without_network(monkeypatch):
    from forma_api import sourcing_gateway

    captured = []
    monkeypatch.setattr(
        sourcing_gateway, "SourcingHTTP", lambda key: captured.append(key) or object()
    )
    monkeypatch.setenv("MODEL_API_KEY", "server-only-test-key")
    assert isinstance(sourcing_gateway.default_gateway_factory(), SourcingGateway)
    assert captured == ["server-only-test-key"]


def test_missing_server_key_fails_without_network(monkeypatch):
    from forma_api.sourcing_gateway import default_gateway_factory

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(GatewayError, match="missing_key"):
        default_gateway_factory()


def test_citation_without_price_evidence_cannot_supply_price():
    offers, _ = SourcingGateway(Fake(response([offer()]))).research(
        ResearchRequest(**REQUEST)
    )
    assert offers[0].price is None and offers[0].price_status == "price_unknown"


def test_price_with_tool_evidence_and_conflict():
    value = response([offer()])
    value["output"][0]["results"] = [
        {
            "url": "https://shop.example/tape",
            "content": "Tape 20 BOB, delivery not included",
        }
    ]
    offers, _ = SourcingGateway(Fake(value)).research(ResearchRequest(**REQUEST))
    assert offers[0].price == "20"
    raw = offer()
    raw["price_status"] = "price_conflict"
    value = response([raw])
    value["output"][0]["results"] = [{"url": raw["url"], "content": "20 BOB"}]
    offers, _ = SourcingGateway(Fake(value)).research(ResearchRequest(**REQUEST))
    assert offers[0].price is None and offers[0].price_status == "price_conflict"


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "incomplete", "output": []},
        {"status": "completed", "output": [{"type": "message", "content": None}]},
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "{}", "annotations": None}
                    ],
                }
            ],
        },
    ],
)
def test_malformed_and_incomplete_results_raise_safe_error(bad):
    with pytest.raises(GatewayError):
        SourcingGateway(Fake(bad)).research(ResearchRequest(**REQUEST))


def test_dimension_number_is_not_price_evidence():
    value = response([offer()])
    value["output"][0]["results"] = [
        {
            "url": "https://shop.example/tape",
            "content": "Tape 20 mm; select currency BOB at checkout",
        }
    ]
    offers, _ = SourcingGateway(Fake(value)).research(ResearchRequest(**REQUEST))
    assert offers[0].price is None


@pytest.mark.parametrize("price", [True, 2.3, {}, "2" * 100])
def test_malformed_prices_stay_unknown(price):
    assert price_status(price, "tape")[1] == "price_unknown"


@pytest.mark.parametrize(
    "excerpt,amount,status",
    [
        ("Desde 20 BOB", "20", "partial_price"),
        ("Deposit 20 BOB; total 100 BOB", "20", "partial_price"),
        ("20 BOB, DM for the real price", "20", "price_unknown"),
        ("Precio 20 BOB; consultar precio al privado", "20", "price_unknown"),
        ("Was 100 BOB, now 20 BOB", "20", "price_conflict"),
        ("Option A 20 BOB, option B 40 BOB", "20", "price_conflict"),
        ("20 BOB per roll; price 20.00 BOB", "20", "listed"),
        ("0 BOB, envio gratis", "0", "price_unknown"),
        ("0 BOB, gratis envio", "0", "price_unknown"),
        ("0 BOB, free shipping", "0", "price_unknown"),
        ("0 BOB, free to collect", "0", "listed_free"),
    ],
)
def test_source_qualifiers_cannot_be_laundered_by_model_summary(
    excerpt, amount, status
):
    raw = offer()
    raw["price"] = amount
    value = response([raw])
    value["output"][0]["results"] = [{"url": raw["url"], "content": excerpt}]
    offers, _ = SourcingGateway(Fake(value)).research(ResearchRequest(**REQUEST))
    assert offers[0].price_status == status
    if status not in ("listed", "listed_free"):
        assert offers[0].price is None


def test_duplicated_source_does_not_erase_qualifier():
    raw = offer()
    value = response([raw])
    value["output"][0]["results"] = [
        {"url": raw["url"], "content": "Desde 20 BOB"},
        {"url": raw["url"], "content": "20 BOB"},
    ]
    offers, _ = SourcingGateway(Fake(value)).research(ResearchRequest(**REQUEST))
    assert offers[0].price is None and offers[0].price_status == "partial_price"


def test_completed_malformed_json_preserves_reported_usage():
    value = response([offer()])
    value["output"][1]["content"][0]["text"] = "not json"
    with pytest.raises(GatewayError) as error:
        SourcingGateway(Fake(value)).research(ResearchRequest(**REQUEST))
    assert error.value.sourcing_usage.input_tokens == 20
    assert error.value.sourcing_usage.output_tokens == 30


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "incomplete",
            "output": [],
            "usage": {"input_tokens": 21, "output_tokens": 8, "web_search_queries": 2},
        },
        {
            "status": "completed",
            "output": None,
            "usage": {"input_tokens": 21, "output_tokens": 8, "web_search_queries": 2},
        },
        {
            "status": "completed",
            "output": [{"type": "message", "content": None}],
            "usage": {"input_tokens": 21, "output_tokens": 8, "web_search_queries": 2},
        },
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "{}", "annotations": None}
                    ],
                }
            ],
            "usage": {"input_tokens": 21, "output_tokens": 8, "web_search_queries": 2},
        },
    ],
)
def test_early_invalid_response_preserves_safe_usage(payload):
    with pytest.raises(GatewayError, match="^invalid_response$") as error:
        SourcingGateway(Fake(payload)).research(ResearchRequest(**REQUEST))
    usage = error.value.sourcing_usage
    assert (
        usage.input_tokens == 21
        and usage.output_tokens == 8
        and usage.search_queries == 2
    )


def test_invalid_usage_types_are_unknown_even_on_incomplete_response():
    payload = {
        "status": "incomplete",
        "output": None,
        "usage": {"input_tokens": True, "output_tokens": -8, "web_search_queries": "2"},
    }
    with pytest.raises(GatewayError) as error:
        SourcingGateway(Fake(payload)).research(ResearchRequest(**REQUEST))
    usage = error.value.sourcing_usage
    assert (
        usage.input_tokens is None
        and usage.output_tokens is None
        and usage.search_queries is None
    )


def test_background_acknowledgement_and_poll_do_not_regenerate():
    from forma_api.sourcing_gateway import PendingResearch

    class Background:
        posts = 0
        gets = 0

        def post(self, path, payload, timeout):
            self.posts += 1
            assert payload["background"] is True and payload["store"] is True
            return {"id": "resp_known", "status": "queued"}

        def get(self, response_id, timeout):
            self.gets += 1
            assert response_id == "resp_known"
            return response([offer()])

    transport = Background()
    gateway = SourcingGateway(transport)
    with pytest.raises(PendingResearch) as pending:
        gateway.research(ResearchRequest(**REQUEST))
    assert pending.value.response_id == "resp_known"
    offers, usage = gateway.poll("resp_known", ResearchRequest(**REQUEST))
    assert len(offers) == 1 and transport.posts == 1 and transport.gets == 1


@pytest.mark.parametrize(
    "response_id", [None, "https://evil.example/id", "../secret", "resp_bad?x=1"]
)
def test_background_missing_or_unsafe_identity_stays_unknown(response_id):
    with pytest.raises(GatewayError, match="invalid_response"):
        SourcingGateway(Fake({"id": response_id, "status": "queued"})).research(
            ResearchRequest(**REQUEST)
        )


def test_live_shape_commentary_empty_snippets_and_cited_final_fenced_json():
    raw = offer()
    raw["price"] = "188.10"
    value = response([raw])
    value["output"][0]["results"] = [
        {"url": raw["url"], "title": "Tijera", "snippet": ""}
    ]
    sentence = "Tijera: Bs. 188,10; availability unconfirmed."
    block = value["output"][1]["content"][0]
    block["text"] = sentence + "\n```json\n" + json.dumps({"offers": [raw]}) + "\n```"
    block["annotations"] = [
        {
            "type": "url_citation",
            "url": raw["url"],
            "start_index": 0,
            "end_index": len(sentence),
        }
    ]
    value["output"].insert(
        0,
        {
            "type": "message",
            "phase": "commentary",
            "content": [
                {
                    "type": "output_text",
                    "text": "I will search first.",
                    "annotations": [],
                }
            ],
        },
    )
    offers, _ = SourcingGateway(Fake(value)).research(ResearchRequest(**REQUEST))
    assert offers[0].price == "188.10"


def test_empty_snippets_and_uncited_model_price_stay_unknown():
    raw = offer()
    value = response([raw])
    value["output"][0]["results"] = [
        {"url": raw["url"], "title": "Tape", "snippet": ""}
    ]
    value["output"][1]["content"][0]["annotations"] = []
    offers, _ = SourcingGateway(Fake(value)).research(ResearchRequest(**REQUEST))
    assert offers[0].price is None and offers[0].price_status == "price_unknown"


def test_homepage_replacing_exact_result_product_url_is_rejected():
    raw = offer()
    raw["url"] = "https://shop.example"
    value = response([raw])
    value["output"][0]["results"] = [
        {"url": "https://shop.example/product", "snippet": "20 BOB"}
    ]
    value["output"][1]["content"][0]["annotations"] = []
    offers, _ = SourcingGateway(Fake(value)).research(ResearchRequest(**REQUEST))
    assert offers == ()
