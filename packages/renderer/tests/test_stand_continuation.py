"""Synthetic software fixtures only. No physical build or test was performed."""

import copy
import xml.etree.ElementTree as ET
from math import cos, radians, sin

import pytest
from forma_renderer import render_manual, stand_continuation_blockers
from forma_replanner import simulate_patch
from test_stand_manual import build

from forma_domain import models as m


def _with_part(plan, part_id, **updates):
    parts = tuple(
        p.model_copy(update=updates) if p.id == part_id else p for p in plan.parts
    )
    return plan.model_copy(update={"parts": parts})


def _with_op_args(plan, op_id, **updates):
    operations = tuple(
        o.model_copy(update={"args": o.args.model_copy(update=updates)})
        if o.id == op_id
        else o
        for o in plan.operations
    )
    return plan.model_copy(update={"operations": operations})


def test_v1_plan_has_no_continuation_blockers():
    plan, _parameters, _process = build()
    assert stand_continuation_blockers(plan) == ()


def test_incorrect_brace_height_is_geometry_blocker():
    plan, _parameters, _process = build()
    brace = next(p for p in plan.parts if p.id == "stand-brace")
    changed = _with_part(
        plan,
        "stand-brace",
        geometry=brace.geometry.model_copy(
            update={"height": brace.geometry.height + 5}
        ),
    )
    blockers = stand_continuation_blockers(changed)
    assert any(
        b.code == "geometry_invalid" and "Brace height" in b.message for b in blockers
    )


def test_incorrect_width_is_geometry_blocker():
    plan, _parameters, _process = build()
    base = next(p for p in plan.parts if p.id == "stand-base")
    changed = _with_part(
        plan,
        "stand-base",
        geometry=base.geometry.model_copy(update={"width": base.geometry.width + 5}),
    )
    blockers = stand_continuation_blockers(changed)
    assert any(
        b.code == "geometry_invalid" and "equal widths" in b.message for b in blockers
    )


def test_incorrect_test_mass_is_blocked():
    plan, _parameters, _process = build()
    changed = _with_op_args(plan, "stand-functional-test", mass_g=999)
    blockers = stand_continuation_blockers(changed)
    assert any("mass" in b.message.lower() for b in blockers)


def test_missing_matching_checkpoint_is_blocked():
    plan, _parameters, _process = build()
    changed = _with_op_args(
        plan, "stand-inspect-cuts", checkpoint_id="no-such-checkpoint"
    )
    blockers = stand_continuation_blockers(changed)
    assert any(
        b.code == "invalid_reference" and "checkpoint" in b.message.lower()
        for b in blockers
    )


def test_extra_operation_is_blocked():
    plan, _parameters, _process = build()
    extra = plan.operations[1].model_copy(update={"id": "extra-inspect"})
    changed = plan.model_copy(update={"operations": plan.operations + (extra,)})
    blockers = stand_continuation_blockers(changed)
    assert any(b.code == "unsupported" for b in blockers)


def test_validation_does_not_mutate_plan():
    plan, _parameters, _process = build()
    before = copy.deepcopy(plan)
    assert stand_continuation_blockers(plan) == ()
    assert plan.model_dump() == before.model_dump()


