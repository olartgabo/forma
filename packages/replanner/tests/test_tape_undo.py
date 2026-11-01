"""SYNTHETIC tape-undo fixtures only; no physical build was performed."""

import copy
from datetime import UTC, datetime

import pytest
from forma_compiler import CutProcess
from forma_renderer import StandParameters, compile_stand, stand_continuation_blockers
from forma_replanner import rank_feasible, simulate_patch
from forma_replanner.tape_undo import peel_human_checks

from forma_domain import models as m


def measured(value, unit="mm"):
    return m.Measurement(value=value, unit=unit, source="calculated", confirmed=True)


def build_plan(tape_length=500):
    now = datetime(2026, 10, 30, tzinfo=UTC)
    unknown = m.Measurement(value=None, unit="mm", source="unknown", confirmed=False)
    evidence = tuple(
        m.Evidence(
            id=name,
            project_id="fixture-project",
            version_id="fixture-v1",
            kind="measurement",
            provenance="synthetic_fixture",
            recorded_at=now,
            description="SYNTHETIC software fixture only, not physically tested",
            verification_state="unknown",
        )
        for name in ("fixture-process", "fixture-tape", "fixture-fold")
    )
    sheet = m.Stock(
        id="fixture-sheet",
        kind="sheet",
        material="cardboard",
        condition="usable",
        width_mm=measured(200),
        height_mm=measured(550),
        thickness_mm=measured(2),
        remaining_length_mm=unknown,
        usable_regions=(
            m.Region(
                id="fixture-region",
                geometry=m.Rect(x=0, y=0, width=200, height=550),
            ),
        ),
    )
    tape = m.Stock(
        id="fixture-tape-stock",
        kind="tape",
        material="other_supported",
        condition="usable",
        width_mm=measured(30),
        height_mm=unknown,
        thickness_mm=unknown,
        remaining_length_mm=measured(tape_length),
    )
    profiles = tuple(
        m.JointProfile(
            id=f"fixture-{name}-profile",
            strategy=strategy,
            status="tested",
            material="cardboard",
            thickness_min_mm=1,
            thickness_max_mm=3,
            tolerated_error_mm=1,
            test_evidence_ids=(f"fixture-{name}",),
            limitations=("SYNTHETIC only",),
        )
        for name, strategy in (("tape", "tape"), ("fold", "fold_brace"))
    )
    limits = m.Constraints(
        device_mass_g=measured(180, "g"),
        support_angle_deg=measured(60, "deg"),
        max_footprint_width_mm=measured(120),
        max_footprint_height_mm=measured(180),
        allowed_profile_ids=tuple(p.id for p in profiles),
    )
    request = m.CompilerInput(
        project_id="fixture-project",
        version_id="fixture-v1",
        created_at=now,
        candidate=m.DesignCandidate(
            id="fixture-candidate",
            family="tabletop_fixture_v1",
            support_angle_deg=60,
            part_width_mm=80,
            part_height_mm=150,
            panel_count=3,
            stock_ids=(sheet.id, tape.id),
            profile_ids=tuple(p.id for p in profiles),
            assumptions=("SYNTHETIC only",),
        ),
        stocks=(sheet, tape),
        joint_profiles=profiles,
        constraints=limits,
        kerf_mm=2,
        edge_margin_mm=4,
        process_evidence_ids=("fixture-process",),
    )
    parameters = StandParameters(
        footprint_depth_mm=measured(140),
        lip_mm=measured(15),
        device_width_mm=measured(70),
        device_thickness_mm=measured(8),
        device_contact_height_mm=measured(100),
        tape_overlap_mm=measured(10),
        tools_confirmed=True,
        joint_access_confirmed=True,
        device_label="SYNTHETIC phone specimen",
        test_duration_seconds=60,
        test_surface="SYNTHETIC flat desk",
        test_pass_criteria=("No slip or tip",),
        profile_evidence=evidence[1:],
    )
    process = CutProcess(kerf_min_mm=2, edge_margin_min_mm=4, evidence=(evidence[0],))
    compiled = compile_stand(request, parameters, process=process, allow_synthetic=True)
    assert compiled.status == "accepted", compiled.blockers
    return compiled.plan, process


