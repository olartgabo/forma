import json

import pytest

from forma_api import intake_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.proposal_service import IntakeObservation

PNG = b"\x89PNG\r\n\x1a\nsynthetic"
JPEG = b"\xff\xd8\xffsynthetic"


class Fake:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, path, payload, timeout):
        self.calls.append((path, json.loads(json.dumps(payload)), timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def final(content):
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}


def test_observe_photo_uses_strict_intake_schema_without_tool():
    fake = Fake(
        final(
            '{"labels":["cardboard sheet"],"measurement_source":"unknown",'
            '"questions":["Measure its thickness"]}'
        )
    )
    observation, diagnostics = intake_runtime.observe_photo(
        MetaGateway(fake),
        project_goal="SECRET GOAL",
        image_data=PNG,
        content_type="image/png",
    )
    assert isinstance(observation, IntakeObservation)
    assert observation.measurement_source == "unknown"
    assert diagnostics.status == "ok"
    assert diagnostics.model == "muse-spark-1.3"
    assert diagnostics.elapsed_ms >= 0
    path, payload, _ = fake.calls[0]
    assert path == "/chat/completions"
    assert "tools" not in payload
    assert (
        payload["response_format"]["json_schema"]["schema"]
        == IntakeObservation.model_json_schema()
    )
    user = payload["messages"][1]["content"]
    serialized = user[0]["text"]
    assert "SECRET GOAL" in serialized
    assert '"untrusted_context"' in serialized
    assert "required read-only tool" not in payload["messages"][0]["content"]
    assert user[1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize(
    "code,status,stable",
    [
        ("missing_key", 503, "provider_not_configured"),
        ("authentication", 502, "provider_authentication"),
        ("access_denied", 502, "access_denied"),
        ("rate_limit", 429, "rate_limit"),
        ("timeout", 504, "timeout"),
        ("budget_exhausted", 504, "timeout"),
        ("network_error", 502, "network_error"),
        ("invalid_response", 502, "invalid_response"),
        ("invalid_proposal", 502, "invalid_response"),
        ("provider_http_error", 502, "provider_http_error"),
        ("something_private", 502, "provider_error"),
    ],
)
def test_gateway_error_mapping_is_safe_and_stable(code, status, stable):
    result = intake_runtime.gateway_error_details(code)
    assert result[0] == status
    assert result[1] == stable
    assert code not in result[2] or code == stable


def test_missing_key_from_default_factory(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(GatewayError, match="missing_key"):
        intake_runtime.default_gateway_factory()


@pytest.mark.parametrize(
    "data,mime", [(PNG, "image/webp"), (b"x" * 5_000_001, "image/png"), (b"", "image/png")]
)
def test_invalid_image_rejected_before_transport(data, mime):
    fake = Fake(final("{}"))
    with pytest.raises(GatewayError, match="invalid_image"):
        intake_runtime.observe_photo(
            MetaGateway(fake), project_goal="stand", image_data=data, content_type=mime
        )
    assert fake.calls == []


@pytest.mark.parametrize("content", ["SECRET not json", '{"labels":[],"measurement_source":"unknown","questions":[],"extra":1}'])
def test_malformed_output_becomes_invalid_proposal_without_leak(content):
    fake = Fake(final(content))
    with pytest.raises(GatewayError) as error:
        intake_runtime.observe_photo(
            MetaGateway(fake), project_goal="stand", image_data=JPEG, content_type="image/jpeg"
        )
    assert error.value.code == "invalid_proposal"
    assert "SECRET" not in str(error.value)
    assert intake_runtime.gateway_error_details(error.value.code)[:2] == (
        502,
        "invalid_response",
    )
