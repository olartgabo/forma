"""Synthetic software histories only; no physical build, recovery or result."""

import json

import pytest
from test_adapt import (
    AUTH,
    commit,
    joined,
    patch,
    progress,
    report,
    report_damage,
    simulate,
)

from forma_api.proof import ProofSnapshot
from forma_eval.__main__ import main
from forma_eval.report import Attempt, ProofFacts, conflicts, proof_facts, summarize


def recovered_proof(client, version):
    """Damage, an approved brace replacement, then every remaining step passed."""
    plan = version.plan
    damaged = report_damage(client, plan, joined(client, version))
    preview = simulate(client, plan, damaged, [patch(plan)]).json()["previews"][0]
    approved = commit(client, plan, damaged, preview["preview_id"]).json()
    revised = approved["project"]["active_version_id"]
    new_plan = ProofSnapshot.model_validate(
        client.get(f"/api/projects/{plan.project_id}/proof", headers=AUTH).json()
    ).versions
    new_plan = next(v.plan for v in new_plan if v.plan.version_id == revised)
    done = set(progress(client, plan.project_id, revised)["completed_operation_ids"])
    for operation in new_plan.operations:
        if operation.id not in done:
            report(client, plan.project_id, new_plan, operation.id)
    return ProofSnapshot.model_validate(
        client.get(f"/api/projects/{plan.project_id}/proof", headers=AUTH).json()
    )


def test_facts_come_from_the_recorded_history(setup):
    client, version, _ = setup
    proof = recovered_proof(client, version)
    revision = next(v.revision for v in proof.versions if v.revision is not None)
    facts = proof_facts(proof)
    assert facts.passed and facts.failure_recorded and facts.recovered
    assert facts.revisions == 1
    assert facts.preserved_operations == len(
        revision.simulation.preserved_operation_ids
    )
    assert facts.lost_operations == len(revision.simulation.lost_operation_ids) == 2
    assert facts.sheet_waste_mm2 == facts.connector_waste_mm == 0
    assert facts.failure_to_pass_seconds is not None
    assert facts.failure_to_pass_seconds > 0


def test_cli_reports_a_recovered_attempt_and_rejects_a_contradicted_label(
    setup, tmp_path, capsys
):
    client, version, _ = setup
    proof = recovered_proof(client, version)
    (tmp_path / "proof.json").write_text(proof.model_dump_json(), encoding="utf-8")
    attempt = dict(
        id="a-damaged",
        inventory="A",
        case="damaged_joint",
        method="forma",
        evidence_level="physically_passed",
        builder="team",
        proof_export="proof.json",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"attempts": [attempt]}), encoding="utf-8")
    assert main([str(manifest)]) == 0
    output = capsys.readouterr().out
    assert (
        "| Recovery after a disruption (passed / disrupted attempts) | 1/1 (100%) |"
        in output
    )
    assert "Label conflicts" not in output

    attempt["evidence_level"] = "physically_attempted"
    manifest.write_text(json.dumps({"attempts": [attempt]}), encoding="utf-8")
    assert main([str(manifest)]) == 1
    assert (
        "a-damaged: Proof records a passed functional test, but the label says attempted only"
        in capsys.readouterr().out
    )


def attempt(**fields):
    values = dict(
        id="attempt",
        inventory="A",
        case="none",
        method="forma",
        evidence_level="physically_attempted",
        builder="team",
    )
    return Attempt(**(values | fields))


def facts(**fields):
    values = dict(
        passed=False,
        failure_recorded=False,
        recovered=False,
        revisions=0,
        preserved_operations=0,
        lost_operations=0,
        sheet_waste_mm2=0.0,
        connector_waste_mm=0.0,
        failure_to_pass_seconds=None,
    )
    return ProofFacts(**(values | fields))


def test_fixture_and_bench_results_never_count_as_builds():
    report_text = summarize(
        [
            (attempt(id="fixture", evidence_level="fixture_only"), None),
            (attempt(id="bench", evidence_level="bench_tested"), None),
        ]
    )
    assert (
        "| Completion (physically passed / physically attempted) | n/a (no physical attempt) |"
        in report_text
    )
    assert (
        "Not counted as builds: 2 attempts at bench_tested, fixture_only."
        in report_text
    )


def test_rates_count_only_recorded_physical_outcomes():
    entries = [
        (attempt(id="a1", evidence_level="physically_passed"), facts(passed=True)),
        (attempt(id="a2"), facts()),
        (
            attempt(
                id="b1",
                inventory="B",
                case="damaged_joint",
                evidence_level="physically_passed",
                builder="independent",
                human_corrections=2,
                questions_asked=3,
            ),
            facts(
                passed=True,
                failure_recorded=True,
                recovered=True,
                revisions=1,
                preserved_operations=6,
                lost_operations=2,
                sheet_waste_mm2=1200,
                connector_waste_mm=20,
                failure_to_pass_seconds=900,
            ),
        ),
        (
            attempt(
                id="x", case="infeasible", rejection="stock_exhausted: no region fits"
            ),
            None,
        ),
        (attempt(id="y", case="infeasible"), None),
        (
            attempt(
                id="t", method="fixed_template", evidence_level="physically_passed"
            ),
            None,
        ),
    ]
    text = summarize(entries)
    forma = text.split("## forma")[1].split("## single_prompt")[0]
    for row in (
        "| Completion (physically passed / physically attempted) | 2/3 (67%) |",
        "| Recovery after a disruption (passed / disrupted attempts) | 1/1 (100%) |",
        "| Infeasible case rejected with a concrete blocker | 1/2 (50%) |",
        "| Preserved work in approved revisions (kept / kept + lost) | 6/8 (75%) |",
        "| Recorded sheet waste | 1200 mm2 |",
        "| Recorded connector waste | 20 mm |",
        "| Median failure-to-pass time | 900 s over 1 recoveries |",
        "| Human instruction corrections | 2 over 1 attempts |",
        "| Questions asked | 3 over 1 attempts |",
        "Independent builders among physical attempts: 1.",
    ):
        assert row in forma, row
    template = text.split("## fixed_template")[1]
    assert (
        "| Completion (physically passed / physically attempted) | 1/1 (100%) |"
        in template
    )
    assert "## single_prompt\n\nNo attempts recorded." in text