def _replacement(target_id="stand-brace"):
    plan, _parameters, process = build()
    sheet = next(s for s in plan.stocks if s.kind == "sheet")
    spare = sheet.model_copy(
        update={
            "id": "spare",
            "usable_regions": (
                m.Region(
                    id="spare-region",
                    geometry=sheet.usable_regions[0].geometry,
                ),
            ),
        }
    )
    base = plan.model_copy(update={"stocks": plan.stocks + (spare,)})
    remaining = tuple(
        s.model_copy(update={"usable_regions": ()}) if s.id == sheet.id else s
        for s in base.stocks
    )
    event = m.PhysicalEvent(
        id="synthetic-stand-cut-confirmed",
        project_id=base.project_id,
        version_id=base.version_id,
        operation_id="stand-cut-panels",
        kind="operation_confirmed",
        evidence_ids=(),
        recorded_at=base.created_at,
        actor="user",
        observation=(
            "SYNTHETIC user-confirmed stand cut for a software fixture; "
            "no physical build was performed."
        ),
        verification_state="user_confirmed",
    )
    snapshot = m.ReplannerInput(
        base_plan=base,
        events=(event,),
        evidence=(),
        material_transactions=(),
        remaining_stock=remaining,
        patch=m.RepairPatch(
            id="replace-stand-brace",
            base_version_id=base.version_id,
            kind="replace_part",
            target_id=target_id,
            replacement_stock_id="spare",
            replacement_profile_id=None,
            width_mm=None,
            height_mm=None,
            angle_deg=None,
            rationale="SYNTHETIC replacement of the stand brace from spare stock.",
        ),
    )
    before = copy.deepcopy(snapshot)
    result = simulate_patch(
        snapshot,
        process=process,
        allow_synthetic=True,
        family_validator=stand_continuation_blockers,
    )
    return base, snapshot, before, result


def _new_brace_id(base, result):
    new_ids = {p.id for p in result.plan.parts} - {p.id for p in base.parts}
    assert len(new_ids) == 1
    return next(iter(new_ids))


def _replacement_plan():
    base, _snapshot, _before, result = _replacement()
    assert result.status == "feasible", result.blockers
    return result.plan, _new_brace_id(base, result)


def _assert_blocker(plan, code, fragment):
    blockers = stand_continuation_blockers(plan)
    assert any(b.code == code and fragment in b.message for b in blockers), blockers


def test_replace_brace_from_spare_is_feasible_and_preserves_history():
    base, snapshot, before, result = _replacement()

    assert snapshot.model_dump() == before.model_dump()
    assert result.status == "feasible", result.blockers
    assert result.blockers == ()
    assert stand_continuation_blockers(result.plan) == ()

    new_id = _new_brace_id(base, result)
    base_parts = {p.id: p for p in base.parts}
    result_parts = {p.id: p for p in result.plan.parts}
    base_ops = {o.id: o for o in base.operations}
    result_ops = {o.id: o for o in result.plan.operations}

    # The retired brace and the grouped cut that also produced useful
    # support/base panels remain unchanged.
    assert result_parts["stand-brace"] == base_parts["stand-brace"]
    assert result_ops["stand-cut-panels"] == base_ops["stand-cut-panels"]
    assert result.lost_part_ids == ("stand-brace",)
    assert result.lost_operation_ids == ()
    assert result.preserved_operation_ids == ("stand-cut-panels",)

    new_brace = result_parts[new_id]
    assert new_id != "stand-brace"
    assert new_brace.source_stock_id == "spare"
    assert new_brace.source_region_id == "spare-region"
    assert new_brace.geometry.width == base_parts["stand-brace"].geometry.width
    assert new_brace.geometry.height == base_parts["stand-brace"].geometry.height

    new_cuts = [
        o
        for o in result.plan.operations
        if o.type == "cut_rect" and o.id != "stand-cut-panels"
    ]
    assert len(new_cuts) == 1
    new_cut = new_cuts[0]
    assert new_cut.id not in base_ops
    assert tuple(new_cut.args.child_part_ids) == (new_id,)
    assert new_cut.args.stock_id == "spare"
    assert new_cut.args.source_region_id == "spare-region"

    joints = {j.id: j for j in result.plan.joints}
    assert joints["stand-joint-front"].part_ids == ("stand-support", "stand-base")
    assert joints["stand-joint-rear"].part_ids == ("stand-base", new_id)
    assert joints["stand-joint-apex"].part_ids == ("stand-support", new_id)

    for op in result.plan.operations:
        assert "stand-brace" not in op.preconditions.accessible_part_ids
    for joint_id in ("stand-joint-rear", "stand-joint-apex"):
        tape_op = next(
            o
            for o in result.plan.operations
            if getattr(o.args, "joint_id", None) == joint_id
        )
        assert new_id in tape_op.preconditions.accessible_part_ids
        assert "stand-brace" not in tape_op.part_ids

    assert set(result.invalidated_checkpoint_ids) == {c.id for c in base.checkpoints}
    assert {"stand-brace", new_id} <= set(result.changed_part_ids)

    retire = [d for d in result.proposed_material_deltas if d.kind == "retire_part"]
    assert len(retire) == 1
    old_brace = base_parts["stand-brace"]
    assert retire[0].stock_id == old_brace.source_stock_id
    assert retire[0].source_region_id == old_brace.source_region_id
    assert retire[0].quantity == (old_brace.geometry.width * old_brace.geometry.height)


