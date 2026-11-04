"""Offline search checks on SYNTHETIC inputs; no physical result follows."""

import math
from itertools import count

from forma_synthesizer import candidate_id, domain_values, domains_for, probe, search
from synthetic_inputs import measurement_basis, search_input, sheet, tape

from forma_domain.synthesis_contracts import SearchBudget


def checks(report):
    return {c.check_id: c for c in report.checks}


def test_identical_inputs_give_identical_results_and_ids():
    first, second = search(search_input()), search(search_input())
    assert first.model_dump() == second.model_dump()
    assert first.status == "candidates_found" and len(first.candidates) == 2
    other = search(search_input(kerf_mm=3))
    assert other.search_id != first.search_id


def test_candidates_are_named_measured_and_never_pass_unknowns():
    result = search(search_input())
    for report in result.candidates:
        assert report.status == "acceptable"
        assert report.candidate_id == candidate_id(report.design)
        names = [p.piece.display_name for p in report.pieces]
        assert names == ["Support panel", "Base panel", "Rear brace"]
        assert all(p.piece.reference.startswith("P-") for p in report.pieces)
        assert report.material.part_area_mm2 > 0
        assert report.material.tape_length_mm == 3 * report.design.part_width_mm
        assert report.construction and report.cut_layout_svg
        rows = checks(report)
        assert rows["compiler"].status == "modeled_pass"
        assert rows["fabrication-access"].status == "unverified"
        for case in ("portrait", "landscape"):
            assert rows[f"stability-tip-{case}"].status == "missing_input"
            assert rows[f"retention-{case}"].status == "unsupported"
        assert rows["joint-strength"].status == "unsupported"
        assert len(report.unresolved) == sum(
            1 for c in report.checks if c.status != "modeled_pass"
        )
    assert result.physical_verification == "not_attempted"


def test_measurements_from_another_geometry_do_not_transfer():
    result = search(search_input(measurements=(measurement_basis(),)))
    for report in result.candidates:
        rows = checks(report)
        assert rows["stability-tip-portrait"].status == "evidence_incompatible"
        assert "stability-measurement-1" in rows["stability-tip-portrait"].detail


def test_sheet_too_small_is_infeasible_with_named_limit():
    result = search(search_input(stocks=(sheet("small-sheet", 60, 550), tape())))
    assert result.status == "infeasible" and not result.candidates
    assert result.nodes_total == 0
    assert any("small-sheet is too small" in b.message for b in result.blockers)


def test_insufficient_tape_is_infeasible_not_exhausted():
    data = search_input(stocks=(sheet("synthetic-sheet", 200, 550), tape(length=100)))
    result = search(data)
    assert result.status == "infeasible" and result.exhausted is None
    assert result.nodes_evaluated == result.nodes_total > 0
    assert {r.code for r in result.rejections} >= {"stock_exhausted"}


def test_budget_exhaustion_is_reported_separately():
    data = search_input(stocks=(sheet("synthetic-sheet", 200, 550), tape(length=100)))
    result = search(data, SearchBudget(max_nodes=5))
    assert result.status == "search_exhausted" and result.exhausted == "node_budget"
    assert result.nodes_evaluated == 5 < result.nodes_total
    partial = search(search_input(), SearchBudget(max_nodes=3))
    assert partial.status == "candidates_found" and partial.exhausted == "node_budget"
    ticks = count(0, 10)
    timed = search(
        search_input(), SearchBudget(max_seconds=1), clock=lambda: next(ticks)
    )
    assert timed.status == "search_exhausted" and timed.exhausted == "time_budget"
    assert timed.nodes_evaluated == 0


def test_unknown_stock_needs_measurement_and_is_never_substituted():
    result = search(search_input(stocks=(sheet("unmeasured", None, None), tape())))
    assert result.status == "needs_input" and result.nodes_total == 0
    assert any(
        b.code == "missing_measurement" and b.target_ids == ("unmeasured",)
        for b in result.blockers
    )
    missing_process = search(search_input(process=None))
    assert missing_process.status == "needs_input"


def test_active_build_never_gets_fresh_candidates():
    data = search_input()
    active = search_input(
        identity=data.identity.model_copy(update={"active_version_id": "version-1"})
    )
    result = search(active)
    assert result.status == "active_build" and not result.candidates


def test_missing_tools_stay_unresolved_not_failed():
    result = search(search_input(tools=None))
    assert result.status == "candidates_found"
    rows = checks(result.candidates[0])
    assert rows["fabrication-order"].status == "missing_input"


