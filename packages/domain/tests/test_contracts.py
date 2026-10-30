import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from forma_domain import models as m
from forma_domain.fixtures import synthetic_inventory_a
from forma_domain.generate import artifacts


def unknown(unit):
    return m.Measurement(value=None, unit=unit, source="unknown", confirmed=False)


def plan_data():
    return dict(
        project_id="project-a",
        version_id="version-a",
        status="draft",
        stocks=synthetic_inventory_a(),
        parts=(),
        joint_profiles=(),
        joints=(),
        operations=(),
        checkpoints=(),
        constraints=m.Constraints(
            device_mass_g=unknown("g"),
            support_angle_deg=unknown("deg"),
            max_footprint_width_mm=unknown("mm"),
            max_footprint_height_mm=unknown("mm"),
        ),
        compiler_version="test",
        created_at=datetime.now(UTC),
    )


def test_roundtrip_frozen_nested_collections():
    plan = m.BuildPlan(**plan_data())
    assert m.BuildPlan.model_validate_json(plan.model_dump_json()) == plan
    assert isinstance(plan.stocks, tuple)
    with pytest.raises(ValidationError):
        plan.stocks[0].condition = "usable"
    assert not plan.stocks[0].width_mm.confirmed
    assert plan.stocks[0].thickness_mm.value is None


@pytest.mark.parametrize(
    "change",
    [
        {"value": None, "confirmed": True},
        {"value": 5, "source": "unknown"},
        {"unit": "cm"},
        {"value": float("nan")},
    ],
)
def test_bad_measurement(change):
    data = dict(value=5, unit="mm", source="user_ruler", confirmed=False)
    with pytest.raises(ValidationError):
        m.Measurement(**(data | change))


def test_field_units_and_duplicate_ids():
    data = synthetic_inventory_a()[0].model_dump()
    data["thickness_mm"] = unknown("g")
    with pytest.raises(ValidationError, match="positive mm"):
        m.Stock(**data)
    data = plan_data()
    data["stocks"] *= 2
    with pytest.raises(ValidationError, match="duplicate"):
        m.BuildPlan(**data)


def test_invalid_nested_reference():
    data = plan_data()
    data["parts"] = (
        m.Part(
            id="part-a",
            source_stock_id="missing",
            source_region_id="synthetic-region-a",
            geometry=m.Rect(x=0, y=0, width=10, height=10),
            condition="usable",
        ),
    )
    with pytest.raises(ValidationError, match="stock reference"):
        m.BuildPlan(**data)


def test_unknown_operation_and_untyped_args_rejected():
    adapter = TypeAdapter(m.Operation)
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        adapter.validate_python({"type": "glue"})
    with pytest.raises(ValidationError):
        adapter.validate_python(
            dict(
                id="op-a",
                type="cut_rect",
                expected_state_id="state-a",
                preconditions={},
                effects={},
                args={"arbitrary": True},
            )
        )


def test_cut_confirmation_and_dependency_order():
    op = dict(
        id="op-a",
        type="cut_rect",
        expected_state_id="state-a",
        preconditions={},
        effects={},
        args=dict(
            stock_id="synthetic-stock-a",
            source_region_id="synthetic-region-a",
            child_part_ids=["part-a"],
            kerf_mm=1,
            edge_margin_mm=2,
        ),
    )
    with pytest.raises(ValidationError):
        TypeAdapter(m.Operation).validate_python(
            op | {"requires_user_confirmation": False}
        )
    data = plan_data()
    data["parts"] = (
        m.Part(
            id="part-a",
            source_stock_id="synthetic-stock-a",
            source_region_id="synthetic-region-a",
            geometry=m.Rect(x=0, y=0, width=10, height=10),
            condition="usable",
        ),
    )
    data["operations"] = [op | {"depends_on": ["op-a"]}]
    with pytest.raises(ValidationError, match="preceding operation"):
        m.BuildPlan(**data)
    data["operations"] = [op]
    assert m.BuildPlan(**data).operations[0].reversible == "irreversible"


def test_profile_cannot_claim_tested_without_evidence():
    with pytest.raises(ValidationError, match="measured limits"):
        m.JointProfile(
            id="profile-a", strategy="tab_slot", status="tested", material="cardboard"
        )


def test_model_cannot_report_physical_success():
    with pytest.raises(ValidationError, match="user report"):
        m.PhysicalEvent(
            id="event-a",
            project_id="project-a",
            version_id="version-a",
            kind="test",
            actor="system",
            observation="passed",
            verification_state="user_confirmed",
            test_result="passed",
            recorded_at=datetime.now(UTC),
        )


def test_mutation_scope_and_approval():
    event = m.PhysicalEvent(
        id="event-a",
        project_id="other-project",
        version_id="version-a",
        kind="observation",
        actor="user",
        observation="torn",
        verification_state="unknown",
        recorded_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError, match="differs"):
        m.AppendPhysicalEvent(
            project_id="project-a",
            expected_version_id="version-a",
            idempotency_key="request-123",
            event=event,
        )
    with pytest.raises(ValidationError):
        m.CommitRevision(
            project_id="project-a",
            expected_version_id="version-a",
            idempotency_key="request-123",
            proposal_id="proposal-a",
            user_approved=False,
        )


def test_proposals_bounded_flat_and_no_claim_fields():
    with pytest.raises(ValidationError):
        m.DesignProposals(candidates=[], questions=["question"] * 9)
    with pytest.raises(ValidationError):
        m.RepairPatch(
            id="patch-a",
            base_version_id="version-a",
            kind="change_angle",
            target_id="part-a",
            replacement_stock_id=None,
            replacement_profile_id=None,
            width_mm=None,
            height_mm=None,
            angle_deg=None,
            rationale="test",
        )
    with pytest.raises(ValidationError):
        m.DesignProposals(candidates=[], questions=[], completed_operations=[])


def test_all_twelve_operation_variants_exported_and_generation_stable():
    schema = TypeAdapter(m.Operation).json_schema()
    assert len(schema["discriminator"]["mapping"]) == 12
    assert artifacts() == artifacts()
    assert '"paths": {}' in artifacts()["packages/domain/generated/openapi.json"]


def test_checked_in_artifacts_match_generator():
    root = Path(__file__).resolve().parents[3]
    for relative, content in artifacts().items():
        assert (root / relative).read_text(encoding="utf-8") == content
    subprocess.run(
        [sys.executable, "-m", "forma_domain.generate", "--check"], cwd=root, check=True
    )


@pytest.mark.parametrize(
    "result,state",
    [("passed", "failed"), ("failed", "user_confirmed"), ("not_attempted", "unknown")],
)
def test_contradictory_test_claim_rejected(result, state):
    with pytest.raises(ValidationError, match="disagree"):
        m.PhysicalEvent(
            id="event-a",
            project_id="project-a",
            version_id="version-a",
            kind="test",
            actor="user",
            observation="test report",
            verification_state=state,
            test_result=result,
            recorded_at=datetime.now(UTC),
        )


def test_all_irreversible_variants_require_confirmation():
    operation = dict(
        id="tape-op",
        type="tape_joint",
        part_ids=(),
        stock_ids=(),
        depends_on=(),
        expected_state_id="state",
        preconditions={},
        effects={},
        args=dict(joint_id="joint", stock_id="tape", length_mm=10),
        reversible="irreversible",
        requires_user_confirmation=False,
    )
    with pytest.raises(ValidationError):
        TypeAdapter(m.Operation).validate_python(operation)