def test_replacement_with_unequal_width_is_blocked():
    plan, new_id = _replacement_plan()
    brace = next(p for p in plan.parts if p.id == new_id)
    changed = _with_part(
        plan,
        new_id,
        geometry=brace.geometry.model_copy(update={"width": brace.geometry.width + 5}),
    )
    _assert_blocker(changed, "geometry_invalid", "same width and height")


def test_replacement_with_retired_accessibility_is_blocked():
    plan, _new_id = _replacement_plan()
    operations = tuple(
        o.model_copy(
            update={
                "preconditions": o.preconditions.model_copy(
                    update={"accessible_part_ids": ("stand-brace",)}
                )
            }
        )
        if getattr(o.args, "joint_id", None) == "stand-joint-rear"
        else o
        for o in plan.operations
    )
    changed = plan.model_copy(update={"operations": operations})
    _assert_blocker(changed, "invalid_reference", "references retired part(s)")


def test_replacement_with_misplaced_supplemental_cut_is_blocked():
    plan, new_id = _replacement_plan()
    cut = next(
        o
        for o in plan.operations
        if o.type == "cut_rect" and tuple(o.args.child_part_ids) == (new_id,)
    )
    operations = tuple(o for o in plan.operations if o.id != cut.id) + (cut,)
    changed = plan.model_copy(update={"operations": operations})
    _assert_blocker(changed, "unsupported", "must occur before")


def test_replacement_with_unrelated_part_and_cut_is_blocked():
    plan, new_id = _replacement_plan()
    brace = next(p for p in plan.parts if p.id == new_id)
    cut = next(
        o
        for o in plan.operations
        if o.type == "cut_rect" and tuple(o.args.child_part_ids) == (new_id,)
    )
    unrelated_part = brace.model_copy(update={"id": "unrelated-part"})
    unrelated_cut = cut.model_copy(
        update={
            "id": "unrelated-cut",
            "args": cut.args.model_copy(update={"child_part_ids": ("unrelated-part",)}),
        }
    )
    changed = plan.model_copy(
        update={
            "parts": plan.parts + (unrelated_part,),
            "operations": plan.operations + (unrelated_cut,),
        }
    )
    _assert_blocker(changed, "invalid_reference", "not an active replacement part")


def test_replacement_with_wrong_joint_topology_is_blocked():
    plan, _new_id = _replacement_plan()
    joints = tuple(
        j.model_copy(update={"part_ids": tuple(reversed(j.part_ids))})
        if j.id == "stand-joint-rear"
        else j
        for j in plan.joints
    )
    changed = plan.model_copy(update={"joints": joints})
    _assert_blocker(changed, "unsupported", "must have ordered part_ids")


def test_replacement_with_missing_checkpoint_is_blocked():
    plan, _new_id = _replacement_plan()
    changed = plan.model_copy(update={"checkpoints": plan.checkpoints[1:]})
    _assert_blocker(changed, "invalid_reference", "has no matching checkpoint")


def _svg_part_ids(panel):
    root = ET.fromstring(panel.svg)
    return {
        node.attrib["data-part-id"]
        for node in root.iter()
        if "data-part-id" in node.attrib
    }


