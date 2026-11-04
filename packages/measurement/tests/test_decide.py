"""Offline decision rules on SYNTHETIC inputs; no physical result follows."""

from dataclasses import replace

from forma_measurement import (
    ActiveFacts,
    CaseMargin,
    active_decision,
    compare,
    design_decision,
    thresholds,
)
from forma_synthesizer import search
from measurement_inputs import constraints, search_input, sheet, strip, tape
from synthetic_inputs import parameters

from forma_domain.synthesis_contracts import SearchBudget


def decide(stocks, declined=frozenset(), **overrides):
    data = search_input(stocks=stocks, **overrides)
    return design_decision(data, search(data), frozenset(declined))


def test_thresholds_come_from_the_compiler():
    limits = thresholds(search_input())
    # 70 mm device + two 4 mm margins; stacked panels, kerfs and margins.
    assert (limits.width_mm, limits.height_mm) == (78, 268.8)
    assert limits.tape_width_mm == 20 and limits.tape_length_mm == 210
    assert limits.thickness_ranges == ((1.0, 3.0),)


def test_a_measurement_crosses_the_supported_threshold():
    unknown = decide((sheet("sheet-a", thickness=2), tape()))
    assert unknown.outcome == "question"
    question = unknown.question
    assert question.target.key == "stock:sheet-a:width_mm"
    assert question.threshold.lower == 78 and question.capture == "inventory"
    assert question.required_precision == 1.0 and question.unit == "mm"
    assert "at least 78 mm" in question.why
    too_narrow = decide((sheet("sheet-a", 77), tape()))
    assert too_narrow.outcome == "no_feasible_candidate"
    wide = decide((sheet("sheet-a", 78), tape()))
    assert wide.question.target.key == "stock:sheet-a:height_mm"
    assert wide.question.threshold.lower == 268.8
    measured = decide((sheet("sheet-a", 120, 300), tape()))
    assert measured.question.target.key == "stock:sheet-a:usable_region"
    usable = decide((sheet("sheet-a", 120, 300, region=True), tape()))
    assert usable.outcome == "physical_test_required"
    assert usable.design.status == "candidates_found"
    change = compare(measured, usable)
    assert change.decision_changed
    assert any("usable_region" in fact for fact in change.changed_facts)
    assert "candidates_found" in change.explanation


def test_irrelevant_measurements_are_never_requested():
    usable = sheet("sheet-a", 120, 300, region=True)
    # Strips are not used by the stand; a usable tape makes other tape moot;
    # a sheet confirmed too narrow cannot be rescued by its height.
    result = decide(
        (
            usable,
            sheet("sheet-narrow", 60),
            strip(),
            tape(),
            tape("tape-unknown", length=None),
        )
    )
    asked = {result.question.target.key} if result.question else set()
    assert not any(
        "strip-1" in k or "tape-unknown" in k or "sheet-narrow" in k for k in asked
    )
    assert result.outcome == "physical_test_required"
    # With no possible tape, sheet questions cannot change anything.
    no_tape = decide((sheet("sheet-b"), tape(length=100)))
    assert no_tape.outcome == "no_feasible_candidate" and no_tape.question is None


def test_identical_inputs_select_identically_and_ties_are_by_stock_id():
    stocks = (sheet("sheet-b"), sheet("sheet-a"), tape())
    first, second = decide(stocks), decide(stocks)
    assert first.model_dump() == second.model_dump()
    assert first.question.target.key == "stock:sheet-a:width_mm"
    assert first.pending_questions == 3


def test_question_identity_changes_with_the_inventory_revision():
    stocks = (sheet("sheet-a"), tape())
    data = search_input(stocks=stocks)
    other = replace(
        data,
        identity=data.identity.model_copy(
            update={"inventory_revision_id": "inventory-2"}
        ),
    )
    a = design_decision(data, search(data))
    b = design_decision(other, search(other))
    assert a.question.target == b.question.target
    assert a.question.question_id != b.question.question_id


def test_unavailable_answers_are_not_asked_again_and_stopping_is_explicit():
    stocks = (sheet("sheet-a"), sheet("sheet-b"), tape())
    first = decide(stocks, {"stock:sheet-a:width_mm"})
    assert first.question.target.stock_id == "sheet-b"
    both = decide(stocks, {"stock:sheet-a:width_mm", "stock:sheet-b:width_mm"})
    assert both.question is None and both.outcome == "no_feasible_candidate"
    assert both.identity.declined_target_keys == (
        "stock:sheet-a:width_mm",
        "stock:sheet-b:width_mm",
    )


def test_photo_estimates_stay_unconfirmed_and_are_still_asked():
    estimate = decide((sheet("sheet-a", 300, 600, confirmed=False), tape()))
    assert estimate.outcome == "question"
    # Every value is an estimate here; thickness is asked first.
    assert estimate.question.target.key == "stock:sheet-a:thickness_mm"
    current = estimate.question.current
    assert current.value == 2 and current.confirmed is False
    assert estimate.pending_questions == 2
    assert current.source == "calculated"
    assert estimate.design.status != "candidates_found"


def test_missing_requirement_is_asked_before_stock():
    from measurement_inputs import UNKNOWN

    data = search_input(stocks=(sheet("sheet-a"), tape()))
    gap = data.constraints.model_copy(
        update={"device_mass_g": UNKNOWN.model_copy(update={"unit": "g"})}
    )
    data = replace(data, constraints=gap)
    decision = design_decision(data, search(data))
    assert decision.question.target.key == "requirement:constraints:device_mass_g"
    assert decision.question.capture == "requirements"


def test_server_context_gaps_are_unsupported_not_questions():
    decision = decide((sheet("sheet-a"), tape()), process=None)
    assert decision.outcome == "unsupported" and decision.question is None
    assert decision.missing_capabilities


