"""Synthetic fixture cases loaded from disk, never physical evidence."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from forma_compiler import CutProcess
from forma_replanner import rank_feasible, simulate_patch

from forma_domain.models import Evidence, ReplannerInput

STAMP = "2026-10-30T00:00:00Z"
CASE_DIR = Path(__file__).parent / "cases"
CASE_FILES = ["damaged_slot.json", "impossible_request.json"]


def load_raw(name):
    return json.loads((CASE_DIR / name).read_text())


def load_case(name):
    raw = load_raw(name)
    return raw["input"], raw["process"], raw["expected"]


def make_process(process_dict, project_id, version_id):
    return CutProcess(
        kerf_min_mm=process_dict["kerf_min_mm"],
        edge_margin_min_mm=process_dict["edge_margin_min_mm"],
        evidence=(
            Evidence(
                id="process",
                project_id=project_id,
                version_id=version_id,
                kind="measurement",
                provenance="synthetic_fixture",
                recorded_at=STAMP,
                description="Synthetic limits",
                verification_state="unknown",
            ),
        ),
    )


def run_case(input_dict, process_dict):
    request = ReplannerInput.model_validate(input_dict)
    process = make_process(
        process_dict, request.base_plan.project_id, request.base_plan.version_id
    )
    return request, simulate_patch(request, process=process, allow_synthetic=True)


def unjoined_damage_variant():
    """Feasible derivative of damaged_slot without the completed hinge."""
    input_dict, process_dict, _ = load_case("damaged_slot.json")
    mutated = deepcopy(input_dict)
    mutated["events"] = [
        e for e in mutated["events"] if e.get("operation_id") != "join"
    ]
    for stock in mutated["remaining_stock"]:
        if stock["id"] == "tape":
            stock["remaining_length_mm"] = {
                "value": 100,
                "unit": "mm",
                "source": "user_ruler",
                "confirmed": True,
            }
    return mutated, process_dict


@pytest.mark.parametrize("case_file", CASE_FILES)
def test_fixture_cases(case_file):
    raw = load_raw(case_file)
    assert raw["provenance"] == "synthetic"
    assert "not a measurement" in raw["note"].lower()
    assert "physical result" in raw["note"].lower()
    assert raw["process"]["provenance"] == "synthetic"
    assert "synthetic" in raw["process"]["note"].lower()
    input_dict, process_dict, expected = (
        raw["input"],
        raw["process"],
        raw["expected"],
    )
    request, result = run_case(input_dict, process_dict)
    assert result.status == expected["status"]
    assert expected["blocker_codes"] == sorted(expected["blocker_codes"])
    assert sorted(b.code for b in result.blockers) == expected["blocker_codes"]
    assert tuple(result.preserved_operation_ids) == tuple(
        expected["preserved_operation_ids"]
    )
    if "invalidated_checkpoint_ids" in expected:
        assert tuple(result.invalidated_checkpoint_ids) == tuple(
            expected["invalidated_checkpoint_ids"]
        )
    else:
        assert result.invalidated_checkpoint_ids == ()
    if result.status == "feasible":
        assert result.plan is not None
        assert result.cost is not None
        assert result.blockers == ()
        assert rank_feasible((result,)) == (result,)
    else:
        # BUG?: damaged_slot blocks early with unsupported and empty
        # preservation because the completed lossy tape_joint needs explicit
        # physical undo; recorded as-is from the engine.
        assert result.plan is None
        assert result.cost is None
        assert rank_feasible((result,)) == ()


def test_damaged_slot_mutation_makes_unattached_replacement_feasible():
    input_dict, process_dict, expected = load_case("damaged_slot.json")
    assert expected["status"] == "blocked"
    mutated, _ = unjoined_damage_variant()
    assert mutated != input_dict
    _, result = run_case(mutated, process_dict)
    assert result.status == "feasible"
    assert result.blockers == ()
    assert tuple(result.preserved_operation_ids) == ("cut",)
    assert tuple(result.lost_part_ids) == ("brace",)
    assert tuple(result.lost_operation_ids) == ("cut_brace",)
    assert result.plan is not None
    assert result.cost is not None
    assert rank_feasible((result,)) == (result,)


def test_impossible_request_mutation_exhausts_remaining_stock():
    input_dict, process_dict, expected = load_case("impossible_request.json")
    assert expected["blocker_codes"] == ["geometry_invalid"]
    mutated = deepcopy(input_dict)
    mutated["remaining_stock"][0]["usable_regions"] = []
    _, result = run_case(mutated, process_dict)
    assert result.status == "blocked"
    assert sorted(b.code for b in result.blockers) == ["stock_exhausted"]
    assert "geometry_invalid" not in {b.code for b in result.blockers}
    assert tuple(result.preserved_operation_ids) == ()
    assert tuple(result.preserved_operation_ids) != tuple(
        expected["preserved_operation_ids"]
    )
    assert result.plan is None
    assert result.cost is None
    assert rank_feasible((result,)) == ()


@pytest.mark.parametrize("case_file", CASE_FILES)
def test_default_path_rejects_synthetic_process(case_file):
    """Each real case file run without allow_synthetic stays blocked."""
    raw = load_raw(case_file)
    request = ReplannerInput.model_validate(raw["input"])
    process = make_process(
        raw["process"], request.base_plan.project_id, request.base_plan.version_id
    )
    result = simulate_patch(request, process=process)
    assert result.status == "blocked"
    assert result.plan is None
    assert result.cost is None
    assert rank_feasible((result,)) == ()
    assert result.blockers
    assert all(b.message != "" for b in result.blockers)
    codes = sorted(b.code for b in result.blockers)
    if case_file == "damaged_slot.json":
        # Blocks before compiler validation, so the synthetic flag changes
        # nothing; recorded as-is from the engine.
        assert codes == ["unsupported"]
    else:
        # impossible_request reaches compiler validation, which rejects the
        # synthetic_fixture process on the default path; geometry may also
        # be reported, so assert presence rather than inventing the full set.
        assert "unsupported_profile" in set(codes)


def test_unjoined_variant_rejected_without_allow_synthetic():
    """Extra feasible-derivative check; does not replace per-case coverage."""
    mutated, process_dict = unjoined_damage_variant()
    request = ReplannerInput.model_validate(mutated)
    process = make_process(
        process_dict, request.base_plan.project_id, request.base_plan.version_id
    )
    result = simulate_patch(request, process=process)
    assert result.status == "blocked"
    assert result.plan is None
    assert result.cost is None
    assert sorted(b.code for b in result.blockers) == ["unsupported_profile"]
    assert all(b.message != "" for b in result.blockers)
    assert rank_feasible((result,)) == ()
