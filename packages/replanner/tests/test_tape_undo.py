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


def test_dependent_evidence_and_checkpoints_invalidate():
    base, snapshot, process = attached_snapshot()
    evidence = m.Evidence(
        id="synthetic-dependent-evidence",
        project_id=base.project_id,
        version_id=base.version_id,
        kind="user_report",
        provenance="user",
        part_ids=("stand-brace",),
        operation_ids=("stand-inspect-fit",),
        checkpoint_ids=("stand-inspect-fit-check",),
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


@pytest.mark.parametrize("invalid", ["unknown-target"])
def test_invalid_scope_blocks(invalid):
    _base, snapshot, process = attached_snapshot()
    changed = snapshot.model_copy(
        update={"patch": snapshot.patch.model_copy(update={"target_id": invalid})}
    )
    result = simulate(changed, process)
    assert result.status == "blocked"
    assert result.plan is None
