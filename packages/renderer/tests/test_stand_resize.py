"""Synthetic software fixtures only. No physical build or test was performed."""

import copy
from math import cos, hypot, radians, sin

import pytest
from forma_renderer import render_manual, stand_continuation_blockers
from forma_replanner import simulate_patch
from test_stand_manual import build, measured

from forma_domain import models as m


def _patch(plan, target_id, width_mm, height_mm, patch_id="resize-stand-base"):
    return m.RepairPatch(
        id=patch_id,
        base_version_id=plan.version_id,
        kind="resize_part",
        target_id=target_id,
        replacement_stock_id=None,
        replacement_profile_id=None,
        width_mm=width_mm,
        height_mm=height_mm,
        angle_deg=None,
        rationale="SYNTHETIC stand base extension for a software fixture.",
    )


def _snapshot(plan, patch, *, remaining_stock=None, events=()):
    return m.ReplannerInput(
        base_plan=plan,
        events=events,
        evidence=(),
        material_transactions=(),
        remaining_stock=plan.stocks if remaining_stock is None else remaining_stock,
        patch=patch,
    )


def _simulate(plan, patch, process, **snapshot_kwargs):
    snapshot = _snapshot(plan, patch, **snapshot_kwargs)
    before = copy.deepcopy(snapshot.model_dump())
    result = simulate_patch(
        snapshot,
        process=process,
        allow_synthetic=True,
        family_validator=stand_continuation_blockers,
    )
    assert snapshot.model_dump() == before
    return snapshot, result


def _assert_single_blocker(result, code, message, target_ids=()):
    assert result.status == "blocked", result.blockers
    assert result.plan is None
    assert result.blockers == (
        m.Blocker(code=code, message=message, target_ids=target_ids),
    )


def test_extend_stand_base_depth_regenerates_brace_and_layout():
    plan, parameters, process = build()
    parts = {part.id: part for part in plan.parts}
    patch = _patch(plan, "stand-base", 80, 150)
    snapshot, result = _simulate(plan, patch, process)
    assert result.status == "feasible", result.blockers
    assert result.blockers == ()
    assert stand_continuation_blockers(result.plan) == ()
    assert set(result.changed_part_ids) == {"stand-base", "stand-brace"}

    candidate = {part.id: part for part in result.plan.parts}
    support = candidate["stand-support"]
    base = candidate["stand-base"]
    brace = candidate["stand-brace"]
    original_support = parts["stand-support"]

    support_length = original_support.features[0].geometry.y
    angle = radians(plan.constraints.support_angle_deg.value)
    expected_brace = hypot(
        150 - support_length * cos(angle), support_length * sin(angle)
    )
    assert brace.geometry.height == pytest.approx(expected_brace)

    # Original margin (4 mm) and kerf (2 mm) layout is retained.
    assert support.geometry == original_support.geometry
    assert (base.geometry.x, base.geometry.y) == (4, 156)
    assert (brace.geometry.x, brace.geometry.y) == (4, 308)
    assert (base.geometry.width, base.geometry.height) == (80, 150)
    assert all(part.geometry.rotation_deg == 0 for part in candidate.values())

    # Fold/profile/tape definitions and every operation's arguments are preserved.
    assert support.features == original_support.features
    assert candidate["stand-base"].features == ()
    assert candidate["stand-brace"].features == ()
    assert result.plan.joints == plan.joints
    assert result.plan.joint_profiles == plan.joint_profiles
    assert result.plan.constraints == plan.constraints
    assert [operation.type for operation in result.plan.operations] == [
        operation.type for operation in plan.operations
    ]
    assert [operation.args for operation in result.plan.operations] == [
        operation.args for operation in plan.operations
    ]

    rendered = render_manual(
        result.plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
    )
    assert rendered.status == "accepted", rendered.blockers
    assert rendered.physical_verification == "not_attempted"
    assert len(rendered.panels) == 8
    assert result.lost_part_ids == result.lost_operation_ids == ()
    assert result.required_new_stock_ids == ()
    assert not any(d.kind == "retire_part" for d in result.proposed_material_deltas)
    source = plan.stocks[0].usable_regions[0]
    consumed = [
        d
        for d in result.proposed_material_deltas
        if d.kind == "consume" and d.unit == "mm2"
    ]
    assert len(consumed) == 1
    assert consumed[0].source_region_id == source.id
    assert consumed[0].quantity == source.geometry.width * source.geometry.height
    waste = next(d for d in result.proposed_material_deltas if d.kind == "waste")
    assert waste.quantity == pytest.approx(
        consumed[0].quantity
        - sum(p.geometry.width * p.geometry.height for p in result.plan.parts)
    )


def test_unknown_stand_footprint_stays_unknown_and_blocks():
    plan, _, process = build()
    unknown = m.Measurement(value=None, unit="mm", source="unknown", confirmed=False)
    plan = plan.model_copy(
        update={
            "constraints": plan.constraints.model_copy(
                update={"max_footprint_height_mm": unknown}
            )
        }
    )
    _, result = _simulate(plan, _patch(plan, "stand-base", 80, 150), process)
    _assert_single_blocker(
        result,
        "missing_measurement",
        "Stand base extension requires a confirmed max footprint height.",
        ("stand-base",),
    )
    assert plan.constraints.max_footprint_height_mm.value is None


def test_rotated_stand_parts_are_not_regenerated():
    plan, _, process = build()
    parts = tuple(
        p.model_copy(
            update={"geometry": p.geometry.model_copy(update={"rotation_deg": 90})}
        )
        if p.id == "stand-brace"
        else p
        for p in plan.parts
    )
    plan = plan.model_copy(update={"parts": parts})
    _, result = _simulate(plan, _patch(plan, "stand-base", 80, 150), process)
    _assert_single_blocker(
        result,
        "unsupported",
        "Stand base extension requires all original parts to share one unrotated original source region.",
        ("stand-support", "stand-base", "stand-brace"),
    )


