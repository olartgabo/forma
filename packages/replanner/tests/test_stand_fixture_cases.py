"""Synthetic stand fixtures loaded from disk, never physical evidence.

Every number, confirmation and test result in these files is a software
fixture. A ``feasible`` result here is a typed offline preview only; it is
not a physical pass and does not claim any physical work was performed.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from forma_compiler import CutProcess
from forma_renderer import (
    StandParameters,
    compile_stand,
    render_manual,
    stand_continuation_blockers,
)
from forma_replanner import rank_feasible, simulate_patch

from forma_domain import models as m

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures"
FIXTURE_FILES = (
    "missing_connector.json",
    "damaged_slot.json",
    "size_mismatch.json",
    "impossible_request.json",
)

EXPECTED_KEYS = {
    "status",
    "blocker_codes",
    "preserved_operation_ids",
    "required_undo_operation_ids",
    "invalidated_checkpoint_ids",
    "feasible_patch_ids",
}


def load_raw(fixture_file):
    return json.loads((FIXTURE_DIR / fixture_file).read_text(encoding="utf-8"))


def scenario_ids():
    ids = []
    for fixture_file in FIXTURE_FILES:
        for scenario in load_raw(fixture_file)["scenarios"]:
            ids.append((fixture_file, scenario["id"]))
    return ids


SCENARIOS = scenario_ids()


def find_scenario(raw, scenario_id):
    return next(s for s in raw["scenarios"] if s["id"] == scenario_id)


def assert_history_is_synthetic(scenario_input):
    for event in scenario_input["events"]:
        assert "SYNTHETIC" in event["observation"]
    for evidence in scenario_input["evidence"]:
        assert "SYNTHETIC" in evidence["description"]
    assert "SYNTHETIC" in scenario_input["patch"]["rationale"]


def build_plan(raw):
    """Compile and render the stand from typed fixture inputs."""
    raw_before = deepcopy(raw)
    request = m.CompilerInput.model_validate(raw["compiler_input"])
    parameters = StandParameters.model_validate(raw["stand_parameters"])
    process = CutProcess.model_validate(raw["process"])
    dumps_before = (
        deepcopy(request.model_dump(mode="python")),
        deepcopy(parameters.model_dump(mode="python")),
        deepcopy(process.model_dump(mode="python")),
    )

    compiled = compile_stand(request, parameters, process=process, allow_synthetic=True)
    assert compiled.status == "accepted", compiled.blockers
    assert compiled.plan is not None
    manual = render_manual(
        compiled.plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
    )
    assert manual.status == "accepted", manual.blockers

    # Neither compilation nor rendering may mutate the typed inputs or the
    # raw fixture data they were validated from.
    assert (
        request.model_dump(mode="python"),
        parameters.model_dump(mode="python"),
        process.model_dump(mode="python"),
    ) == dumps_before
    assert raw == raw_before
    return request, parameters, process, compiled.plan


def assert_result(result, expected):
    """Exact frozen comparison; shared by primary and mutation runs."""
    assert set(expected) == EXPECTED_KEYS
    assert expected["blocker_codes"] == sorted(expected["blocker_codes"])
    assert result.status == expected["status"]
    assert sorted(b.code for b in result.blockers) == expected["blocker_codes"]
    assert tuple(result.preserved_operation_ids) == tuple(
        expected["preserved_operation_ids"]
    )
    assert tuple(result.required_undo_operation_ids) == tuple(
        expected["required_undo_operation_ids"]
    )
    assert tuple(result.invalidated_checkpoint_ids) == tuple(
        expected["invalidated_checkpoint_ids"]
    )
    ranked = rank_feasible((result,))
    assert tuple(r.patch_id for r in ranked) == tuple(expected["feasible_patch_ids"])
    if expected["status"] == "feasible":
        assert result.plan is not None
        assert result.cost is not None
        assert result.blockers == ()
        assert ranked == (result,)
    else:
        assert result.plan is None
        assert result.cost is None
        assert ranked == ()


def run_scenario(scenario, input_key, plan, parameters, process):
    scenario_input = scenario[input_key]
    assert "base_plan" not in scenario_input
    assert_history_is_synthetic(scenario_input)

    injected = deepcopy(scenario_input)
    injected["base_plan"] = plan
    request = m.ReplannerInput.model_validate(injected)
    dump_before = deepcopy(request.model_dump(mode="python"))

    result = simulate_patch(
        request,
        process=process,
        allow_synthetic=True,
        family_validator=stand_continuation_blockers,
    )

    # Simulation must not mutate the typed snapshot, and the fixture's
    # on-disk scenario must still carry no injected base plan.
    assert request.model_dump(mode="python") == dump_before
    assert "base_plan" not in scenario[input_key]

    if result.status == "feasible":
        continuation = render_manual(
            result.plan,
            process=process,
            profile_evidence=parameters.profile_evidence,
            allow_synthetic=True,
        )
        assert continuation.status == "accepted", continuation.blockers
    return result


@pytest.mark.parametrize("fixture_file", FIXTURE_FILES)
def test_stand_fixture_compiles_renders_and_rejects_by_default(fixture_file):
    raw = load_raw(fixture_file)

    assert raw["provenance"] == "synthetic"
    assert raw["metadata"]["provenance"] == "synthetic"
    assert "SYNTHETIC" in raw["metadata"]["description"]
    assert "not physical" in raw["note"]

    request, parameters, process, _plan = build_plan(raw)

    assert request.constraints.allow_purchases is False
    for evidence in (*process.evidence, *parameters.profile_evidence):
        assert evidence.provenance == "synthetic_fixture"
        assert "SYNTHETIC" in evidence.description

    # Without the explicit synthetic opt-in the same typed inputs are
    # rejected at provenance, with no plan produced.
    rejected = compile_stand(request, parameters, process=process)
    assert rejected.status == "blocked"
    assert rejected.plan is None
    assert sorted(b.code for b in rejected.blockers) == ["unsupported_profile"]


@pytest.mark.parametrize(
    ("fixture_file", "scenario_id"),
    SCENARIOS,
    ids=[f"{name}:{sid}" for name, sid in SCENARIOS],
)
def test_stand_fixture_scenario(fixture_file, scenario_id):
    raw = load_raw(fixture_file)
    scenario = find_scenario(raw, scenario_id)
    _request, parameters, process, plan = build_plan(raw)

    result = run_scenario(scenario, "replanner_input", plan, parameters, process)
    assert_result(result, scenario["expected"])


@pytest.mark.parametrize(
    ("fixture_file", "scenario_id"),
    SCENARIOS,
    ids=[f"{name}:{sid}" for name, sid in SCENARIOS],
)
def test_stand_fixture_mutation_differs_from_primary(fixture_file, scenario_id):
    """Hypothetical fixture states, not claims of actual physical undo."""
    raw = load_raw(fixture_file)
    scenario = find_scenario(raw, scenario_id)
    _request, parameters, process, plan = build_plan(raw)

    result = run_scenario(scenario, "mutation_input", plan, parameters, process)
    assert_result(result, scenario["mutation_expected"])
    # The mutated state must genuinely diverge: the frozen primary
    # expectation no longer describes the mutated run.
    with pytest.raises(AssertionError):
        assert_result(result, scenario["expected"])