def test_render_replacement_plan():
    base, _snapshot, _before, result = _replacement()
    assert result.status == "feasible", result.blockers
    original_plan, parameters, process = build()
    original = render_manual(
        original_plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
    )
    rendered = render_manual(
        result.plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
    )
    assert original.status == "accepted", original.blockers
    assert rendered.status == "accepted", rendered.blockers
    assert rendered.physical_verification == "not_attempted"

    new_id = _new_brace_id(base, result)
    core_child_ids = ("stand-support", "stand-base", "stand-brace")
    core_ops = [
        o
        for o in result.plan.operations
        if not (o.type == "cut_rect" and tuple(o.args.child_part_ids) != core_child_ids)
    ]
    supplemental_ops = [
        o
        for o in result.plan.operations
        if o.type == "cut_rect" and tuple(o.args.child_part_ids) != core_child_ids
    ]
    assert len(core_ops) == 8
    assert len(supplemental_ops) == 1
    panels_by_id = {p.operation_id: p for p in rendered.panels}
    assert set(panels_by_id) == {o.id for o in result.plan.operations}

    # The retained core cut renders exactly as in the original plan.
    original_cut = next(
        p for p in original.panels if p.operation_id == "stand-cut-panels"
    )
    core_cut = panels_by_id["stand-cut-panels"]
    assert core_cut.part_ids == core_child_ids
    assert core_cut.dependency_hash == original_cut.dependency_hash
    assert core_cut.svg == original_cut.svg

    # Core panels keep their original Step N/8 numbering.
    for core_index, op in enumerate(core_ops):
        panel = panels_by_id[op.id]
        assert f"Step {core_index + 1}/8" in panel.svg
        assert f"Step {core_index + 1}:" in panel.svg

    # The supplemental cut is a single-panel replacement cut.
    replacement_cut = panels_by_id[supplemental_ops[0].id]
    assert replacement_cut.part_ids == (new_id,)
    assert len(replacement_cut.part_ids) == 1
    assert _svg_part_ids(replacement_cut) == set(replacement_cut.part_ids)
    assert "Replacement cut" in replacement_cut.svg
    assert "the one labelled panel" in replacement_cut.svg

    # Assembly (side-view) panels use the new brace, never the retired one.
    side_ops = core_ops[3:]
    assert len(side_ops) == 5
    for op in side_ops:
        panel = panels_by_id[op.id]
        assert "stand-brace" not in _svg_part_ids(panel)
        assert new_id in _svg_part_ids(panel)
        assert new_id in panel.svg

    # Consumers of the replacement differ from the original render.
    original_by_core = list(original.panels)
    assert len(original_by_core) == 8
    for core_index, op in enumerate(core_ops):
        if new_id not in panels_by_id[op.id].part_ids:
            continue
        if op.id == supplemental_ops[0].id:
            continue
        assert (
            panels_by_id[op.id].dependency_hash
            != original_by_core[core_index].dependency_hash
        )

    # All historical parts remain in the bill of materials.
    bill_ids = {item.id for item in rendered.bill_of_materials}
    assert {"stand-support", "stand-base", "stand-brace", new_id} <= bill_ids


@pytest.mark.parametrize("target", ["stand-support", "stand-base", "stand-brace"])
def test_replaced_roles_render_connected_triangle_and_active_lip(target):
    base, _, _, result = _replacement(target)
    assert result.status == "feasible", result.blockers
    _, parameters, process = build()
    rendered = render_manual(
        result.plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
    )
    assert rendered.status == "accepted", rendered.blockers
    new_id = next(
        p.id for p in result.plan.parts if p.id not in {x.id for x in base.parts}
    )
    joints = {j.id: j for j in result.plan.joints}
    support_id, base_id = joints["stand-joint-front"].part_ids
    brace_id = joints["stand-joint-rear"].part_ids[1]
    parts = {p.id: p for p in result.plan.parts}
    support = parts[support_id]
    length = support.features[0].geometry.y
    depth = parts[base_id].geometry.height
    theta = radians(result.plan.constraints.support_angle_deg.value)
    reach, rise = length * cos(theta), length * sin(theta)
    scale = min(400 / depth, 300 / rise)
    start, apex, rear = (
        (120, 555),
        (120 + reach * scale, 555 - rise * scale),
        (120 + depth * scale, 555),
    )
    expected = {
        base_id: (*start, *rear),
        support_id: (*start, *apex),
        brace_id: (*apex, *rear),
    }
    fit_id = next(
        c.after_operation_id
        for c in result.plan.checkpoints
        if c.id == "stand-inspect-fit-check"
    )
    fit = next(p for p in rendered.panels if p.operation_id == fit_id)
    assert "Side elevation; nominal zero-thickness geometry" in fit.svg
    root = ET.fromstring(fit.svg)
    ns = "{http://www.w3.org/2000/svg}"
    for part_id, coords in expected.items():
        group = next(n for n in root.iter() if n.attrib.get("data-part-id") == part_id)
        line = next(
            n
            for n in group
            if n.tag == ns + "line" and n.attrib.get("stroke-width") == "5"
        )
        assert tuple(
            float(line.attrib[a]) for a in ("x1", "y1", "x2", "y2")
        ) == pytest.approx(coords, abs=1e-6)
    assert target not in _svg_part_ids(fit)
    assert new_id in _svg_part_ids(fit)
    if target == "stand-support":
        feature_id = support.features[0].id
        assert feature_id != "stand-lip-fold"
        fold = next(
            p for p in rendered.panels if p.tools == ("ruler", "confirmed folding tool")
        )
        assert f"Fold {new_id} on {feature_id}" in fold.svg
        assert any(n.attrib.get("data-feature-id") == feature_id for n in root.iter())