def test_replacement_bearing_stand_is_not_regenerated():
    from test_stand_continuation import _replacement

    original, snapshot, _, replaced = _replacement()
    assert replaced.status == "feasible", replaced.blockers
    _, _, process = build()
    plan = replaced.plan
    request = _snapshot(
        plan,
        _patch(plan, "stand-base", 80, 150),
        remaining_stock=snapshot.remaining_stock,
        events=snapshot.events,
    )
    before = copy.deepcopy(request.model_dump())
    result = simulate_patch(
        request,
        process=process,
        allow_synthetic=True,
        historical_plans=(original,),
        family_validator=stand_continuation_blockers,
    )
    assert request.model_dump() == before
    assert result.status == "blocked"
    assert any(
        b.code == "unsupported" and "original stand-support" in b.message
        for b in result.blockers
    )


def test_completed_stand_cut_cannot_be_resized():
    plan, _parameters, process = build()
    remaining = tuple(
        stock.model_copy(update={"usable_regions": ()})
        if stock.kind == "sheet"
        else stock
        for stock in plan.stocks
    )
    event = m.PhysicalEvent(
        id="synthetic-stand-cut-confirmed",
        project_id=plan.project_id,
        version_id=plan.version_id,
        operation_id="stand-cut-panels",
        kind="operation_confirmed",
        evidence_ids=(),
        recorded_at=plan.created_at,
        actor="user",
        observation=(
            "SYNTHETIC user-confirmed stand cut for a software fixture; "
            "no physical build was performed."
        ),
        verification_state="user_confirmed",
    )
    _snapshot_obj, result = _simulate(
        plan,
        _patch(plan, "stand-base", 80, 150),
        process,
        remaining_stock=remaining,
        events=(event,),
    )
    _assert_single_blocker(
        result,
        "unsupported",
        "Stand base extension requires the original stand-cut-panels cut to be unfinished; completed cuts cannot be resized.",
        ("stand-cut-panels",),
    )


def test_resize_other_stand_part_is_unsupported():
    plan, _parameters, process = build()
    _snapshot_obj, result = _simulate(
        plan, _patch(plan, "stand-support", 80, 160), process
    )
    _assert_single_blocker(
        result,
        "unsupported",
        "Stand resize only supports extending stand-base; other stand parts cannot be resized.",
        ("stand-support",),
    )


def test_stand_base_width_change_is_unsupported():
    plan, _parameters, process = build()
    _snapshot_obj, result = _simulate(
        plan, _patch(plan, "stand-base", 90, 150), process
    )
    _assert_single_blocker(
        result,
        "unsupported",
        "Stand base extension requires the requested width to equal the current stand base width.",
        ("stand-base",),
    )


def test_stand_base_shrink_is_unsupported():
    plan, _parameters, process = build()
    _snapshot_obj, result = _simulate(
        plan, _patch(plan, "stand-base", 80, 130), process
    )
    _assert_single_blocker(
        result,
        "unsupported",
        "Stand base extension only supports increasing the stand base depth.",
        ("stand-base",),
    )


def test_stand_base_depth_above_confirmed_footprint_is_blocked():
    plan, _parameters, process = build()
    _snapshot_obj, result = _simulate(
        plan, _patch(plan, "stand-base", 80, 190), process
    )
    _assert_single_blocker(
        result,
        "geometry_invalid",
        "Requested stand base depth exceeds the confirmed max footprint height.",
        ("stand-base",),
    )


def test_stand_base_depth_overflowing_stock_is_blocked():
    plan, _parameters, process = build()
    larger_limit = plan.model_copy(
        update={
            "constraints": plan.constraints.model_copy(
                update={"max_footprint_height_mm": measured(1000)}
            )
        }
    )
    _snapshot_obj, result = _simulate(
        larger_limit,
        _patch(larger_limit, "stand-base", 80, 400),
        process,
    )
    assert result.status == "blocked"
    assert any(
        blocker.code == "geometry_invalid"
        and blocker.message == "Child cut exceeds source or edge margin."
        for blocker in result.blockers
    )


def test_stand_plan_with_declared_offcut_is_unsupported():
    plan, _parameters, process = build()
    operations = tuple(
        operation.model_copy(
            update={
                "effects": operation.effects.model_copy(
                    update={
                        "created_offcuts": (
                            m.Region(
                                id="synthetic-offcut",
                                geometry=m.Rect(x=100, y=4, width=10, height=10),
                            ),
                        )
                    }
                )
            }
        )
        if operation.id == "stand-cut-panels"
        else operation
        for operation in plan.operations
    )
    changed = plan.model_copy(update={"operations": operations})
    _snapshot_obj, result = _simulate(
        changed, _patch(changed, "stand-base", 80, 150), process
    )
    _assert_single_blocker(
        result,
        "unsupported",
        "Stand base extension does not support plans with declared offcuts.",
        ("stand-cut-panels",),
    )


def test_stand_resize_without_cut_process_is_blocked():
    plan, _parameters, _process = build()
    snapshot = _snapshot(plan, _patch(plan, "stand-base", 80, 150))
    result = simulate_patch(
        snapshot,
        process=None,
        allow_synthetic=True,
        family_validator=stand_continuation_blockers,
    )
    assert result.status == "blocked"
    assert any(
        blocker.code == "unsupported_profile"
        and blocker.message
        == "Cutting requires measured process evidence; synthetic fixtures require explicit opt-in."
        for blocker in result.blockers
    )