def attached_snapshot(tape_length=500, spare_height=550):
    plan, process = build_plan(tape_length)
    sheet = next(s for s in plan.stocks if s.kind == "sheet")
    spare = sheet.model_copy(
        update={
            "id": "spare",
            "height_mm": sheet.height_mm.model_copy(update={"value": spare_height}),
            "usable_regions": (
                m.Region(
                    id="spare-region",
                    geometry=m.Rect(x=0, y=0, width=200, height=spare_height),
                ),
            ),
        }
    )
    base = plan.model_copy(update={"stocks": plan.stocks + (spare,)})
    events = tuple(
        m.PhysicalEvent(
            id=f"synthetic-tape-undo-{o.id}",
            project_id=base.project_id,
            version_id=base.version_id,
            operation_id=o.id,
            kind="operation_confirmed",
            evidence_ids=(),
            recorded_at=base.created_at,
            actor="user",
            observation="SYNTHETIC user-confirmed operation; no physical build.",
            verification_state="user_confirmed",
        )
        for o in base.operations[:6]
    )
    remaining = tuple(
        stock.model_copy(update={"usable_regions": ()})
        if stock.id == sheet.id
        else stock.model_copy(
            update={
                "remaining_length_mm": stock.remaining_length_mm.model_copy(
                    update={"value": tape_length - 240}
                )
            }
        )
        if stock.kind == "tape"
        else stock
        for stock in base.stocks
    )
    snapshot = m.ReplannerInput(
        base_plan=base,
        events=events,
        evidence=(),
        material_transactions=(),
        remaining_stock=remaining,
        patch=m.RepairPatch(
            id="replace-attached-brace-tape-undo",
            base_version_id=base.version_id,
            kind="replace_part",
            target_id="stand-brace",
            replacement_stock_id="spare",
            replacement_profile_id=None,
            width_mm=None,
            height_mm=None,
            angle_deg=None,
            rationale="SYNTHETIC tape-undo replacement of the attached brace.",
        ),
    )
    return base, snapshot, process


def simulate(snapshot, process):
    before = copy.deepcopy(snapshot)
    result = simulate_patch(
        snapshot,
        process=process,
        allow_synthetic=True,
        family_validator=stand_continuation_blockers,
    )
    assert snapshot.model_dump() == before.model_dump()
    return result


def test_peel_human_checks_name_all_confirmations():
    checks = " ".join(peel_human_checks("stand-joint-rear", "stand-base")).lower()
    assert all(word in checks for word in ("device", "support", "access", "undamaged"))
    assert "stand-base" in checks


def test_attached_brace_peel_and_reattach_leaves_100mm():
    base, snapshot, process = attached_snapshot()
    result = simulate(snapshot, process)
    assert result.status == "feasible", result.blockers
    assert rank_feasible((result,)) == (result,)
    assert result.cost is not None and result.cost.known_weighted_cost == 8
    peels = [o for o in result.plan.operations if o.type == "detach"]
    assert tuple(result.required_undo_operation_ids) == tuple(o.id for o in peels)
    assert len(peels) == 2
    assert result.plan.operations[:6] == base.operations[:6]
    tape_uses = [
        d.quantity
        for d in result.proposed_material_deltas
        if d.stock_id == "fixture-tape-stock" and d.kind == "consume"
    ]
    assert tape_uses == [80, 80]
    assert 500 - 240 - sum(tape_uses) == 100
    assert all(o.id in result.incomplete_operation_ids for o in peels)


def test_completed_functional_test_without_fit_blocks():
    completed_final_checks = ("stand-functional-test",)
    base, snapshot, process = attached_snapshot()
    ops = {o.id: o for o in base.operations}
    extra_events = tuple(
        m.PhysicalEvent(
            id=f"synthetic-tape-undo-{op_id}",
            project_id=base.project_id,
            version_id=base.version_id,
            operation_id=op_id,
            kind="operation_confirmed",
            evidence_ids=(),
            recorded_at=base.created_at,
            actor="user",
            observation="SYNTHETIC user-confirmed operation; no physical build.",
            verification_state="user_confirmed",
        )
        for op_id in completed_final_checks
    )
    assert all(op_id in ops for op_id in completed_final_checks)
    changed = snapshot.model_copy(update={"events": snapshot.events + extra_events})
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None
    assert result.cost is None
    # Simulation rejects a test completion that precedes its fit
    # prerequisite before any candidate can be constructed.
    assert any(
        b.code == "invalid_order" and b.target_ids == completed_final_checks
        for b in result.blockers
    ), result.blockers
    # Completion history is preserved and not stripped to obtain a candidate.
    assert tuple(e.operation_id for e in changed.events[-len(extra_events) :]) == (
        completed_final_checks
    )


