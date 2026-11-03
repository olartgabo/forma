"""Turn recorded attempts and their Proof exports into evaluation counts.

Every rate is a numerator over a denominator taken from records: a manifest
the team writes per attempt and, for FORMA attempts, the Proof JSON export. A
fixture, compiler or bench result never counts as a physical attempt, and a
zero denominator is reported as such instead of as a rate.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from forma_api.proof import ProofSnapshot
from forma_domain.models import Record, Text

EvidenceLevel = Literal[
    "fixture_only",
    "compiler_validated",
    "bench_tested",
    "physically_attempted",
    "physically_passed",
]
PHYSICAL = ("physically_attempted", "physically_passed")


class Attempt(Record):
    id: str = Field(min_length=1)
    inventory: Literal["A", "B"]
    case: Literal[
        "none",
        "missing_connector",
        "dimension_mismatch",
        "damaged_joint",
        "infeasible",
    ]
    method: Literal["forma", "single_prompt", "vision_chat", "fixed_template"]
    evidence_level: EvidenceLevel
    builder: Literal["team", "independent"]
    # Path to the Proof JSON export, relative to the manifest file.
    proof_export: str | None = None
    # For the infeasible case: the concrete blocker FORMA or the baseline gave.
    rejection: Text | None = None
    human_corrections: int | None = Field(default=None, ge=0)
    questions_asked: int | None = Field(default=None, ge=0)
    notes: Text | None = None


class Manifest(Record):
    attempts: tuple[Attempt, ...] = Field(min_length=1)


@dataclass(frozen=True)
class ProofFacts:
    """What one Proof export records. Times are server ingestion times."""

    passed: bool
    failure_recorded: bool
    recovered: bool
    revisions: int
    preserved_operations: int
    lost_operations: int
    sheet_waste_mm2: float
    connector_waste_mm: float
    failure_to_pass_seconds: float | None


def proof_facts(proof: ProofSnapshot) -> ProofFacts:
    active = next((v for v in proof.versions if v.state == "active"), None)
    events = [event for v in proof.versions for event in v.progress.events]
    failures = sorted(
        event.recorded_at
        for event in events
        if event.verification_state == "failed" or event.kind == "damage"
    )
    passed = active is not None and active.progress.status == "passed"
    passes = sorted(
        event.recorded_at
        for event in (active.progress.events if active else ())
        if event.kind == "test" and event.test_result == "passed"
    )
    revisions = [v.revision for v in proof.versions if v.revision is not None]
    transactions = [
        item for v in proof.versions for item in v.progress.material_transactions
    ]
    return ProofFacts(
        passed=passed,
        failure_recorded=bool(failures),
        recovered=passed and bool(failures) and active.revision is not None,
        revisions=len(revisions),
        preserved_operations=sum(
            len(r.simulation.preserved_operation_ids) for r in revisions
        ),
        lost_operations=sum(len(r.simulation.lost_operation_ids) for r in revisions),
        sheet_waste_mm2=sum(
            t.quantity for t in transactions if t.kind == "waste" and t.unit == "mm2"
        ),
        connector_waste_mm=sum(
            t.quantity for t in transactions if t.kind == "waste" and t.unit == "mm"
        ),
        failure_to_pass_seconds=(passes[-1] - failures[0]).total_seconds()
        if passed and failures and passes and passes[-1] > failures[0]
        else None,
    )


def conflicts(attempt: Attempt, facts: ProofFacts | None) -> list[str]:
    """Places where the manifest label disagrees with the recorded Proof."""
    problems = []
    if attempt.method == "forma" and attempt.evidence_level in PHYSICAL:
        if facts is None:
            problems.append(f"{attempt.id}: physical FORMA attempt has no Proof export")
        elif attempt.evidence_level == "physically_passed" and not facts.passed:
            problems.append(
                f"{attempt.id}: labelled physically passed, but Proof records no passed functional test"
            )
        elif attempt.evidence_level == "physically_attempted" and facts.passed:
            problems.append(
                f"{attempt.id}: Proof records a passed functional test, but the label says attempted only"
            )
    if attempt.case == "infeasible" and attempt.evidence_level == "physically_passed":
        problems.append(f"{attempt.id}: an infeasible case cannot be physically passed")
    return problems


def _rate(numerator: int, denominator: int, empty: str) -> str:
    if denominator == 0:
        return f"n/a ({empty})"
    return f"{numerator}/{denominator} ({100 * numerator / denominator:.0f}%)"


def summarize(entries: Sequence[tuple[Attempt, ProofFacts | None]]) -> str:
    lines = [
        "# FORMA evaluation results",
        "",
        "Counts come from the attempt manifest and Proof exports. Only physically",
        "attempted builds enter completion and recovery rates; fixture, compiler and",
        "bench results are listed separately. Times are report ingestion times.",
    ]
    problems = [p for attempt, facts in entries for p in conflicts(attempt, facts)]
    if problems:
        lines += ["", "## Label conflicts (resolve before reporting)", ""]
        lines += [f"- {p}" for p in problems]
    for method in ("forma", "single_prompt", "vision_chat", "fixed_template"):
        rows = [(a, f) for a, f in entries if a.method == method]
        lines += ["", f"## {method}", ""]
        if not rows:
            lines.append("No attempts recorded.")
            continue
        physical = [(a, f) for a, f in rows if a.evidence_level in PHYSICAL]
        feasible = [(a, f) for a, f in physical if a.case != "infeasible"]
        passed = [a for a, _ in feasible if a.evidence_level == "physically_passed"]
        disrupted = [
            (a, f)
            for a, f in feasible
            if a.case != "none" or (f is not None and f.failure_recorded)
        ]
        recovered = [a for a, _ in disrupted if a.evidence_level == "physically_passed"]
        infeasible = [a for a, _ in rows if a.case == "infeasible"]
        rejected = [a for a in infeasible if a.rejection]
        recorded = [f for _, f in rows if f is not None]
        preserved = sum(f.preserved_operations for f in recorded)
        lost = sum(f.lost_operations for f in recorded)
        times = [
            f.failure_to_pass_seconds
            for f in recorded
            if f.failure_to_pass_seconds is not None
        ]
        corrections = [
            a.human_corrections for a, _ in rows if a.human_corrections is not None
        ]
        questions = [
            a.questions_asked for a, _ in rows if a.questions_asked is not None
        ]
        lines += [
            "| Measure | Result |",
            "| --- | --- |",
            "| Completion (physically passed / physically attempted) | "
            + _rate(len(passed), len(feasible), "no physical attempt")
            + " |",
            "| Recovery after a disruption (passed / disrupted attempts) | "
            + _rate(len(recovered), len(disrupted), "no disrupted physical attempt")
            + " |",
            "| Infeasible case rejected with a concrete blocker | "
            + _rate(len(rejected), len(infeasible), "no infeasible case attempted")
            + " |",
            "| Preserved work in approved revisions (kept / kept + lost) | "
            + _rate(preserved, preserved + lost, "no approved revision recorded")
            + " |",
            f"| Recorded sheet waste | {sum(f.sheet_waste_mm2 for f in recorded):g} mm2 |",
            f"| Recorded connector waste | {sum(f.connector_waste_mm for f in recorded):g} mm |",
            "| Median failure-to-pass time | "
            + (
                f"{statistics.median(times):g} s over {len(times)} recoveries"
                if times
                else "n/a (no recovery with both times recorded)"
            )
            + " |",
            "| Human instruction corrections | "
            + (
                f"{sum(corrections)} over {len(corrections)} attempts"
                if corrections
                else "not recorded"
            )
            + " |",
            "| Questions asked | "
            + (
                f"{sum(questions)} over {len(questions)} attempts"
                if questions
                else "not recorded"
            )
            + " |",
        ]
        unphysical = [a for a, _ in rows if a.evidence_level not in PHYSICAL]
        if unphysical:
            levels = sorted({a.evidence_level for a in unphysical})
            lines += [
                "",
                f"Not counted as builds: {len(unphysical)} attempts at "
                + ", ".join(levels)
                + ".",
            ]
        independent = sum(1 for a, _ in physical if a.builder == "independent")
        lines.append(f"Independent builders among physical attempts: {independent}.")
    return "\n".join(lines) + "\n"


def load(manifest_path: Path) -> list[tuple[Attempt, ProofFacts | None]]:
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    ids = [attempt.id for attempt in manifest.attempts]
    if len(set(ids)) != len(ids):
        raise ValueError("Attempt IDs must be unique")
    entries = []
    for attempt in manifest.attempts:
        facts = None
        if attempt.proof_export is not None:
            path = manifest_path.parent / attempt.proof_export
            facts = proof_facts(
                ProofSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
            )
        entries.append((attempt, facts))
    return entries
