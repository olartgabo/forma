"""Offline real-replanner integration coverage for ranked repair previews."""

import copy

import pytest
from forma_renderer import stand_continuation_blockers
from forma_replanner import rank_feasible, simulate_patch
from test_compiler_adapter import FakeTransport, batch, patch, setup_case

from forma_api import compiler_adapter as adapter
from forma_api.model_gateway import MetaGateway
from forma_api.proposal_service import CandidateFeedback, ProposalService
from forma_domain import models as m


def ranked_case():
    request, state, kwargs = setup_case()
    tape = next(p for p in state.profiles if p.strategy == "tape")
    extra = tape.model_copy(update={"id": "fixture-alternative-tape"})
    profiles = state.profiles + (extra,)
    constraints = state.constraints.model_copy(
        update={
            "allowed_profile_ids": state.constraints.allowed_profile_ids + (extra.id,),
        }
    )
    plan = state.plan.model_copy(
        update={"joint_profiles": profiles, "constraints": constraints}
    )
    state = state.model_copy(
        update={"profiles": profiles, "constraints": constraints, "plan": plan}
    )
    kwargs["base_plan"] = plan
    replacement = m.RepairPatch(
        id="repair-middle-profile",
        base_version_id=state.version_id,
        kind="replace_joint_profile",
        target_id="stand-joint-front",
        replacement_stock_id=None,
        replacement_profile_id=extra.id,
        width_mm=None,
        height_mm=None,
        angle_deg=None,
        rationale="Synthetic equivalent tested tape profile",
    )
    # Model order intentionally opposes lexical tie breaking for equal-cost resizes.
    candidates = (
        patch(state, id="repair-z-extension"),
        replacement,
        patch(state, id="repair-a-extension"),
    )
    return request, state, kwargs, candidates


def expected_results(state, kwargs, candidates):
    results = tuple(
        simulate_patch(
            m.ReplannerInput(
                base_plan=state.plan,
                patch=candidate,
                events=kwargs["events"],
                evidence=kwargs["evidence"],
                material_transactions=kwargs["material_transactions"],
                remaining_stock=state.stocks,
            ),
            process=kwargs["process"],
            allow_synthetic=True,
            historical_plans=kwargs["historical_plans"],
            family_validator=stand_continuation_blockers,
        )
        for candidate in candidates
    )
    return results, rank_feasible(results)


def test_real_adapter_preserves_and_ranks_complete_repair_results_once(monkeypatch):
    _, state, kwargs, candidates = ranked_case()
    before = copy.deepcopy((state.model_dump(), kwargs))
    raw, expected = expected_results(state, kwargs, candidates)
    assert all(r.status == "feasible" for r in raw), raw
    assert [r.cost.known_weighted_cost for r in raw] == [2, 0, 2]
    assert [r.patch_id for r in expected] == [
        candidates[1].id,
        candidates[2].id,
        candidates[0].id,
    ]
    real_simulator, calls = adapter.simulate_patch, []

    def counted(snapshot, **options):
        calls.append(snapshot.patch.id)
        return real_simulator(snapshot, **options)

    monkeypatch.setattr(adapter, "simulate_patch", counted)
    fake = FakeTransport(state, batch(*candidates))
    outcome = ProposalService(MetaGateway(fake), adapter.build_validator(**kwargs)).run(
        "repair", state, "compare repairs"
    )
    assert outcome.status == "proposed", outcome
    assert calls == [c.id for c in candidates]
    assert [r.model_dump() for r in outcome.repair_results] == [
        r.model_dump() for r in expected
    ]
    assert [c.id for c in outcome.proposal.candidates] == [r.patch_id for r in expected]
    assert [r.candidate_id for r in outcome.reviews] == [c.id for c in candidates]
    for result in outcome.repair_results:
        assert result.cost.estimated_extra_minutes is None
        assert result.cost.material_waste_fraction is None
        assert result.cost.estimated_new_purchase_cost is None
        assert result.cost.complete_estimate is False
    trace = outcome.trace.model_dump_json()
    diff_ids = {
        id
        for r in expected
        for field in (
            "preserved_operation_ids",
            "required_undo_operation_ids",
            "redo_operation_ids",
            "newly_required_operation_ids",
            "changed_part_ids",
            "invalidated_checkpoint_ids",
        )
        for id in getattr(r, field)
    }
    assert diff_ids
    assert all(id not in trace for id in diff_ids)
    assert state.model_dump() == before[0]
    assert kwargs == before[1]