def test_dependent_evidence_and_checkpoints_invalidate():
    base, snapshot, process = attached_snapshot()
    evidence = m.Evidence(
        id="synthetic-dependent-evidence",
        project_id=base.project_id,
        version_id=base.version_id,
        kind="user_report",
        provenance="user",
        part_ids=("stand-brace",),
        operation_ids=("stand-inspect-cuts",),
        checkpoint_ids=("stand-inspect-cuts-check",),
        recorded_at=base.created_at,
        description="SYNTHETIC dependent evidence for the attached brace.",
        verification_state="user_confirmed",
    )
    changed = snapshot.model_copy(update={"evidence": (evidence,)})
    result = simulate(changed, process)
    assert result.status == "feasible", result.blockers
    assert result.invalidated_evidence_ids == (evidence.id,)
    assert "stand-inspect-fit-check" in result.invalidated_checkpoint_ids
    assert "stand-inspect-cuts-check" in result.invalidated_checkpoint_ids


def test_initial_399mm_tape_blocks_without_refund():
    _base, snapshot, process = attached_snapshot(tape_length=399)
    result = simulate(snapshot, process)
    assert result.status == "blocked"
    assert result.plan is None
    assert any(b.code == "stock_exhausted" for b in result.blockers)


def test_insufficient_remaining_sheet_blocks():
    _base, snapshot, process = attached_snapshot(spare_height=100)
    result = simulate(snapshot, process)
    assert result.status == "blocked"
    assert any(b.code == "stock_exhausted" for b in result.blockers)


def test_stale_patch_scope_blocks():
    base, snapshot, process = attached_snapshot()
    stale = snapshot.model_copy(
        update={
            "patch": snapshot.patch.model_copy(
                update={"base_version_id": "not-the-base-version"}
            )
        }
    )
    before = copy.deepcopy(stale)
    result = simulate_patch(
        stale,
        process=process,
        allow_synthetic=True,
        family_validator=stand_continuation_blockers,
    )
    assert stale.model_dump() == before.model_dump()
    assert result.status == "blocked"
    assert any(b.code == "stale_version" for b in result.blockers)
    assert base.version_id != "not-the-base-version"


def full_snapshot(tape_length=500):
    base, snapshot, process = attached_snapshot(tape_length=tape_length)
    checks = {c.after_operation_id: c.id for c in base.checkpoints}

    def evidence(eid, parts, ops):
        return m.Evidence(
            id=eid,
            project_id=base.project_id,
            version_id=base.version_id,
            kind="user_report",
            provenance="user",
            part_ids=parts,
            operation_ids=ops,
            checkpoint_ids=tuple(checks[o] for o in ops if o in checks),
            recorded_at=base.created_at,
            description=f"SYNTHETIC user evidence {eid}; no physical build.",
            verification_state="user_confirmed",
        )

    records = (
        evidence(
            "synthetic-full-cut-evidence",
            ("stand-brace",),
            ("stand-cut-panels",),
        ),
        evidence(
            "synthetic-full-fit-evidence",
            ("stand-support", "stand-base", "stand-brace"),
            ("stand-inspect-fit",),
        ),
        evidence(
            "synthetic-full-function-evidence",
            ("stand-support", "stand-base", "stand-brace"),
            ("stand-functional-test",),
        ),
    )
    by_op = {
        "stand-cut-panels": (records[0].id,),
        "stand-inspect-fit": (records[1].id,),
        "stand-functional-test": (records[2].id,),
    }
    events = tuple(
        e.model_copy(update={"evidence_ids": by_op[e.operation_id]})
        if e.operation_id in by_op
        else e
        for e in snapshot.events
    ) + tuple(
        m.PhysicalEvent(
            id=f"synthetic-tape-undo-{op_id}",
            project_id=base.project_id,
            version_id=base.version_id,
            operation_id=op_id,
            kind="operation_confirmed",
            evidence_ids=by_op[op_id],
            recorded_at=base.created_at,
            actor="user",
            observation="SYNTHETIC user-confirmed operation; no physical build.",
            verification_state="user_confirmed",
        )
        for op_id in ("stand-inspect-fit", "stand-functional-test")
    )
    changed = snapshot.model_copy(update={"events": events, "evidence": records})
    return base, changed, process


