import json
from types import SimpleNamespace

import pytest

from forma_api import diagnosis_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_domain.models import DiagnosisProposal

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


def proposal_json(**overrides):
    value = {
        "visible_observations": ["A tear is visible near the slot"],
        "hypotheses": ["The slot may be too close to the edge"],
        "questions_or_measurements": ["Measure the distance to the edge"],
        "affected_ids": [],
        "failure_type": "unknown",
    }
    value.update(overrides)
    return json.dumps(value)


def photo_only_context():
    return diagnosis_runtime.build_context(
        project_id="project-a",
        revision_id="inventory-1",
        project_goal="SECRET GOAL",
        reported_problem="The slot tore",
        stocks=(),
        plan=None,
    )


def test_photo_only_payload_schema_context_and_image_consent():
    fake = Fake(final(proposal_json()))
    proposal, diagnostics = diagnosis_runtime.diagnose_photo(
        MetaGateway(fake),
        image_data=PNG,
        content_type="image/png",
        context=photo_only_context(),
        plan=None,
    )
    assert isinstance(proposal, DiagnosisProposal)
    assert proposal.failure_type == "unknown"
    assert diagnostics.status == "ok"
    assert diagnostics.model == "muse-spark-1.3"
    path, payload, _ = fake.calls[0]
    assert path == "/chat/completions"
    assert "tools" not in payload
    assert (
        payload["response_format"]["json_schema"]["schema"]
        == DiagnosisProposal.model_json_schema()
    )
    system = payload["messages"][0]["content"]
    assert "visible_observations" in system
    user = payload["messages"][1]["content"]
    serialized = user[0]["text"]
    assert '"active_plan": null' in serialized
    assert '"reported_problem": "The slot tore"' in serialized
    assert '"reported_problem_is_observed_fact": false' in serialized
    assert '"completion_history_supplied": false' in serialized
    assert user[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_photo_only_invented_affected_ids_rejected():
    fake = Fake(final(proposal_json(affected_ids=["part-invented"])))
    with pytest.raises(GatewayError, match="invalid_diagnosis_reference"):
        diagnosis_runtime.diagnose_photo(
            MetaGateway(fake),
            image_data=JPEG,
            content_type="image/jpeg",
            context=photo_only_context(),
            plan=None,
        )


def _plan():
    operation = SimpleNamespace(id="op-1")
    part = SimpleNamespace(id="part-1", features=(SimpleNamespace(id="feature-1"),))
    return SimpleNamespace(
        version_id="version-1",
        stocks=(SimpleNamespace(id="stock-1"),),
        parts=(part,),
        joints=(SimpleNamespace(id="joint-1"),),
        operations=(operation,),
        checkpoints=(SimpleNamespace(id="check-1"),),
    )


def test_contextual_affected_ids_validated_against_server_plan():
    plan = _plan()
    allowed = diagnosis_runtime.allowed_affected_ids(plan)
    assert {
        "version-1",
        "stock-1",
        "part-1",
        "feature-1",
        "joint-1",
        "op-1",
        "check-1",
    } <= allowed
    valid = DiagnosisProposal.model_validate_json(
        proposal_json(affected_ids=["op-1"], failure_type="torn_slot")
    )
    assert diagnosis_runtime.validate_diagnosis(valid, plan=plan) is valid
    invented = DiagnosisProposal.model_validate_json(
        proposal_json(affected_ids=["op-other"])
    )
    with pytest.raises(GatewayError, match="invalid_diagnosis_reference"):
        diagnosis_runtime.validate_diagnosis(invented, plan=plan)
    duplicate = DiagnosisProposal.model_validate_json(
        proposal_json(affected_ids=["op-1", "op-1"])
    )
    with pytest.raises(GatewayError, match="invalid_diagnosis_reference"):
        diagnosis_runtime.validate_diagnosis(duplicate, plan=plan)


@pytest.mark.parametrize(
    "data,mime",
    [(PNG, "image/webp"), (b"x" * 5_000_001, "image/png"), (b"", "image/png")],
)
def test_invalid_image_rejected_before_transport(data, mime):
    fake = Fake(final(proposal_json()))
    with pytest.raises(GatewayError, match="invalid_image"):
        diagnosis_runtime.diagnose_photo(
            MetaGateway(fake),
            image_data=data,
            content_type=mime,
            context=photo_only_context(),
            plan=None,
        )
    assert fake.calls == []


def test_request_requires_paired_operation_context():
    with pytest.raises(Exception):
        diagnosis_runtime.DiagnosisRequest(
            media_id="media-a",
            expected_revision_id="inventory-1",
            reported_problem="It tore",
            expected_active_version_id="version-1",
        )
