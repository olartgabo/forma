"""SYNTHETIC fabrication-report fixtures only; no physical build was performed."""

import copy
from datetime import UTC, datetime, timedelta

import pytest
from forma_compiler import CutProcess
from forma_fabrication import fabrication_report
from forma_renderer import StandParameters, compile_stand, stand_continuation_blockers
from forma_replanner import simulate_patch

from forma_domain import models as m
from forma_domain.fabrication_contracts import FabricationInput, VersionHistory

NOW = datetime(2026, 10, 30, tzinfo=UTC)
TOOLS = ("Scissors", "metal ruler")


def measured(value, unit="mm"):
    return m.Measurement(value=value, unit=unit, source="calculated", confirmed=True)


def stand():
    unknown = m.Measurement(value=None, unit="mm", source="unknown", confirmed=False)
    evidence = tuple(
        m.Evidence(
            id=name,
            project_id="fixture-project",
            version_id="fixture-v1",
            kind="measurement",
            provenance="synthetic_fixture",
            recorded_at=NOW,
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
                id="fixture-region", geometry=m.Rect(x=0, y=0, width=200, height=550)
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
    request = m.CompilerInput(
        project_id="fixture-project",
        version_id="fixture-v1",
        created_at=NOW,
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
        constraints=m.Constraints(
            device_mass_g=measured(180, "g"),
            support_angle_deg=measured(60, "deg"),
            max_footprint_width_mm=measured(120),
            max_footprint_height_mm=measured(180),
            allowed_profile_ids=tuple(p.id for p in profiles),
        ),
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


def confirmed(plan, op_ids, *, start=0):
    return tuple(
        m.PhysicalEvent(
            id=f"event-{plan.version_id}-{start + index}",
            project_id=plan.project_id,
            version_id=plan.version_id,
            operation_id=op_id,
            kind="operation_confirmed",
            recorded_at=NOW + timedelta(minutes=start + index),
            actor="user",
            observation="SYNTHETIC user-confirmed operation; no physical build.",
            verification_state="user_confirmed",
        )
        for index, op_id in enumerate(op_ids)
    )


def report(plan, process, events=(), *, tools=TOOLS, remaining=None, lineage=None):
    data = FabricationInput(
        project_id=plan.project_id,
        inventory_revision_id="inventory-fixture",
        lineage=lineage or (VersionHistory(plan=plan, events=events),),
        remaining_stock=plan.stocks if remaining is None else remaining,
        declared_tools=tools,
    )
    before = copy.deepcopy(data)
    result = fabrication_report(data, process=process, allow_synthetic=True)
    assert data == before
    return result


def by_id(result):
    return {o.operation_id: o for o in result.operations}


def codes(readiness):
    return {b.code for b in readiness.blockers}


def reorder(plan, order, depends_on):
    """The stand with chosen list order and dependencies; geometry unchanged."""
    ops = {o.id: o for o in plan.operations}
    return plan.model_copy(
        update={
            "operations": tuple(
                ops[op_id].model_copy(
                    update={"depends_on": depends_on.get(op_id, ops[op_id].depends_on)}
                )
                for op_id in order
            )
        }
    )


FRONT_FIRST = (
    "stand-cut-panels",
    "stand-inspect-cuts",
    "stand-joint-front-attach",
    "stand-fold-lip",
    "stand-joint-rear-attach",
    "stand-joint-apex-attach",
    "stand-inspect-fit",
    "stand-functional-test",
)


def front_first(plan, fold_after_join=False):
    """List the front join before the lip fold on the support it covers."""
    deps = {
        "stand-joint-front-attach": ("stand-inspect-cuts",),
        "stand-fold-lip": ("stand-joint-front-attach",)
        if fold_after_join
        else ("stand-inspect-cuts",),
        "stand-joint-rear-attach": ("stand-joint-front-attach", "stand-fold-lip"),
    }
    changed = reorder(plan, FRONT_FIRST, deps)
    return m.BuildPlan.model_validate_json(changed.model_dump_json())


def test_fresh_stand_starts_with_the_cut_and_lists_the_plan_order():
    plan, process = stand()
    result = report(plan, process)
    assert result.status == "ready"
    assert result.next_operation_id == "stand-cut-panels"
    assert [s.operation_id for s in result.supported_order] == [
        o.id for o in plan.operations
    ]
    assert result.order_status == "complete"
    assert not any(s.reordered for s in result.supported_order)
    cut = by_id(result)["stand-cut-panels"]
    assert cut.status == "ready"
    assert {t.tool: t.declared_name for t in cut.tools} == {
        "cutting_tool": "Scissors",
        "ruler": "metal ruler",
    }
    assert any("cannot be undone" in c for c in cut.required_confirmations)
    # The transition from the current state matches the first scheduled step.
    assert cut.next_state_id == result.supported_order[0].state_id
    assert by_id(result)["stand-fold-lip"].status == "waiting"
    assert by_id(result)["stand-fold-lip"].waiting_on_operation_ids == (
        "stand-inspect-cuts",
    )
    assert result.access_basis == "declared_rules"
    assert result.observed_usability == "not_assessed"


def test_report_is_deterministic_and_binds_its_inputs():
    plan, process = stand()
    events = confirmed(plan, ("stand-cut-panels",))
    first = report(plan, process, events)
    assert first == report(plan, process, events)
    assert first.snapshot.last_event_id == events[-1].id
    assert first.snapshot.rules_version == "fabrication-rules-v1"
    later = report(
        plan, process, confirmed(plan, ("stand-cut-panels", "stand-inspect-cuts"))
    )
    assert later.snapshot.history_sha256 != first.snapshot.history_sha256
    assert later.current_state_id != first.current_state_id
    assert later.snapshot.plan_sha256 == first.snapshot.plan_sha256
    assert by_id(first)["stand-cut-panels"].completed_in_version_id == plan.version_id


@pytest.mark.parametrize(
    ("tools", "tool_status", "wording"),
    [
        (None, "unknown", "No tools were saved"),
        (
            ("metal ruler",),
            "not_declared",
            "None of your saved tools is a cutting tool",
        ),
    ],
)
def test_missing_tools_are_named_assumptions_to_confirm(tools, tool_status, wording):
    plan, process = stand()
    result = report(plan, process, tools=tools)
    cut = by_id(result)["stand-cut-panels"]
    # Saved tools are fixed while a plan is active, so a gap is something the
    # builder confirms at the step rather than a blocker they cannot clear.
    assert cut.status == "ready"
    assert {t.tool: t.status for t in cut.tools}["cutting_tool"] == tool_status
    assert any(wording in c for c in cut.required_confirmations)
    assert result.next_operation_id == "stand-cut-panels"


def test_tool_names_match_whole_words_only():
    plan, process = stand()
    cut = by_id(report(plan, process, tools=("rulers notebook", "penknife")))[
        "stand-cut-panels"
    ]
    assert {t.status for t in cut.tools} == {"not_declared"}
    assert all(t.declared_name is None for t in cut.tools)


def test_supported_reordered_sequence_folds_before_the_join():
    plan, process = stand()
    variant = front_first(plan)
    after_inspect = confirmed(variant, ("stand-cut-panels", "stand-inspect-cuts"))
    result = report(variant, process, after_inspect)
    order = [s.operation_id for s in result.supported_order]
    assert order[:2] == ["stand-fold-lip", "stand-joint-front-attach"]
    assert result.supported_order[1].reordered is True
    assert result.order_status == "complete"
    ops = by_id(result)
    assert ops["stand-fold-lip"].status == "ready"
    front = ops["stand-joint-front-attach"]
    assert front.status == "blocked"
    assert any("Do stand-fold-lip first" in b.message for b in front.blockers)
    assert result.next_operation_id == "stand-fold-lip"


def test_post_join_preparation_is_inaccessible():
    plan, process = stand()
    variant = front_first(plan)
    events = confirmed(
        variant,
        ("stand-cut-panels", "stand-inspect-cuts", "stand-joint-front-attach"),
    )
    result = report(variant, process, events)
    assert result.attached_joint_ids == ("stand-joint-front",)
    fold = by_id(result)["stand-fold-lip"]
    assert fold.status == "blocked"
    assert any(
        b.code == "invalid_order" and "stand-joint-front" in b.target_ids
        for b in fold.blockers
    )
    assert result.order_status == "blocked"
    assert result.next_operation_id is None
    # Completed work stays put; the report never reorders it.
    assert all(
        s.operation_id not in {e.operation_id for e in events}
        for s in result.supported_order
    )


def test_dependency_and_access_cycle_is_reported():
    plan, process = stand()
    variant = front_first(plan, fold_after_join=True)
    result = report(variant, process, confirmed(variant, ("stand-cut-panels",)))
    assert result.order_status == "cycle"
    # Only the two steps that wait on each other, not the steps after them.
    assert result.order_blockers[0].target_ids == (
        "stand-joint-front-attach",
        "stand-fold-lip",
    )
    assert [s.operation_id for s in result.supported_order] == ["stand-inspect-cuts"]
    ops = by_id(result)
    assert ops["stand-joint-front-attach"].status == "blocked"
    assert "stand-joint-front-attach" in ops["stand-fold-lip"].waiting_on_operation_ids


def test_unknown_joint_access_blocks():
    plan, process = stand()
    unknown = plan.model_copy(
        update={
            "joints": tuple(
                j.model_copy(update={"confirmed_accessible": None})
                if j.id == "stand-joint-front"
                else j
                for j in plan.joints
            )
        }
    )
    unknown = m.BuildPlan.model_validate_json(unknown.model_dump_json())
    events = confirmed(
        unknown, ("stand-cut-panels", "stand-inspect-cuts", "stand-fold-lip")
    )
    result = report(unknown, process, events)
    front = by_id(result)["stand-joint-front-attach"]
    assert front.status == "blocked"
    assert any(
        "Access to stand-joint-front is unknown" in b.message for b in front.blockers
    )
    # The compiler's own access check is reported verbatim, not re-derived.
    assert any(b.message == "Confirm actual joint access." for b in result.blockers)
    assert result.status == "blocked"


def test_compiler_rejection_is_passed_through_unchanged():
    plan, process = stand()
    data = FabricationInput(
        project_id=plan.project_id,
        inventory_revision_id="inventory-fixture",
        lineage=(VersionHistory(plan=plan),),
        remaining_stock=plan.stocks,
        declared_tools=TOOLS,
    )
    # Synthetic process evidence without opt-in fails the existing compiler.
    result = fabrication_report(data, process=process)
    assert any(b.code == "unsupported_profile" for b in result.blockers)
    assert result.status == "blocked"
    assert result.supported_order == ()
    assert all(o.status != "ready" for o in result.operations)


def test_material_shortfall_and_calculated_balance():
    plan, process = stand()
    events = confirmed(
        plan, ("stand-cut-panels", "stand-inspect-cuts", "stand-fold-lip")
    )

    def tape_left(value, confirmed_length):
        return tuple(
            s.model_copy(
                update={
                    "remaining_length_mm": m.Measurement(
                        value=value,
                        unit="mm",
                        source="calculated" if not confirmed_length else "user_ruler",
                        confirmed=confirmed_length,
                    )
                }
            )
            if s.kind == "tape"
            else s.model_copy(update={"usable_regions": ()})
            for s in plan.stocks
        )

    short = by_id(report(plan, process, events, remaining=tape_left(40, True)))
    assert codes(short["stand-joint-front-attach"]) == {"stock_exhausted"}
    calculated = by_id(report(plan, process, events, remaining=tape_left(300, False)))
    front = calculated["stand-joint-front-attach"]
    assert front.status == "ready"
    assert any("calculated, not measured" in c for c in front.required_confirmations)
    # The already-cut region is gone from the ledger, so a cut cannot repeat.
    fresh = by_id(report(plan, process, remaining=tape_left(500, True)))
    assert codes(fresh["stand-cut-panels"]) == {"stock_exhausted"}


def test_failed_check_and_damage_pause_the_build():
    plan, process = stand()
    done = confirmed(plan, [o.id for o in plan.operations[:6]])
    evidence = m.Evidence(
        id="damage-evidence",
        project_id=plan.project_id,
        version_id=plan.version_id,
        kind="user_report",
        provenance="user",
        part_ids=("stand-brace",),
        recorded_at=NOW + timedelta(hours=1),
        description="SYNTHETIC torn brace",
        verification_state="user_confirmed",
    )
    damage = m.PhysicalEvent(
        id="damage-event",
        project_id=plan.project_id,
        version_id=plan.version_id,
        operation_id="stand-inspect-fit",
        kind="damage",
        evidence_ids=(evidence.id,),
        recorded_at=NOW + timedelta(hours=1),
        actor="user",
        observation="SYNTHETIC torn brace",
        verification_state="user_confirmed",
    )
    result = fabrication_report(
        FabricationInput(
            project_id=plan.project_id,
            inventory_revision_id="inventory-fixture",
            lineage=(
                VersionHistory(
                    plan=plan, events=done + (damage,), evidence=(evidence,)
                ),
            ),
            remaining_stock=plan.stocks,
            declared_tools=TOOLS,
        ),
        process=process,
        allow_synthetic=True,
    )
    assert result.damaged_part_ids == ("stand-brace",)
    assert result.failed_operation_ids == ("stand-inspect-fit",)
    assert result.status == "blocked"
    fit = by_id(result)["stand-inspect-fit"]
    assert any("stand-brace was reported damaged" in b.message for b in fit.blockers)


def repaired_lineage(peeled=()):
    plan, process = stand()
    spare = next(s for s in plan.stocks if s.kind == "sheet").model_copy(
        update={
            "id": "spare",
            "usable_regions": (
                m.Region(
                    id="spare-region", geometry=m.Rect(x=0, y=0, width=200, height=550)
                ),
            ),
        }
    )
    base = plan.model_copy(update={"stocks": plan.stocks + (spare,)})
    base_events = confirmed(base, [o.id for o in base.operations[:6]])
    remaining = tuple(
        s.model_copy(update={"usable_regions": ()})
        if s.id == "fixture-sheet"
        else s.model_copy(
            update={
                "remaining_length_mm": s.remaining_length_mm.model_copy(
                    update={"value": 260}
                )
            }
        )
        if s.kind == "tape"
        else s
        for s in base.stocks
    )
    result = simulate_patch(
        m.ReplannerInput(
            base_plan=base,
            events=base_events,
            evidence=(),
            material_transactions=(),
            remaining_stock=remaining,
            patch=m.RepairPatch(
                id="replace-brace",
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
        ),
        process=process,
        allow_synthetic=True,
        family_validator=stand_continuation_blockers,
    )
    assert result.status == "feasible", result.blockers
    revised = result.plan
    incomplete = set(result.incomplete_operation_ids)
    carried = tuple(o.id for o in revised.operations if o.id not in incomplete)
    peels = [o.id for o in revised.operations if o.type == "detach"]
    lineage = (
        VersionHistory(plan=base, events=base_events),
        VersionHistory(
            plan=revised,
            events=confirmed(revised, peels[: len(peeled)], start=100),
            carried_operation_ids=carried,
            base_last_event_id=base_events[-1].id,
        ),
    )
    return revised, process, lineage, remaining, peels


def test_detach_state_comes_from_replayed_peels_not_completed_ids():
    revised, process, lineage, remaining, peels = repaired_lineage()
    result = report(revised, process, lineage=lineage, remaining=remaining)
    assert result.attached_joint_ids == (
        "stand-joint-apex",
        "stand-joint-front",
        "stand-joint-rear",
    )
    assert result.next_operation_id == peels[0]
    peel = by_id(result)[peels[0]]
    assert peel.status == "ready"
    # The plan's own peel checks pass through unchanged.
    assert peel.required_confirmations == next(
        o.preconditions.human_checks for o in revised.operations if o.id == peels[0]
    )
    carried_attach = by_id(result)["stand-joint-rear-attach"]
    assert carried_attach.status == "completed"
    assert carried_attach.completed_in_version_id == lineage[0].plan.version_id

    revised, process, lineage, remaining, peels = repaired_lineage(peeled=peels)
    after = report(revised, process, lineage=lineage, remaining=remaining)
    # The rear and apex attaches remain completed work, yet their joints are off.
    assert by_id(after)["stand-joint-rear-attach"].status == "completed"
    assert after.attached_joint_ids == ("stand-joint-front",)
    assert after.next_operation_id == "replacement_cut_" + peels[0].split("_")[2]
    assert after.order_status == "complete"


@pytest.mark.parametrize("problem", ["carried", "boundary", "early", "twice"])
def test_history_conflicts_block_everything(problem):
    revised, process, lineage, remaining, peels = repaired_lineage()
    base, current = lineage
    if problem == "carried":
        current = current.model_copy(
            update={
                "carried_operation_ids": current.carried_operation_ids + (peels[0],)
            }
        )
    elif problem == "boundary":
        current = current.model_copy(update={"base_last_event_id": base.events[0].id})
    elif problem == "early":
        current = current.model_copy(
            update={"events": confirmed(revised, (peels[1],), start=100)}
        )
    else:
        # The second report of the same peel would detach a joint already off.
        current = current.model_copy(
            update={"events": confirmed(revised, (peels[0], peels[0]), start=100)}
        )
    result = report(revised, process, lineage=(base, current), remaining=remaining)
    assert result.status == "history_conflict"
    assert result.blockers
    assert result.next_operation_id is None
    assert result.supported_order == ()
    assert all(
        o.status in ("completed", "blocked", "waiting") for o in result.operations
    )


def test_complete_build_has_nothing_left():
    plan, process = stand()
    result = report(plan, process, confirmed(plan, [o.id for o in plan.operations]))
    assert result.status == "complete"
    assert result.next_operation_id is None
    assert result.supported_order == ()
    assert result.order_status == "complete"