def seven_snapshot(tape_length=500):
    base, snapshot, process = attached_snapshot(tape_length=tape_length)
    checks = {c.after_operation_id: c.id for c in base.checkpoints}
    fit_evidence = m.Evidence(
        id="synthetic-seven-fit-evidence",
        project_id=base.project_id,
        version_id=base.version_id,
        kind="user_report",
        provenance="user",
        part_ids=("stand-support", "stand-base", "stand-brace"),
        operation_ids=("stand-inspect-fit",),
        checkpoint_ids=(checks["stand-inspect-fit"],),
        recorded_at=base.created_at,
        description="SYNTHETIC user evidence; no physical build.",
        verification_state="user_confirmed",
    )
    events = tuple(
        e.model_copy(update={"evidence_ids": (fit_evidence.id,)})
        if e.operation_id == "stand-inspect-fit"
        else e
        for e in snapshot.events
    ) + (
        m.PhysicalEvent(
            id="synthetic-tape-undo-stand-inspect-fit",
            project_id=base.project_id,
            version_id=base.version_id,
            operation_id="stand-inspect-fit",
            kind="operation_confirmed",
            evidence_ids=(fit_evidence.id,),
            recorded_at=base.created_at,
            actor="user",
            observation="SYNTHETIC user-confirmed operation; no physical build.",
            verification_state="user_confirmed",
        ),
    )
    changed = snapshot.model_copy(
        update={"events": events, "evidence": (fit_evidence,)}
    )
    return base, changed, process


def test_seven_prefix_tape_undo_preserves_fit_and_regenerates_finals():
    base, snapshot, process = seven_snapshot()
    result = simulate(snapshot, process)
    assert result.status == "feasible", result.blockers
    assert result.cost is not None and result.cost.known_weighted_cost == 8
    plan = result.plan
    assert len(plan.operations) == 15
    assert plan.operations[:7] == base.operations[:7]
    assert {p.id: p for p in plan.parts if p.id in {x.id for x in base.parts}} == {
        p.id: p for p in base.parts
    }
    assert tuple(j for j in plan.joints if j.id.startswith("stand-joint-"))[:3] == (
        base.joints
    )
    plan_checks = {c.id: c for c in plan.checkpoints}
    fit_check = next(
        c for c in base.checkpoints if c.after_operation_id == "stand-inspect-fit"
    )
    assert plan_checks[fit_check.id] == fit_check
    appended = plan.operations[7:]
    assert [o.type for o in appended] == [
        "detach",
        "detach",
        "cut_rect",
        "inspect",
        "tape_joint",
        "tape_joint",
        "inspect",
        "functional_test",
    ]
    assert all(o.id in result.incomplete_operation_ids for o in appended)
    assert all(o.id in result.incomplete_operation_ids for o in plan.operations[7:])
    peels = appended[:2]
    assert tuple(result.required_undo_operation_ids) == tuple(o.id for o in peels)
    assert "stand-joint-front-attach" in result.preserved_operation_ids
    assert "stand-inspect-fit" not in result.preserved_operation_ids
    assert fit_check.id in result.invalidated_checkpoint_ids
    assert result.invalidated_evidence_ids == ("synthetic-seven-fit-evidence",)
    new_id = next(p.id for p in plan.parts if p.id not in {x.id for x in base.parts})
    active = ("stand-support", "stand-base", new_id)
    new_fit, new_test = appended[-2], appended[-1]
    assert new_fit.id not in {o.id for o in base.operations}
    assert new_test.id not in {o.id for o in base.operations}
    assert "stand-functional-test" not in {o.id for o in plan.operations}
    assert new_fit.part_ids == active and tuple(new_fit.args.target_ids) == active
    assert new_test.part_ids == active
    new_joints = [j for j in plan.joints if j.id not in {x.id for x in base.joints}]
    assert tuple(new_test.preconditions.required_joint_ids) == (
        "stand-joint-front",
        *[j.id for j in new_joints],
    )
    orig_test = next(o for o in base.operations if o.id == "stand-functional-test")
    assert new_test.args.device_label == orig_test.args.device_label
    assert new_test.args.mass_g == orig_test.args.mass_g
    assert new_test.args.duration_seconds == orig_test.args.duration_seconds
    assert new_test.args.surface == orig_test.args.surface
    assert new_test.args.pass_criteria == orig_test.args.pass_criteria
    for op in (new_fit, new_test):
        assert any(
            c.after_operation_id == op.id and c.id == op.args.checkpoint_id
            for c in plan.checkpoints
        )
    tape_uses = [
        d.quantity
        for d in result.proposed_material_deltas
        if d.stock_id == "fixture-tape-stock" and d.kind == "consume"
    ]
    assert tape_uses == [80, 80]
    assert 500 - 240 - sum(tape_uses) == 100


def _extra_event(base, event_id, operation_id, **updates):
    fields = {
        "id": event_id,
        "project_id": base.project_id,
        "version_id": base.version_id,
        "operation_id": operation_id,
        "kind": "observation",
        "evidence_ids": (),
        "recorded_at": base.created_at,
        "actor": "user",
        "observation": "SYNTHETIC persisted reference; no physical build.",
        "verification_state": "user_confirmed",
    }
    fields.update(updates)
    return m.PhysicalEvent(**fields)