def test_probe_regenerates_dependent_brace_and_geometry():
    data = search_input()
    base = search(data).candidates[0]
    depths = domain_values(domains_for(data, data.stocks[0])[2])
    new_depth = next(d for d in depths if d != base.design.footprint_depth_mm)
    result = probe(data, SearchBudget(), base.design, "footprint_depth_mm", new_depth)
    assert result.status == "evaluated" and result.report.status == "acceptable"
    assert set(result.changed_piece_ids) == {"stand-base", "stand-brace"}
    brace = next(p for p in result.report.pieces if p.piece.part_id == "stand-brace")
    angle = math.radians(base.design.support_angle_deg)
    support = base.design.support_length_mm
    expected = math.hypot(
        new_depth - support * math.cos(angle), support * math.sin(angle)
    )
    assert math.isclose(brace.height_mm, expected) and brace.dependent
    assert result.report.canonical_geometry_hash != base.canonical_geometry_hash
    assert result.previous_value_mm == base.design.footprint_depth_mm


def test_probe_rejects_off_domain_values_and_fixed_inputs():
    data = search_input()
    base = search(data).candidates[0]
    budget = SearchBudget()
    assert (
        probe(data, budget, base.design, "part_width_mm", 71.3).status
        == "outside_domain"
    )
    lip = base.design.model_copy(update={"lip_mm": 30.0})
    assert probe(data, budget, lip, "part_width_mm", 70.0).status == "outside_domain"
    angle = base.design.model_copy(update={"support_angle_deg": 45.0})
    assert probe(data, budget, angle, "part_width_mm", 70.0).status == "outside_domain"
    foreign = base.design.model_copy(update={"sheet_stock_id": "missing-sheet"})
    assert (
        probe(data, budget, foreign, "part_width_mm", 70.0).status == "outside_domain"
    )


def test_probe_to_a_hard_failure_reports_rejection_not_acceptance():
    data = search_input()
    base = search(data).candidates[0]
    supports = domain_values(domains_for(data, data.stocks[0])[1])
    result = probe(data, SearchBudget(), base.design, "support_length_mm", supports[-1])
    assert result.status == "evaluated"
    assert result.report.status == "rejected"
    assert any(c.status == "modeled_failure" for c in result.report.checks)
    assert result.report.blockers


def test_search_inputs_are_not_mutated():
    data = search_input()
    before = [s.model_dump() for s in data.stocks]
    search(data)
    assert [s.model_dump() for s in data.stocks] == before


def test_unconfirmed_tools_or_access_need_input_not_infeasible():
    data = search_input()
    for field in ("tools_confirmed", "joint_access_confirmed"):
        unconfirmed = search_input(
            parameters=data.parameters.model_copy(update={field: False})
        )
        result = search(unconfirmed)
        assert result.status == "needs_input", field
        assert any(b.code == "needs_confirmation" for b in result.blockers)


def test_compiler_input_rejections_are_needs_input_not_infeasible():
    # Sheet thickness outside the reviewed profile range: the compiler asks for
    # a supported profile on every node, which says nothing about stock size.
    thick = search_input(stocks=(sheet("thick-sheet", 200, 550, thickness=5), tape()))
    result = search(thick)
    assert result.status == "needs_input" and not result.candidates
    assert result.nodes_evaluated == result.nodes_total > 0
    assert any(b.code == "unsupported_profile" for b in result.blockers)


def test_out_of_family_angle_is_an_explicit_blocker_not_an_error():
    from synthetic_inputs import constraints

    data = search_input(constraints=constraints(angle=90))
    result = search(data)
    assert result.status == "needs_input"
    assert any(
        b.code == "unsupported" and "90 degree" in b.message for b in result.blockers
    )
    base = search(search_input()).candidates[0]
    probed = probe(data, SearchBudget(), base.design, "part_width_mm", 70.0)
    assert probed.status == "unsupported" and probed.blockers


def test_candidates_are_generated_lazily_within_the_budget(monkeypatch):
    import sys

    module = sys.modules["forma_synthesizer.search"]

    built = []

    class Counting(module.StandDesign):
        def __init__(self, **values):
            built.append(1)
            super().__init__(**values)

    monkeypatch.setattr(module, "StandDesign", Counting)
    result = search(search_input(), SearchBudget(max_nodes=1))
    assert result.nodes_evaluated == 1 and result.nodes_total == 64
    assert len(built) <= 2


def test_final_evaluation_is_inside_the_time_budget():
    calls = count()
    # Generous for preparation and every node, then late for finalists.
    timed = search(
        search_input(),
        SearchBudget(max_seconds=1),
        clock=lambda: 0 if next(calls) < 65 else 100,
    )
    assert timed.nodes_evaluated == timed.nodes_total == 64
    assert timed.status == "search_exhausted" and timed.exhausted == "time_budget"
