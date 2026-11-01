"""Synthetic software fixtures only, not physical evidence."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from forma_compiler import CutProcess
from forma_renderer import StandParameters, compile_stand, render_manual
from forma_replanner import rank_feasible, simulate_patch

from forma_domain import models as m


def measured(value, unit="mm"):
    return m.Measurement(value=value, unit=unit, source="calculated", confirmed=True)


def fixture():
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
    width, height, angle, depth, stock_width, stock_height = (
        80,
        150,
        60,
        140,
        200,
        550,
    )
    sheet = m.Stock(
        id="fixture-sheet",
        kind="sheet",
        material="cardboard",
        condition="usable",
        width_mm=measured(stock_width),
        height_mm=measured(stock_height),
        thickness_mm=measured(2),
        remaining_length_mm=unknown,
        usable_regions=(
            m.Region(
                id="fixture-region",
                geometry=m.Rect(x=0, y=0, width=stock_width, height=stock_height),
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
        remaining_length_mm=measured(500),
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
        support_angle_deg=measured(angle, "deg"),
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
            support_angle_deg=angle,
            part_width_mm=width,
            part_height_mm=height,
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
        footprint_depth_mm=measured(depth),
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
        test_pass_criteria=("No slip or tip", "Three insertion/removal cycles"),
        profile_evidence=evidence[1:],
    )
    process = CutProcess(kerf_min_mm=2, edge_margin_min_mm=4, evidence=(evidence[0],))
    return request, parameters, process


def compile_and_render():
    request, parameters, process = fixture()
    compiled = compile_stand(request, parameters, process=process, allow_synthetic=True)
    assert compiled.status == "accepted", compiled.blockers
    manual = render_manual(
        compiled.plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
    )
    assert manual.status == "accepted", manual.blockers
    assert len(manual.panels) == len(compiled.plan.operations)
    return compiled.plan, parameters, process, manual


def resize_patch(plan):
    # resize_part is used because change_angle is unconditionally unsupported.
    target = plan.parts[0]
    return m.RepairPatch(
        id="synthetic-resize",
        base_version_id=plan.version_id,
        kind="resize_part",
        target_id=target.id,
        replacement_stock_id=None,
        replacement_profile_id=None,
        width_mm=target.geometry.width - 5,
        height_mm=target.geometry.height,
        angle_deg=None,
        rationale="SYNTHETIC fixture resize only",
    )


def base_extension_patch(plan):
    # The one supported stand resize: extend stand-base depth at its
    # current width (80 x 140 -> 80 x 150 in this fixture).
    return m.RepairPatch(
        id="synthetic-base-extension",
        base_version_id=plan.version_id,
        kind="resize_part",
        target_id="stand-base",
        replacement_stock_id=None,
        replacement_profile_id=None,
        width_mm=80,
        height_mm=150,
        angle_deg=None,
        rationale="SYNTHETIC supported base extension only",
    )


def base_input(plan, patch):
    return m.ReplannerInput(
        base_plan=plan,
        events=(),
        evidence=(),
        material_transactions=(),
        remaining_stock=tuple(s.model_copy(deep=True) for s in plan.stocks),
        patch=patch,
    )


def test_stand_pipeline_future_support_resize_is_unsupported():
    plan, _, process = compile_and_render()[:3]
    patch = resize_patch(plan)
    snapshot = base_input(plan, patch)
    before = deepcopy(plan.model_dump(mode="python"))
    result = simulate_patch(snapshot, process=process, allow_synthetic=True)
    # Only extending stand-base is supported; resizing stand-support is not.
    assert result.status == "blocked"
    assert result.plan is None
    assert result.cost is None
    assert rank_feasible((result,)) == ()
    assert [(b.code, b.message, b.target_ids) for b in result.blockers] == [
        (
            "unsupported",
            "Stand resize only supports extending stand-base; other stand parts cannot be resized.",
            (patch.target_id,),
        )
    ]
    assert plan.model_dump(mode="python") == before


def confirmed_tape_input(plan):
    idx = next(i for i, o in enumerate(plan.operations) if o.type == "tape_joint")
    prefix = plan.operations[: idx + 1]
    base = datetime(2026, 10, 31, tzinfo=UTC)
    user_evidence = m.Evidence(
        id="synthetic-user-evidence",
        project_id=plan.project_id,
        version_id=plan.version_id,
        kind="user_report",
        provenance="user",
        recorded_at=base,
        description="SYNTHETIC user confirmation only",
        verification_state="user_confirmed",
    )
    events = tuple(
        m.PhysicalEvent(
            id=f"synthetic-confirm-{o.id}",
            project_id=plan.project_id,
            version_id=plan.version_id,
            operation_id=o.id,
            kind="operation_confirmed",
            evidence_ids=(user_evidence.id,),
            recorded_at=base + timedelta(minutes=i + 1),
            actor="user",
            observation="SYNTHETIC confirmation only",
            verification_state="user_confirmed",
        )
        for i, o in enumerate(prefix)
    )
    stocks = {s.id: s.model_copy(deep=True) for s in plan.stocks}
    for op in prefix:
        if op.type == "cut_rect":
            stock = stocks[op.args.stock_id]
            kept = tuple(
                r for r in stock.usable_regions if r.id != op.args.source_region_id
            )
            kept += tuple(op.effects.created_offcuts)
            stocks[stock.id] = stock.model_copy(update={"usable_regions": kept})
        elif op.type in ("tape_joint", "tie_joint"):
            stock = stocks[op.args.stock_id]
            value = stock.remaining_length_mm.value - op.args.length_mm
            measurement = stock.remaining_length_mm.model_copy(update={"value": value})
            stocks[stock.id] = stock.model_copy(
                update={"remaining_length_mm": measurement}
            )
    remaining = tuple(stocks[s.id] for s in plan.stocks)
    return m.ReplannerInput(
        base_plan=plan,
        events=events,
        evidence=(user_evidence,),
        material_transactions=(),
        remaining_stock=remaining,
        patch=resize_patch(plan),
    )


def test_stand_pipeline_completed_support_resize_is_unsupported():
    plan, _, process = compile_and_render()[:3]
    snapshot = confirmed_tape_input(plan)
    result = simulate_patch(snapshot, process=process, allow_synthetic=True)
    assert result.status == "blocked"
    assert result.plan is None
    assert result.cost is None
    assert rank_feasible((result,)) == ()
    # The unsupported target is rejected before any undo reasoning, so this
    # is not evidence that completed work can or cannot be undone.
    assert [(b.code, b.message, b.target_ids) for b in result.blockers] == [
        (
            "unsupported",
            "Stand resize only supports extending stand-base; other stand parts cannot be resized.",
            (snapshot.patch.target_id,),
        )
    ]


def test_stand_pipeline_default_rejects_synthetic():
    plan, _, process = compile_and_render()[:3]
    # Use the supported base extension so the only rejection on the
    # default path is the synthetic process provenance.
    result = simulate_patch(
        base_input(plan, base_extension_patch(plan)), process=process
    )
    assert result.status == "blocked"
    assert result.plan is None
    assert result.cost is None
    assert rank_feasible((result,)) == ()
    assert sorted(b.code for b in result.blockers) == ["unsupported_profile"]