def test_persisted_observation_on_unfinished_fit_blocks_six_prefix():
    base, snapshot, process = attached_snapshot()
    event = _extra_event(base, "synthetic-obs-fit", "stand-inspect-fit")
    changed = snapshot.model_copy(update={"events": snapshot.events + (event,)})
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None and result.cost is None
    assert any(
        b.code == "invalid_reference" and b.target_ids == ("stand-inspect-fit",)
        for b in result.blockers
    ), result.blockers
    assert changed.events[-1] == event


def test_persisted_not_attempted_test_on_unfinished_function_blocks_six_prefix():
    base, snapshot, process = attached_snapshot()
    event = _extra_event(
        base,
        "synthetic-test-not-attempted",
        "stand-functional-test",
        kind="test",
        verification_state="not_checked",
        test_result="not_attempted",
    )
    changed = snapshot.model_copy(update={"events": snapshot.events + (event,)})
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None and result.cost is None
    assert any(
        b.code == "invalid_reference" and b.target_ids == ("stand-functional-test",)
        for b in result.blockers
    ), result.blockers


def test_persisted_future_function_checkpoint_evidence_blocks_six_prefix():
    base, snapshot, process = attached_snapshot()
    check_id = next(
        c.id
        for c in base.checkpoints
        if c.after_operation_id == "stand-functional-test"
    )
    evidence = m.Evidence(
        id="synthetic-future-function-check-evidence",
        project_id=base.project_id,
        version_id=base.version_id,
        kind="user_report",
        provenance="user",
        checkpoint_ids=(check_id,),
        recorded_at=base.created_at,
        description="SYNTHETIC future checkpoint evidence; no physical build.",
        verification_state="not_checked",
    )
    changed = snapshot.model_copy(update={"evidence": (evidence,)})
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None
    assert any(
        b.code == "invalid_reference" and b.target_ids == ("stand-functional-test",)
        for b in result.blockers
    ), result.blockers
    assert changed.evidence == (evidence,)


def test_persisted_reference_to_unfinished_function_blocks_seven_prefix():
    base, snapshot, process = seven_snapshot()
    event = _extra_event(
        base,
        "synthetic-seven-test-not-attempted",
        "stand-functional-test",
        kind="test",
        verification_state="not_checked",
        test_result="not_attempted",
    )
    changed = snapshot.model_copy(update={"events": snapshot.events + (event,)})
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None
    assert any(
        b.code == "invalid_reference" and b.target_ids == ("stand-functional-test",)
        for b in result.blockers
    ), result.blockers


def test_persisted_transaction_on_unfinished_fit_blocks_six_prefix():
    base, snapshot, process = attached_snapshot()
    event = _extra_event(base, "synthetic-tx-event", None)
    spare = next(s for s in snapshot.remaining_stock if s.id == "spare")
    region = spare.usable_regions[0]
    tx = m.MaterialTransaction(
        id="synthetic-tx-future-fit",
        project_id=base.project_id,
        version_id=base.version_id,
        operation_id="stand-inspect-fit",
        source_stock_id="spare",
        kind="waste",
        source_region_id=region.id,
        quantity=region.geometry.width * region.geometry.height,
        unit="mm2",
        recorded_at=base.created_at,
        physical_event_id=event.id,
    )
    changed = snapshot.model_copy(
        update={
            "events": snapshot.events + (event,),
            "material_transactions": (tx,),
            "remaining_stock": tuple(
                s.model_copy(update={"usable_regions": ()}) if s.id == "spare" else s
                for s in snapshot.remaining_stock
            ),
        }
    )
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None
    assert any(
        b.code == "invalid_reference" and b.target_ids == ("stand-inspect-fit",)
        for b in result.blockers
    ), result.blockers


def test_failed_function_test_stays_needs_confirmation():
    base, snapshot, process = attached_snapshot()
    event = _extra_event(
        base,
        "synthetic-failed-function",
        "stand-functional-test",
        kind="test",
        verification_state="failed",
        test_result="failed",
    )
    changed = snapshot.model_copy(update={"events": snapshot.events + (event,)})
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None
    assert any(b.code == "needs_confirmation" for b in result.blockers), result.blockers


def test_seven_prefix_with_399mm_tape_blocks():
    _base, snapshot, process = seven_snapshot(tape_length=399)
    result = simulate(snapshot, process)
    assert result.status == "blocked"
    assert result.plan is None
    assert any(b.code == "stock_exhausted" for b in result.blockers)


