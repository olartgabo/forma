"""Real compiler/fabrication checks for synthetic construction proposals only."""

import pytest
from forma_stability.construction import bind_operations, generate_construction
from forma_stability.construction_fabrication import build_fabrication
from forma_stability.generic_examples import assembly_example

from forma_domain.construction_plan import ConstructionRequest


def proposal(name="box"):
    return generate_construction(ConstructionRequest(target=assembly_example(name)))


@pytest.mark.parametrize("name", ("box", "ramp"))
def test_actual_fabrication_engine_orders_every_bound_rectangular_operation(name):
    construction = proposal(name)
    plan, report, bindings, blockers = build_fabrication(
        construction, allow_synthetic=True
    )
    assert not blockers
    assert report.status == "ready"
    assert not report.blockers
    assert report.snapshot.inputs_sha256
    assert len([op for op in plan.operations if op.type == "cut_rect"]) == 1
    assert len([op for op in plan.operations if op.type == "tape_joint"]) == len(
        construction.request.target.assembly.joints
    )
    assert sum(
        op.args.length_mm for op in plan.operations if op.type == "tape_joint"
    ) == 80 * len(plan.joints)
    bound = bind_operations(construction, bindings)
    flattened = [oid for step in bound.steps for oid in step.operation_ids]
    assert len(flattened) == len(set(flattened))
    assert set(flattened) == {op.id for op in plan.operations}
    assert all(op.requires_user_confirmation for op in plan.operations)
    assert report.snapshot.last_event_id is None
    assert report.attached_joint_ids == ()
    assert all(op.status != "completed" for op in report.operations)
    assert report.order_status == "complete"
    assert {step.operation_id for step in report.supported_order} == set(flattened)
    assert all(p.source_stock_id == plan.stocks[0].id for p in plan.parts)


def test_fixed_resources_do_not_expand_to_fit_target_and_tape_exhaustion_blocks():
    construction = proposal()
    plan, report, _, _ = build_fabrication(
        construction, allow_synthetic=True, sheet_width_mm=100, sheet_height_mm=100
    )
    assert plan.stocks[0].width_mm.value == 100
    assert report.status == "blocked"
    assert report.blockers
    plan, report, _, _ = build_fabrication(
        construction, allow_synthetic=True, tape_length_mm=1
    )
    assert plan.stocks[1].remaining_length_mm.value == 1
    assert report.status == "blocked"
    assert any(b.code == "stock_exhausted" for b in report.blockers)


@pytest.mark.parametrize("name", ("triangle", "concave"))
def test_nonrectangular_target_has_no_fabricated_cut_plan(name):
    plan, report, bindings, blockers = build_fabrication(
        proposal(name), allow_synthetic=True
    )
    assert plan is report is None
    assert not bindings
    assert "rectangular" in blockers[0]


def test_resource_opt_in_and_replay_identity_are_explicit():
    construction = proposal()
    assert build_fabrication(construction)[0] is None
    first = build_fabrication(construction, allow_synthetic=True)
    assert first == build_fabrication(construction, allow_synthetic=True)
    other = build_fabrication(construction, allow_synthetic=True, tape_length_mm=4000)
    assert first[0].version_id != other[0].version_id
    assert first[1].snapshot.inputs_sha256 != other[1].snapshot.inputs_sha256
    assert "synthetic" in first[0].compiler_version
    assert all(
        "SYNTHETIC" in note for note in first[0].joint_profiles[0].limitations[:1]
    )
