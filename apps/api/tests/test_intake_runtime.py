import json

import pytest

from forma_api import intake_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.proposal_prompts import LANGUAGE_RULE
from forma_api.proposal_service import IntakeObservation
from forma_api.provider_diagnostics import ProviderUsage, summarize_usage
from forma_domain.material_catalog import IntakeProposal

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


CARDBOARD = {
    "identity": {"outcome": "catalog", "category_id": "corrugated_cardboard"},
    "visible_evidence": "brown fluted sheet",
    "box": {"x1": 0.2, "y1": 0.2, "x2": 0.8, "y2": 0.7},
    "visibility": "full",
}
INTAKE_JSON = json.dumps(
    {"recognition": "items", "items": [CARDBOARD], "questions": []}
)


def test_observe_photo_uses_strict_intake_schema_without_tool():
    fake = Fake(
        final(
            json.dumps(
                {
                    "recognition": "items",
                    "items": [CARDBOARD],
                    "questions": ["Measure its thickness"],
                }
            )
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
    assert observation.recognition == "items"
    # Labels are derived from the structured items, never free text alone.
    assert observation.labels == ("Corrugated cardboard",)
    assert observation.items[0].identity.category_id == "corrugated_cardboard"
    assert diagnostics.status == "ok"
    assert diagnostics.model == "muse-spark-1.3"
    assert diagnostics.elapsed_ms >= 0
    path, payload, _ = fake.calls[0]
    assert path == "/chat/completions"
    assert "tools" not in payload
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema == IntakeProposal.model_json_schema()
    assert schema["required"] == ["recognition", "items", "questions"]
    assert payload["max_completion_tokens"] == 4096
    user = payload["messages"][1]["content"]
    serialized = user[0]["text"]
    assert "SECRET GOAL" in serialized
    assert '"untrusted_context"' in serialized
    assert "required read-only tool" not in payload["messages"][0]["content"]
    system_prompt = payload["messages"][0]["content"]
    assert system_prompt.count(LANGUAGE_RULE) == 1
    assert "intake-items-v2" in system_prompt
    # The old instruction contradicted the item request.
    assert "labels and questions only" not in system_prompt
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


# The shapes the live runs of November 4, 2026 returned for the cardboard and
# notched-sheet photos (labels with no items), plus other non-answers.
@pytest.mark.parametrize(
    "answer",
    [
        {
            "labels": ["torn corrugated cardboard stack"],
            "measurement_source": "unknown",
            "questions": ["How many individual torn pieces make up the stack?"],
            "items": [],
        },
        {
            "labels": ["brown flat sheet candidate object"],
            "measurement_source": "unknown",
            "questions": [],
        },
        {"recognition": "items", "items": [], "questions": []},
        {"recognition": "no_objects", "items": [CARDBOARD], "questions": []},
        {"items": [CARDBOARD], "questions": []},
        {"recognition": "items", "items": [CARDBOARD]},
    ],
)
def test_label_only_or_inconsistent_answers_are_not_recognition(answer):
    fake = Fake(final(json.dumps(answer)))
    with pytest.raises(GatewayError) as error:
        intake_runtime.observe_photo(
            MetaGateway(fake),
            project_goal="stand",
            image_data=PNG,
            content_type="image/png",
        )
    assert error.value.code == "invalid_proposal"
    assert intake_runtime.gateway_error_details(error.value.code)[:2] == (
        502,
        "invalid_response",
    )
    assert len(fake.calls) == 1


def test_no_objects_is_an_explicit_answer_not_a_failure():
    content = json.dumps(
        {
            "recognition": "no_objects",
            "items": [],
            "questions": ["Is the material outside the frame?"],
        }
    )
    fake = Fake(final(content))
    observation, diagnostics = intake_runtime.observe_photo(
        MetaGateway(fake),
        project_goal="stand",
        image_data=PNG,
        content_type="image/png",
    )
    assert observation.recognition == "no_objects"
    assert observation.items == () and observation.labels == ()
    assert observation.questions == ("Is the material outside the frame?",)
    assert diagnostics.status == "ok"
    assert len(fake.calls) == 1


def test_partial_uncertain_and_group_items_are_kept_as_proposed():
    content = json.dumps(
        {
            "recognition": "partial",
            "items": [
                {
                    "identity": {
                        "outcome": "uncertain",
                        "alternatives": ["plastic_bottle", "food_container"],
                    },
                    "visible_evidence": "clear curved object",
                    "box": None,
                },
                {
                    "identity": {"outcome": "catalog", "category_id": "bottle_caps"},
                    "visible_evidence": "pile of caps",
                    "instance": "group_count_unknown",
                },
            ],
            "questions": [],
        }
    )
    observation, _ = intake_runtime.observe_photo(
        MetaGateway(Fake(final(content))),
        project_goal="stand",
        image_data=PNG,
        content_type="image/png",
    )
    assert observation.recognition == "partial"
    first, second = observation.items
    assert first.identity.outcome == "uncertain" and first.box is None
    assert second.instance == "group_count_unknown"
    assert observation.labels == ("Unidentified object", "Bottle caps")


def test_truncated_answer_keeps_finish_reason_and_usage_without_retry():
    # Run 3 (plastic bottle): 3632 input and 2048 output tokens, cut off.
    response = {
        "choices": [
            {"finish_reason": "length", "message": {"content": '{"recognition":"it'}}
        ],
        "usage": {
            "prompt_tokens": 3632,
            "completion_tokens": 2048,
            "completion_tokens_details": {"reasoning_tokens": 1990},
        },
    }
    fake = Fake(response)
    with pytest.raises(GatewayError) as error:
        intake_runtime.observe_photo(
            MetaGateway(fake),
            project_goal="stand",
            image_data=PNG,
            content_type="image/png",
        )
    assert error.value.code == "incomplete_output"
    diagnostics = error.value.diagnostics
    assert diagnostics.finish_reason == "length"
    assert diagnostics.usage.input_tokens == 3632
    assert diagnostics.usage.output_tokens == 2048
    assert diagnostics.usage.reasoning_tokens == 1990
    assert len(fake.calls) == 1
    assert intake_runtime.gateway_error_details("incomplete_output")[:2] == (
        502,
        "incomplete_output",
    )


def test_the_largest_valid_answer_leaves_most_of_the_budget_for_reasoning():
    item = {
        "identity": {
            "outcome": "other",
            "other_label": "x" * 80,
            "alternatives": ["plastic_bottle", "food_container", "bottle_caps"],
        },
        "visible_evidence": "y" * 80,
        "box": {"x1": 0.123456, "y1": 0.123456, "x2": 0.654321, "y2": 0.654321},
        "visibility": "partial",
        "instance": "group_count_unknown",
    }
    biggest = IntakeProposal.model_validate(
        {
            "recognition": "partial",
            "items": [item] * 12,
            "questions": ["q" * 160] * 3,
        }
    )
    with pytest.raises(Exception):
        IntakeProposal.model_validate(
            {"recognition": "partial", "items": [item] * 13, "questions": []}
        )
    # Conservatively one token per three characters.
    tokens = len(biggest.model_dump_json()) / 3
    assert tokens < intake_runtime.INTAKE_MAX_COMPLETION_TOKENS / 2


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
        ("incomplete_output", 502, "incomplete_output"),
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


def test_default_intake_gateway_allows_one_long_call_without_retries(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "server-test-key")
    monkeypatch.setenv("META_SPARK_MODEL", "muse-spark-1.3")
    gateway = intake_runtime.default_gateway_factory()
    fake = Fake(final(INTAKE_JSON))
    gateway.transport = fake
    intake_runtime.observe_photo(
        gateway, project_goal="stand", image_data=PNG, content_type="image/png"
    )
    assert 119 < fake.calls[0][2] <= 120
    assert gateway.budget == 120
    assert gateway.max_rounds == 1
    assert gateway.max_retries == 0
    failing = Fake(GatewayError("rate_limit", retryable=True))
    gateway.transport = failing
    with pytest.raises(GatewayError, match="rate_limit"):
        intake_runtime.observe_photo(
            gateway, project_goal="stand", image_data=PNG, content_type="image/png"
        )
    assert len(failing.calls) == 1