def test_fully_completed_build_tape_undo_preserves_original_history():
    base, snapshot, process = full_snapshot()
    result = simulate(snapshot, process)
    assert result.status == "feasible", result.blockers
    assert rank_feasible((result,)) == (result,)
    assert result.cost is not None and result.cost.known_weighted_cost == 8
    plan = result.plan
    assert plan.operations[:8] == base.operations
    assert tuple(o.id for o in plan.operations[:8]) == tuple(
        o.id for o in base.operations
    )
    base_checks = {c.id: c for c in base.checkpoints}
    plan_checks = {c.id: c for c in plan.checkpoints}
    assert {k: plan_checks[k] for k in base_checks} == base_checks
    base_parts = {p.id: p for p in base.parts}
    assert {p.id: p for p in plan.parts if p.id in base_parts} == base_parts

    appended = plan.operations[8:]
    assert [o.type for o in appended] == [
        "detach",
        "detach",
        "cut_rect",
        "inspect",
        "tape_joint",
        "tape_joint",
        "inspect",
        "functional_test",
    ]
    peels = appended[:2]
    assert len({o.id for o in peels}) == 2
    assert tuple(result.required_undo_operation_ids) == tuple(o.id for o in peels)
    assert all(o.id in result.incomplete_operation_ids for o in appended)
    assert "stand-joint-front-attach" in result.preserved_operation_ids
    for stale in (
        "stand-joint-rear-attach",
        "stand-joint-apex-attach",
        "stand-inspect-fit",
        "stand-functional-test",
    ):
        assert stale not in result.preserved_operation_ids
    assert {
        "stand-joint-rear-attach",
        "stand-joint-apex-attach",
    } <= set(result.lost_operation_ids)

    checks = {c.after_operation_id: c.id for c in base.checkpoints}
    assert {
        checks["stand-inspect-cuts"],
        checks["stand-inspect-fit"],
        checks["stand-functional-test"],
    } <= set(result.invalidated_checkpoint_ids)
    assert set(result.invalidated_evidence_ids) == {e.id for e in snapshot.evidence}
    # Old evidence records themselves are not rewritten by simulation.
    assert tuple(e.id for e in snapshot.evidence) == (
        "synthetic-full-cut-evidence",
        "synthetic-full-fit-evidence",
        "synthetic-full-function-evidence",
    )

    new_id = next(p.id for p in plan.parts if p.id not in base_parts)
    active = ("stand-support", "stand-base", new_id)
    new_fit, new_test = appended[-2], appended[-1]
    assert new_fit.id not in {o.id for o in base.operations}
    assert new_test.id not in {o.id for o in base.operations}
    assert new_fit.part_ids == active
    assert tuple(new_fit.args.target_ids) == active
    assert new_test.part_ids == active
    new_joints = [j for j in plan.joints if j.id not in {x.id for x in base.joints}]
    assert len(new_joints) == 2
    assert tuple(new_test.preconditions.required_joint_ids) == (
        "stand-joint-front",
        *[j.id for j in new_joints],
    )
    assert new_fit.depends_on == (appended[-3].id,)
    assert new_test.depends_on == (new_fit.id,)
    for op in (new_fit, new_test):
        assert any(
            c.after_operation_id == op.id and c.id == op.args.checkpoint_id
            for c in plan.checkpoints
        )
        assert op.id not in {e.operation_id for e in snapshot.events}

    tape_uses = [
        d.quantity
        for d in result.proposed_material_deltas
        if d.stock_id == "fixture-tape-stock" and d.kind == "consume"
    ]
    assert tape_uses == [80, 80]
    assert 500 - 240 - sum(tape_uses) == 100
    sheet_consumes = [
        d
        for d in result.proposed_material_deltas
        if d.kind == "consume" and d.source_region_id == "spare-region"
    ]
    assert len(sheet_consumes) == 1


@pytest.mark.parametrize(
    ("operation_id", "checkpoint_id"),
    [
        ("stand-inspect-fit", "stand-inspect-fit-check"),
        ("stand-functional-test", "stand-function-check"),
    ],
)
def test_full_build_redirected_final_checkpoint_blocks(operation_id, checkpoint_id):
    base, snapshot, process = full_snapshot()
    checkpoints = tuple(
        c.model_copy(update={"after_operation_id": "stand-inspect-cuts"})
        if c.id == checkpoint_id
        else c
        for c in base.checkpoints
    )
    changed_base = base.model_copy(update={"checkpoints": checkpoints})
    # The redirected record still names a real operation, so this rebuild
    # through the domain schema succeeds; simulation must reject it itself.
    changed = m.ReplannerInput.model_validate(
        snapshot.model_copy(update={"base_plan": changed_base}).model_dump(
            mode="python"
        )
    )
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None
    assert result.cost is None
    assert result.proposed_material_deltas == ()
    assert result.incomplete_operation_ids == ()
    assert any(
        b.code == "invalid_reference" and b.target_ids == (operation_id, checkpoint_id)
        for b in result.blockers
    ), result.blockers
    assert changed.base_plan.checkpoints == checkpoints
    assert changed.events == snapshot.events
    assert changed.evidence == snapshot.evidence


