import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from forma_api import diagnosis_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_domain.models import (
    BuildPlan,
    Constraints,
    DiagnosisProposal,
    Effects,
    Feature,
    Fold,
    FoldArgs,
    Joint,
    JointProfile,
    Measurement,
    Part,
    Preconditions,
    Rect,
    Region,
    Stock,
)

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


def _real_plan():
    def mm(value):
        return Measurement(value=value, unit="mm", source="user_ruler", confirmed=True)

    def unknown(unit):
        return Measurement(value=None, unit=unit, source="unknown", confirmed=False)

    stock = Stock(
        id="stock-1",
        kind="sheet",
        material="cardboard",
        width_mm=mm(300),
        height_mm=mm(200),
        thickness_mm=mm(2),
        remaining_length_mm=mm(300),
        condition="usable",
        usable_regions=(
            Region(id="region-1", geometry=Rect(x=0, y=0, width=300, height=200)),
        ),
    )
    fold_feature = Feature(
        id="feature-fold-1",
        kind="fold",
        geometry=Rect(x=10, y=20, width=80, height=2),
    )
    slot_feature = Feature(
        id="feature-slot-1",
        kind="slot",
        geometry=Rect(x=30, y=40, width=12, height=3),
    )
    tab_feature = Feature(
        id="feature-tab-1",
        kind="tab",
        geometry=Rect(x=5, y=6, width=11, height=7),
    )
    part = Part(
        id="part-1",
        source_stock_id="stock-1",
        source_region_id="region-1",
        geometry=Rect(x=0, y=0, width=100, height=80),
        features=(fold_feature, slot_feature),
        condition="usable",
    )
    other = Part(
        id="part-2",
        source_stock_id="stock-1",
        source_region_id="region-1",
        geometry=Rect(x=100, y=0, width=90, height=80),
        features=(tab_feature,),
        condition="usable",
    )
    operation = Fold(
        id="op-fold-1",
        type="fold",
        part_ids=("part-1",),
        stock_ids=(),
        depends_on=(),
        expected_state_id="state-after-fold",
        requires_user_confirmation=True,
        preconditions=Preconditions(
            accessible_part_ids=("part-1",),
            required_joint_ids=("joint-1",),
            human_checks=("Check the fold line is reachable",),
        ),
        effects=Effects(changed_part_ids=("part-1",), attached_joint_ids=("joint-1",)),
        args=FoldArgs(
            part_id="part-1",
            feature_id="feature-fold-1",
            start_x_mm=10,
            start_y_mm=20,
            end_x_mm=90,
            end_y_mm=20,
            angle_deg=67.5,
            direction="valley",
            reachable_face="front",
        ),
    )
    return BuildPlan(
        project_id="project-a",
        version_id="version-1",
        status="active",
        stocks=(stock,),
        parts=(part, other),
        joint_profiles=(
            JointProfile(
                id="profile-1",
                strategy="tab_slot",
                status="experimental",
                material="cardboard",
            ),
        ),
        joints=(
            Joint(
                id="joint-1",
                profile_id="profile-1",
                part_ids=("part-1", "part-2"),
                interface_feature_ids=("feature-slot-1", "feature-tab-1"),
            ),
        ),
        operations=(operation,),
        checkpoints=(),
        constraints=Constraints(
            device_mass_g=unknown("g"),
            support_angle_deg=unknown("deg"),
            max_footprint_width_mm=unknown("mm"),
            max_footprint_height_mm=unknown("mm"),
        ),
        compiler_version="test-compiler",
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


def test_context_includes_stored_operation_facts_and_geometry():
    plan = _real_plan()
    context = diagnosis_runtime.build_context(
        project_id="project-a",
        revision_id="inventory-1",
        project_goal="A stand",
        reported_problem="The fold looks wrong",
        stocks=plan.stocks,
        plan=plan,
        current_operation_id="op-fold-1",
    )
    assert context["completion_history_supplied"] is False
    active = context["active_plan"]
    current = active["current_operation"]
    # Stored expected (intended) operation facts, not completion history.
    assert current["args"]["angle_deg"] == 67.5
    assert current["args"]["direction"] == "valley"
    assert current["args"]["feature_id"] == "feature-fold-1"
    assert current["preconditions"]["accessible_part_ids"] == ["part-1"]
    assert current["preconditions"]["required_joint_ids"] == ["joint-1"]
    assert current["effects"]["changed_part_ids"] == ["part-1"]
    assert current["effects"]["attached_joint_ids"] == ["joint-1"]
    assert current["expected_state_id"] == "state-after-fold"
    assert "completed" not in current
    # Referenced part / feature geometry Muse can compare with the photo.
    part = next(item for item in active["parts"] if item["id"] == "part-1")
    assert part["geometry"] == {
        "x": 0.0,
        "y": 0.0,
        "width": 100.0,
        "height": 80.0,
        "rotation_deg": 0,
    }
    features = {item["id"]: item for item in part["features"]}
    assert features["feature-fold-1"]["kind"] == "fold"
    assert features["feature-fold-1"]["geometry"]["width"] == 80.0
    assert features["feature-slot-1"]["geometry"] == {
        "x": 30.0,
        "y": 40.0,
        "width": 12.0,
        "height": 3.0,
        "rotation_deg": 0,
    }
    joint = active["joints"][0]
    interface = {item["id"]: item for item in joint["interface_features"]}
    assert interface["feature-slot-1"]["part_id"] == "part-1"
    assert interface["feature-slot-1"]["geometry"]["width"] == 12.0
    assert interface["feature-tab-1"]["geometry"]["width"] == 11.0
    # Scoped IDs unchanged and no unrelated blobs are introduced.
    assert "op-fold-1" in active["allowed_affected_ids"]
    assert "evidence" not in active
    assert "physical_events" not in active


def test_request_requires_paired_operation_context():
    with pytest.raises(Exception):
        diagnosis_runtime.DiagnosisRequest(
            media_id="media-a",
            expected_revision_id="inventory-1",
            reported_problem="It tore",
            expected_active_version_id="version-1",
        )