def test_historical_v1_all_panel_hashes():
    # Captured from unchanged main6a876c1 before the continuation refactor.
    for alternate, expected in (
        (
            False,
            (
                "a517c33dad324c5a7dca685922fa46ca5f36a2255977d5550b7648f39a49bab2",
                "796812c9fa625d9a15a325c2524842f3ac172776f9d9c13d673a13edcddab635",
                "039f2166a5907eb812d0ada8ec9c50ffc7030f38e18e974eff5a4aa2ca3803a2",
                "25ae378d7a6a452278349bd05b3683b56a965f5aaf04547f8a63fd6e761bdd5d",
                "b7ebeacd41a4af8c6595dea72a16f1d7df73a4bef814443a8e0ea94dd999b58c",
                "b9acadaed79d367ac3df773677c6b38a2b1e9e394ad70b9b56a74d54ab717e35",
                "438e2b4ff470700a241cf7fc37f6a67d8674464d504a08f78364661f9f82dfb6",
                "28c2e23d476627523bc9205b2a389e603aa8849e18015a66ed1647b019190fd5",
            ),
        ),
        (
            True,
            (
                "ca7c469bfae41098e20372ea6a78e5e57cbe34640b7ac4ba36ffecc05b99be09",
                "d842c6add1a5c6135b37f477c4a0d02694dcc834792896e404320926af70e01b",
                "c2c29bcfc153b93190855e4ad7bd2837d5b218c371e8e31420885d731e9e5ead",
                "55e6dec3897778bf8de676f1d58f48b2656212243c18b24135544fcf0ca3f585",
                "990189bd2a34e64239f374c637d5b6b2f22a7b420b3a36fd57d5525ab8681966",
                "15d84e5ae757ae7216a4c2534473da4baeeb5868b1a795e08ff1bbd877712c6a",
                "9f6f3471d291b681ade598b4fced10bc2d1aa8ff3a936a42e43108f88686c588",
                "4add38e8cde903c2b6e1c1322d460868f89a191fbd80509a0fa407d3e8c51cdb",
            ),
        ),
    ):
        plan, parameters, process = build(alternate=alternate)
        result = render_manual(
            plan,
            process=process,
            profile_evidence=parameters.profile_evidence,
            allow_synthetic=True,
        )
        assert result.status == "accepted", result.blockers
        assert tuple(p.dependency_hash for p in result.panels) == expected


def test_replacement_with_base_depth_not_exceeding_reach_is_blocked():
    plan, _new_id = _replacement_plan()
    base = next(p for p in plan.parts if p.id == "stand-base")
    changed = _with_part(
        plan,
        "stand-base",
        geometry=base.geometry.model_copy(update={"height": 10}),
    )
    _assert_blocker(
        changed,
        "geometry_invalid",
        "Base depth must exceed the horizontal reach of the support.",
    )