def test_full_build_referenced_final_checkpoint_absent_blocks():
    base, snapshot, process = full_snapshot()
    operations = tuple(
        o.model_copy(
            update={
                "args": o.args.model_copy(
                    update={"checkpoint_id": "stand-inspect-cuts-check"}
                )
            }
        )
        if o.id == "stand-inspect-fit"
        else o
        for o in base.operations
    )
    checkpoints = tuple(
        c for c in base.checkpoints if c.id != "stand-inspect-fit-check"
    )
    evidence = tuple(
        e.model_copy(update={"checkpoint_ids": ("stand-inspect-cuts-check",)})
        if e.id == "synthetic-full-fit-evidence"
        else e
        for e in snapshot.evidence
    )
    changed_base = base.model_copy(
        update={"operations": operations, "checkpoints": checkpoints}
    )
    changed = m.ReplannerInput.model_validate(
        snapshot.model_copy(
            update={"base_plan": changed_base, "evidence": evidence}
        ).model_dump(mode="python")
    )
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None
    assert result.cost is None
    assert result.proposed_material_deltas == ()
    assert result.incomplete_operation_ids == ()
    assert any(
        b.code == "invalid_reference"
        and b.target_ids == ("stand-inspect-fit", "stand-inspect-cuts-check")
        for b in result.blockers
    ), result.blockers
    assert changed.base_plan.checkpoints == checkpoints
    assert changed.events == snapshot.events


def test_fully_completed_build_with_399mm_tape_blocks():
    _base, snapshot, process = full_snapshot(tape_length=399)
    result = simulate(snapshot, process)
    assert result.status == "blocked"
    assert result.plan is None
    assert any(b.code == "stock_exhausted" for b in result.blockers)


def _replay_seven_candidate(tape_value=260, duplicate_peel=False, peel_count=1):
    base, snapshot, process = seven_snapshot()
    result = simulate(snapshot, process)
    assert result.status == "feasible", result.blockers
    candidate = result.plan
    peels = [o for o in candidate.operations if o.type == "detach"]
    peel_events = tuple(
        m.PhysicalEvent(
            id=f"synthetic-seven-replay-{o.id}",
            project_id=candidate.project_id,
            version_id=candidate.version_id,
            operation_id=o.id,
            kind="operation_confirmed",
            evidence_ids=(),
            recorded_at=candidate.created_at,
            actor="user",
            observation="SYNTHETIC user-confirmed peel; no physical build.",
            verification_state="user_confirmed",
        )
        for o in peels[:peel_count]
    )
    if duplicate_peel:
        peel_events += (
            peel_events[0].model_copy(update={"id": "synthetic-seven-replay-dup"}),
        )
    remaining = []
    for stock in candidate.stocks:
        if stock.kind == "sheet" and stock.id != "spare":
            remaining.append(stock.model_copy(update={"usable_regions": ()}))
        elif stock.kind == "tape":
            remaining.append(
                stock.model_copy(
                    update={
                        "remaining_length_mm": stock.remaining_length_mm.model_copy(
                            update={"value": tape_value}
                        )
                    }
                )
            )
        else:
            remaining.append(stock)
    base_part = next(p for p in candidate.parts if p.id == "stand-base")
    replay = m.ReplannerInput(
        base_plan=candidate,
        events=snapshot.events + peel_events,
        evidence=snapshot.evidence,
        material_transactions=(),
        remaining_stock=tuple(remaining),
        patch=m.RepairPatch(
            id="synthetic-seven-replay-noop",
            base_version_id=candidate.version_id,
            kind="resize_part",
            target_id="stand-base",
            replacement_stock_id=None,
            replacement_profile_id=None,
            width_mm=base_part.geometry.width,
            height_mm=base_part.geometry.height,
            angle_deg=None,
            rationale="SYNTHETIC no-op follow-up after confirmed peel.",
        ),
    )
    before = copy.deepcopy(replay)
    outcome = simulate_patch(
        replay,
        process=process,
        allow_synthetic=True,
        historical_plans=(base,),
        family_validator=stand_continuation_blockers,
    )
    assert replay.model_dump() == before.model_dump()
    return outcome


