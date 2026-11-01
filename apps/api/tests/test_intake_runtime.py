import json

import pytest

from forma_api import intake_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.proposal_service import IntakeObservation
from forma_api.provider_diagnostics import ProviderUsage, summarize_usage

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


def final_usage(content, usage=None):
    response = final(content)
    if usage is not None:
        response["usage"] = usage
    return response


INTAKE_JSON = (
    '{"labels":["cardboard sheet"],"measurement_source":"unknown","questions":[]}'
)


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


def test_observe_photo_reports_provider_usage_and_zero_is_valid():
    fake = Fake(final_usage(INTAKE_JSON, {"prompt_tokens": 12, "completion_tokens": 0}))
    _, diagnostics = intake_runtime.observe_photo(
        MetaGateway(fake),
        project_goal="stand",
        image_data=PNG,
        content_type="image/png",
    )
    assert diagnostics.usage is not None
    assert diagnostics.usage.model_calls == 1
    assert diagnostics.usage.input_tokens == 12
    assert diagnostics.usage.output_tokens == 0


def test_observe_photo_reused_gateway_excludes_prior_calls():
    gateway = MetaGateway(
        Fake(
            final_usage(INTAKE_JSON, {"prompt_tokens": 100, "completion_tokens": 50}),
            final_usage(INTAKE_JSON, {"prompt_tokens": 7, "completion_tokens": 3}),
        )
    )
    intake_runtime.observe_photo(
        gateway, project_goal="stand", image_data=PNG, content_type="image/png"
    )
    _, diagnostics = intake_runtime.observe_photo(
        gateway, project_goal="stand", image_data=PNG, content_type="image/png"
    )
    assert diagnostics.usage.model_calls == 1
    assert diagnostics.usage.input_tokens == 7
    assert diagnostics.usage.output_tokens == 3


def test_observe_photo_missing_usage_stays_unknown():
    fake = Fake(final(INTAKE_JSON))
    _, diagnostics = intake_runtime.observe_photo(
        MetaGateway(fake),
        project_goal="stand",
        image_data=PNG,
        content_type="image/png",
    )
    assert diagnostics.usage.model_calls == 1
    assert diagnostics.usage.input_tokens is None
    assert diagnostics.usage.output_tokens is None


@pytest.mark.parametrize("bad", [True, -1, 1.5, "12", 10**9 + 1])
def test_observe_photo_malformed_input_tokens_unknown_not_partial(bad):
    fake = Fake(
        final_usage(INTAKE_JSON, {"prompt_tokens": bad, "completion_tokens": 4})
    )
    _, diagnostics = intake_runtime.observe_photo(
        MetaGateway(fake),
        project_goal="stand",
        image_data=PNG,
        content_type="image/png",
    )
    assert diagnostics.usage.model_calls == 1
    assert diagnostics.usage.input_tokens is None
    assert diagnostics.usage.output_tokens == 4


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


def test_usage_record_optional_for_backwards_compatibility_and_strict():
    legacy = intake_runtime.IntakeDiagnostics.model_validate(
        {"status": "ok", "model": "muse-spark-1.3", "elapsed_ms": 1}
    )
    assert legacy.usage is None
    with pytest.raises(Exception):
        ProviderUsage(model_calls=1, input_tokens=True)
    with pytest.raises(Exception):
        ProviderUsage(model_calls=1, input_tokens=-1)
    with pytest.raises(Exception):
        ProviderUsage(model_calls=1, output_tokens=10**18)
    # No traces: call count is known to be zero, tokens remain unknown.
    empty = summarize_usage([])
    assert empty.model_calls == 0
    assert empty.input_tokens is None and empty.output_tokens is None
    dumped = ProviderUsage(model_calls=1, input_tokens=0, output_tokens=0).model_dump()
    assert dumped == {"model_calls": 1, "input_tokens": 0, "output_tokens": 0}
    assert not any("cost" in key or "price" in key for key in dumped)


def test_missing_key_from_default_factory(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(GatewayError, match="missing_key"):
        intake_runtime.default_gateway_factory()


@pytest.mark.parametrize(
    "data,mime",
    [(PNG, "image/webp"), (b"x" * 5_000_001, "image/png"), (b"", "image/png")],
)
def test_invalid_image_rejected_before_transport(data, mime):
    fake = Fake(final("{}"))
    with pytest.raises(GatewayError, match="invalid_image"):
        intake_runtime.observe_photo(
            MetaGateway(fake), project_goal="stand", image_data=data, content_type=mime
        )
    assert fake.calls == []


@pytest.mark.parametrize(
    "content",
    [
        "SECRET not json",
        '{"labels":[],"measurement_source":"unknown","questions":[],"extra":1}',
    ],
)
def test_malformed_output_becomes_invalid_proposal_without_leak(content):
    fake = Fake(final(content))
    with pytest.raises(GatewayError) as error:
        intake_runtime.observe_photo(
            MetaGateway(fake),
            project_goal="stand",
            image_data=JPEG,
            content_type="image/jpeg",
        )
    assert error.value.code == "invalid_proposal"
    assert "SECRET" not in str(error.value)
    assert intake_runtime.gateway_error_details(error.value.code)[:2] == (
        502,
        "invalid_response",
    )