def test_labels_that_contradict_proof_are_flagged():
    assert conflicts(attempt(evidence_level="physically_passed"), facts()) == [
        "attempt: labelled physically passed, but Proof records no passed functional test"
    ]
    assert conflicts(attempt(), None) == [
        "attempt: physical FORMA attempt has no Proof export"
    ]
    assert conflicts(
        attempt(case="infeasible", evidence_level="physically_passed"),
        facts(passed=True),
    ) == ["attempt: an infeasible case cannot be physically passed"]
    assert conflicts(attempt(method="vision_chat"), None) == []


@pytest.mark.parametrize("failure_recorded", [False, True])
def test_a_passed_disruption_without_recorded_recovery_is_not_a_recovery(
    failure_recorded,
):
    entry = attempt(case="damaged_joint", evidence_level="physically_passed")
    recorded = facts(passed=True, failure_recorded=failure_recorded)
    text = summarize([(entry, recorded)])
    assert (
        "| Completion (physically passed / physically attempted) | 1/1 (100%) |" in text
    )
    assert (
        "| Recovery after a disruption (passed / disrupted attempts) | 0/1 (0%) |"
        in text
    )


@pytest.mark.parametrize("method", ["single_prompt", "vision_chat", "fixed_template"])
def test_baseline_recovery_uses_the_observers_recorded_outcome(method):
    text = summarize(
        [
            (
                attempt(
                    method=method,
                    case="damaged_joint",
                    evidence_level="physically_passed",
                ),
                None,
            )
        ]
    )
    assert (
        "| Recovery after a disruption (passed / disrupted attempts) | 1/1 (100%) |"
        in text
    )


def test_cli_does_not_count_a_passed_initial_build_as_recovered(
    setup, tmp_path, capsys
):
    client, version, _ = setup
    plan = version.plan
    for operation in plan.operations:
        report(client, plan.project_id, plan, operation.id)
    proof = client.get(f"/api/projects/{plan.project_id}/proof", headers=AUTH).json()
    (tmp_path / "proof.json").write_text(json.dumps(proof), encoding="utf-8")
    entry = attempt(
        case="damaged_joint",
        evidence_level="physically_passed",
        proof_export="proof.json",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"attempts": [entry.model_dump()]}), encoding="utf-8"
    )
    assert main([str(manifest)]) == 0
    output = capsys.readouterr().out
    assert (
        "| Recovery after a disruption (passed / disrupted attempts) | 0/1 (0%) |"
        in output
    )


@pytest.mark.parametrize(
    "level", ["fixture_only", "compiler_validated", "bench_tested"]
)
@pytest.mark.parametrize("with_physical", [False, True])
def test_nonphysical_proof_cannot_change_physical_material_or_recovery_metrics(
    level, with_physical
):
    synthetic = (
        attempt(id="synthetic", case="damaged_joint", evidence_level=level),
        facts(
            passed=True,
            failure_recorded=True,
            recovered=True,
            revisions=1,
            preserved_operations=600,
            lost_operations=200,
            sheet_waste_mm2=1200,
            connector_waste_mm=20,
            failure_to_pass_seconds=900,
        ),
    )
    physical = (
        attempt(case="damaged_joint", evidence_level="physically_passed"),
        facts(
            passed=True,
            failure_recorded=True,
            recovered=True,
            revisions=1,
            preserved_operations=3,
            lost_operations=1,
            sheet_waste_mm2=100,
            connector_waste_mm=5,
            failure_to_pass_seconds=60,
        ),
    )
    text = summarize([synthetic, physical] if with_physical else [synthetic])
    rows = text.splitlines()
    expected = (
        (
            "| Preserved work in approved revisions (kept / kept + lost) | 3/4 (75%) |",
            "| Recorded sheet waste | 100 mm2 |",
            "| Recorded connector waste | 5 mm |",
            "| Median failure-to-pass time | 60 s over 1 recoveries |",
        )
        if with_physical
        else (
            "| Preserved work in approved revisions (kept / kept + lost) | n/a (no approved revision recorded) |",
            "| Recorded sheet waste | 0 mm2 |",
            "| Recorded connector waste | 0 mm |",
            "| Median failure-to-pass time | n/a (no recovery with both times recorded) |",
        )
    )
    for row in expected:
        assert row in rows


def test_time_from_an_unrecovered_failure_is_not_reported_as_recovery_time():
    text = summarize(
        [
            (
                attempt(case="damaged_joint", evidence_level="physically_passed"),
                facts(passed=True, failure_recorded=True, failure_to_pass_seconds=900),
            )
        ]
    )
    assert (
        "| Median failure-to-pass time | n/a (no recovery with both times recorded) |"
        in text
    )