def test_out_of_family_requirements_have_no_feasible_candidate():
    decision = decide(
        (sheet("sheet-a"), tape()),
        constraints=constraints(angle=60).model_copy(
            update={
                "max_footprint_width_mm": constraints().max_footprint_width_mm.model_copy(
                    update={"value": 50}
                )
            }
        ),
    )
    assert decision.outcome == "no_feasible_candidate"
    assert "unlimited cardboard stock" in decision.reasons[0]


def test_budget_exhaustion_is_not_a_question():
    data = search_input(
        stocks=(sheet("sheet-a", 120, 300, region=True), tape(length=100))
    )
    result = search(data, SearchBudget(max_nodes=1))
    assert result.status == "search_exhausted"
    assert design_decision(data, result).outcome == "budget_exhausted"


def active(status, stage="reported_assembled", cases=(), band=None, required=None):
    return ActiveFacts(
        data=search_input(),
        plan_version_id="version-1",
        analysis_status=status,
        stage=stage,
        part_ids=("stand-base", "stand-brace", "stand-support"),
        blockers=("SYNTHETIC blocker",),
        cases=cases,
        required_margin_m=required,
        resolution_band_m=band,
    )


def test_built_stand_outcomes():
    unbuilt = active_decision(active("needs_measurement", stage="planned_preview"))
    assert unbuilt.outcome == "physical_test_required"
    built = active_decision(active("needs_measurement"))
    assert built.outcome == "question"
    assert built.question.capture == "stability_measurements"
    assert built.question.affected_case_ids == ("portrait", "landscape")
    assert [p.display_name for p in built.question.target.pieces] == [
        "Base panel",
        "Rear brace",
        "Support panel",
    ]
    declined = active_decision(
        active("needs_measurement"),
        frozenset({"assembled_stand:version-1:assembled_stand"}),
    )
    assert declined.outcome == "physical_test_required"
    assert active_decision(active("unsupported")).outcome == "unsupported"


def test_margins_inside_resolution_are_unsupported_intervals():
    clear = (
        CaseMargin("portrait", "modeled_pass", 0.030),
        CaseMargin("landscape", "modeled_pass", 0.025),
    )
    decided = active_decision(
        active("complete", cases=clear, band=0.002, required=0.005)
    )
    assert decided.outcome == "none_needed"
    assert "not a physical pass" in decided.reasons[-1]
    close = (CaseMargin("portrait", "modeled_pass", 0.006),)
    interval = active_decision(
        active("complete", cases=close, band=0.002, required=0.005)
    )
    assert interval.outcome == "unsupported"
    assert "interval propagation" in interval.missing_capabilities[0]
    missing = (CaseMargin("portrait", "needs_measurement", None),)
    assert (
        active_decision(active("complete", cases=missing, required=0.005)).outcome
        == "unsupported"
    )


def test_comparison_explains_unchanged_decisions():
    before = decide((sheet("sheet-a"), tape()))
    after = decide((sheet("sheet-a", 120), tape()))
    change = compare(before, after)
    assert not change.decision_changed
    assert change.changed_facts == ("stock:sheet-a:width_mm: unknown → 120",)
    assert change.explanation.startswith(
        "The saved values changed, but no supported decision changed"
    )


def test_a_rounded_threshold_never_excludes_stock_the_compiler_accepts():
    # The height threshold is reported in 0.1 mm steps (268.8 mm). A value
    # between whole millimetres is decided by the compiler, not by rounding.
    near = decide((sheet("sheet-a", height=268.9), tape()))
    assert near.outcome == "question"
    assert near.question.target.key == "stock:sheet-a:width_mm"
    usable = decide((sheet("sheet-a", 120, 268.9, region=True), tape()))
    assert usable.design.status == "candidates_found"
    assert usable.outcome == "physical_test_required"
    short = decide((sheet("sheet-a", height=268.7), tape()))
    assert short.outcome == "no_feasible_candidate" and short.question is None


def test_questions_only_cover_materials_with_reviewed_profiles():
    other = sheet("sheet-other").model_copy(update={"material": "other_supported"})
    alone = decide((other, tape()))
    # Dimensions cannot enable a sheet the profiles do not cover.
    assert alone.outcome == "unsupported" and alone.question is None
    assert any("other_supported" in r and "profile" in r for r in alone.reasons)
    assert alone.missing_capabilities
    mixed = decide((other, sheet("sheet-z"), tape()))
    assert mixed.question.target.stock_id == "sheet-z"
    assert any("sheet-other" in r for r in mixed.reasons)


def test_missing_profile_evidence_is_an_input_gap_not_impossibility():
    gap = parameters().model_copy(update={"profile_evidence": ()})
    data = search_input(
        stocks=(sheet("sheet-a", 120, 300, region=True), tape()), parameters=gap
    )
    result = search(data)
    assert result.status == "needs_input"
    decision = design_decision(data, result)
    assert decision.outcome == "unsupported" and decision.question is None
    assert not any("unlimited" in r for r in decision.reasons)


def test_comparisons_cover_every_inventory_fact():
    narrow = tuple(sheet(f"sheet-{i:02d}", 60) for i in range(17))
    before = decide((*narrow, sheet("sheet-zz"), tape()))
    after = decide((*narrow, sheet("sheet-zz", 120), tape()))
    assert before.question.target.key == "stock:sheet-zz:width_mm"
    assert after.question.target.key == "stock:sheet-zz:height_mm"
    assert len(after.facts) == 18 * 4 + 2 + 4
    change = compare(before, after)
    assert change.changed_facts == ("stock:sheet-zz:width_mm: unknown → 120",)
    assert "Height of sheet sheet-zz" in change.explanation