def test_mixed_real_repairs_keep_exact_blocked_review_and_only_rank_feasible():
    _, state, kwargs, candidates = ranked_case()
    candidates = (
        candidates[0],
        patch(state, height=10000, id="repair-blocked"),
        candidates[1],
    )
    raw, expected = expected_results(state, kwargs, candidates)
    assert raw[1].status == "blocked" and raw[1].blockers
    fake = FakeTransport(state, batch(*candidates))
    outcome = ProposalService(MetaGateway(fake), adapter.build_validator(**kwargs)).run(
        "repair", state, "compare repairs"
    )
    assert outcome.status == "proposed"
    assert outcome.reviews[1].feedback.status == "blocked"
    assert outcome.reviews[1].feedback.blockers == raw[1].blockers
    assert [r.model_dump() for r in outcome.repair_results] == [
        r.model_dump() for r in expected
    ]
    assert [c.id for c in outcome.proposal.candidates] == [r.patch_id for r in expected]
    assert "repair-blocked" not in [r.patch_id for r in outcome.repair_results]


@pytest.mark.parametrize(
    "corruption", ["patch", "base", "project", "parent", "same_version"]
)
def test_mismatched_typed_simulation_fails_closed(corruption):
    _, state, kwargs, candidates = ranked_case()
    candidate = candidates[0]
    checked = expected_results(state, kwargs, (candidate,))[0][0]
    if corruption == "patch":
        checked = checked.model_copy(update={"patch_id": "wrong-patch"})
    elif corruption == "base":
        checked = checked.model_copy(update={"base_version_id": "wrong-base"})
    else:
        plan_update = {
            "project": {"project_id": "wrong-project"},
            "parent": {"parent_version_id": "wrong-parent"},
            "same_version": {"version_id": state.version_id},
        }[corruption]
        checked = checked.model_copy(
            update={"plan": checked.plan.model_copy(update=plan_update)}
        )
    fake = FakeTransport(state, batch(candidate))
    outcome = ProposalService(MetaGateway(fake), lambda c, s: checked).run(
        "repair", state, "repair"
    )
    assert outcome.status == "stopped" and outcome.error_code == "compiler_failed"
    assert outcome.proposal is None and outcome.repair_results == ()


def test_accepted_repair_without_simulation_is_rejected():
    _, state, _, candidates = ranked_case()
    fake = FakeTransport(state, batch(candidates[0]))
    outcome = ProposalService(
        MetaGateway(fake),
        lambda c, s: CandidateFeedback(
            status="accepted",
            blockers=(),
        ),
    ).run("repair", state, "repair")
    assert outcome.status == "stopped" and outcome.error_code == "compiler_failed"
    assert outcome.proposal is None and outcome.repair_results == ()


def test_blocked_feedback_remains_supported_for_repair():
    _, state, _, candidates = ranked_case()
    feedback = CandidateFeedback(
        status="blocked",
        blockers=(
            m.Blocker(
                code="missing_measurement",
                message="Measure the available stock first.",
            ),
        ),
    )
    fake = FakeTransport(state, batch(candidates[0]), batch())
    outcome = ProposalService(MetaGateway(fake), lambda c, s: feedback).run(
        "repair", state, "repair"
    )
    assert outcome.status == "blocked" and outcome.repair_results == ()
    assert outcome.reviews[0].feedback == feedback


def test_design_keeps_existing_result_contract():
    request, state, kwargs = setup_case()
    fake = FakeTransport(state, batch(request.candidate))
    outcome = ProposalService(MetaGateway(fake), adapter.build_validator(**kwargs)).run(
        "design", state, "design"
    )
    assert outcome.status == "proposed"
    assert outcome.proposal.candidates == (request.candidate,)
    assert outcome.reviews[0].feedback.status == "accepted"
    assert outcome.repair_results == ()