@pytest.mark.parametrize("peel_count", [1, 2])
def test_seven_candidate_replay_after_peels_has_no_history_blockers(peel_count):
    outcome = _replay_seven_candidate(peel_count=peel_count)
    assert outcome.status == "blocked"
    codes = {b.code for b in outcome.blockers}
    assert codes <= {"unsupported", "no_feasible_repair"}
    assert codes.isdisjoint(
        {"invalid_reference", "stale_version", "stock_exhausted", "invalid_order"}
    )


def test_seven_candidate_replay_wrong_remaining_tape_blocks():
    outcome = _replay_seven_candidate(tape_value=261)
    assert outcome.status == "blocked"
    assert any(b.code == "stock_exhausted" for b in outcome.blockers)


def test_seven_candidate_replay_duplicate_peel_blocks():
    outcome = _replay_seven_candidate(duplicate_peel=True)
    assert outcome.status == "blocked"
    assert any(b.code == "invalid_order" for b in outcome.blockers)


def _replay_full_candidate(tape_value=260, duplicate_peel=False, peel_count=1):
    base, snapshot, process = full_snapshot()
    result = simulate(snapshot, process)
    assert result.status == "feasible", result.blockers
    candidate = result.plan
    peels = [o for o in candidate.operations if o.type == "detach"]
    peel_events = tuple(
        m.PhysicalEvent(
            id=f"synthetic-replay-{o.id}",
            project_id=candidate.project_id,
            version_id=candidate.version_id,
            operation_id=o.id,
            kind="operation_confirmed",
            evidence_ids=(),
            recorded_at=candidate.created_at,
            actor="user",
            observation="SYNTHETIC user-confirmed peel; no physical build.",
            verification_state="user_confirmed",
        )
        for o in peels[:peel_count]
    )
    if duplicate_peel:
        peel_events += (
            peel_events[0].model_copy(update={"id": "synthetic-replay-dup"}),
        )
    remaining = []
    for stock in candidate.stocks:
        if stock.kind == "sheet" and stock.id != "spare":
            remaining.append(stock.model_copy(update={"usable_regions": ()}))
        elif stock.kind == "tape":
            remaining.append(
                stock.model_copy(
                    update={
                        "remaining_length_mm": stock.remaining_length_mm.model_copy(
                            update={"value": tape_value}
                        )
                    }
                )
            )
        else:
            remaining.append(stock)
    base_part = next(p for p in candidate.parts if p.id == "stand-base")
    replay = m.ReplannerInput(
        base_plan=candidate,
        events=snapshot.events + peel_events,
        evidence=snapshot.evidence,
        material_transactions=(),
        remaining_stock=tuple(remaining),
        patch=m.RepairPatch(
            id="synthetic-replay-noop",
            base_version_id=candidate.version_id,
            kind="resize_part",
            target_id="stand-base",
            replacement_stock_id=None,
            replacement_profile_id=None,
            width_mm=base_part.geometry.width,
            height_mm=base_part.geometry.height,
            angle_deg=None,
            rationale="SYNTHETIC no-op follow-up after confirmed peel.",
        ),
    )
    before = copy.deepcopy(replay)
    outcome = simulate_patch(
        replay,
        process=process,
        allow_synthetic=True,
        historical_plans=(base,),
        family_validator=stand_continuation_blockers,
    )
    assert replay.model_dump() == before.model_dump()
    return outcome


@pytest.mark.parametrize("peel_count", [1, 2])
def test_full_candidate_replay_after_first_peel_has_no_history_blockers(peel_count):
    outcome = _replay_full_candidate(peel_count=peel_count)
    assert outcome.status == "blocked"
    codes = {b.code for b in outcome.blockers}
    assert codes <= {"unsupported", "no_feasible_repair"}
    assert codes.isdisjoint(
        {"invalid_reference", "stale_version", "stock_exhausted", "invalid_order"}
    )


def test_full_candidate_replay_wrong_remaining_tape_blocks():
    outcome = _replay_full_candidate(tape_value=261)
    assert outcome.status == "blocked"
    assert any(b.code == "stock_exhausted" for b in outcome.blockers)


def test_full_candidate_replay_duplicate_peel_blocks():
    outcome = _replay_full_candidate(duplicate_peel=True)
    assert outcome.status == "blocked"
    assert any(b.code == "invalid_order" for b in outcome.blockers)


@pytest.mark.parametrize("invalid", ["unknown-target"])
def test_invalid_scope_blocks(invalid):
    _base, snapshot, process = attached_snapshot()
    changed = snapshot.model_copy(
        update={"patch": snapshot.patch.model_copy(update={"target_id": invalid})}
    )
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None
