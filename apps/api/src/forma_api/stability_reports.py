"""Immutable, content-addressed saved stability reports and their history.

A saved report records the exact normalized engine input, policy, report and
dependency versions that produced it. Reports never become physical evidence:
they are modeled results bound to one plan, inventory and history cursor, and
they turn stale when any of those change.
"""

from datetime import UTC, datetime
from typing import Literal

import numpy as np
import shapely
from forma_stability import ENGINE_VERSION
from pydantic import AwareDatetime, Field

from forma_api import stability_runtime as runtime
from forma_api.plans import PlanService
from forma_api.progress import snapshot as progress_snapshot
from forma_api.projects import Key, ProjectError
from forma_api.stability_measurements import digest, latest_record, typed_evidence_ids
from forma_domain.models import (
    ID,
    Evidence,
    EvidenceInvalidation,
    PhysicalEvent,
    Record,
    Text,
)
from forma_domain.stability_contracts import (
    CheckStatus,
    CheckType,
    ContentHash,
    StabilityInput,
    StabilityReport,
)

REPORT_PREFIX = "stability-report-"
HISTORY_LIMIT = 50
StaleReason = Literal[
    "plan_changed", "inventory_changed", "history_changed", "evidence_invalidated"
]


class DependencyVersions(Record):
    engine: Text
    numpy: Text
    shapely: Text
    geos: Text


class SavedStabilityReport(Record):
    """Immutable record; its ID is derived from the engine's cache hash."""

    report_id: ID
    project_id: ID
    plan_version_id: ID
    inventory_revision_id: ID
    history_cursor: ID | None
    created_at: AwareDatetime
    source: Literal["builder", "muse_tool"]
    analysis_status: Literal["complete", "needs_measurement", "unsupported"]
    blockers: tuple[Text, ...] = Field(default=(), max_length=128)
    input_hash: ContentHash
    analysis_input: StabilityInput
    report: StabilityReport
    dependencies: DependencyVersions
    evidence_ids: tuple[ID, ...] = Field(default=(), max_length=256)


class ReportFreshness(Record):
    current: bool
    stale_reasons: tuple[StaleReason, ...] = ()


class StabilityReportSummary(Record):
    report_id: ID
    plan_version_id: ID
    inventory_revision_id: ID
    history_cursor: ID | None
    created_at: AwareDatetime
    source: Literal["builder", "muse_tool"]
    analysis_status: Literal["complete", "needs_measurement", "unsupported"]
    report_status: CheckStatus
    coverage: Literal["complete", "partial", "unsupported"]
    policy_id: ID
    policy_version: Text
    case_ids: tuple[ID, ...]
    freshness: ReportFreshness


class StabilityReportSaveRequest(runtime.StabilityAnalysisRequest):
    idempotency_key: Key


class StabilityReportSaveResponse(Record):
    analysis: runtime.StabilityAnalysisResponse
    saved: StabilityReportSummary | None = None
    cached: bool = False
    replayed: bool = False


class StabilityReportHistory(Record):
    project_id: ID
    active_plan_version_id: ID | None
    inventory_revision_id: ID
    last_event_id: ID | None
    reports: tuple[StabilityReportSummary, ...] = Field(max_length=HISTORY_LIMIT)


class StabilityReportDetail(Record):
    saved: SavedStabilityReport
    freshness: ReportFreshness


ComparisonOutcome = Literal[
    "not_comparable",
    "unknown",
    "first_larger_margin",
    "second_larger_margin",
    "equal_within_tolerance",
    "same_status",
    "different_status",
]


class ComparisonRow(Record):
    case_id: ID
    check_type: CheckType
    first_status: CheckStatus | None
    second_status: CheckStatus | None
    first_margin_m: float | None = None
    second_margin_m: float | None = None
    outcome: ComparisonOutcome


class StabilityReportComparison(Record):
    """Per-check comparison only; no overall ranking or physical claim."""

    project_id: ID
    first: StabilityReportSummary
    second: StabilityReportSummary
    comparable: bool
    mismatches: tuple[Text, ...] = ()
    rows: tuple[ComparisonRow, ...] = Field(default=(), max_length=80)


def dependencies() -> DependencyVersions:
    return DependencyVersions(
        engine=ENGINE_VERSION,
        numpy=np.__version__,
        shapely=shapely.__version__,
        geos=shapely.geos_version_string,
    )


def report_id(report: StabilityReport) -> str:
    return REPORT_PREFIX + report.cache_hash


def _rows(connection, table, project_id):
    return connection.execute(
        f"SELECT body FROM {table} WHERE project_id=? ORDER BY rowid", (project_id,)
    )


def last_event_id(connection, project_id):
    row = connection.execute(
        "SELECT id FROM progress_events WHERE project_id=? ORDER BY rowid DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    return row[0] if row else None


def invalidations(connection, project_id):
    return tuple(
        EvidenceInvalidation.model_validate_json(row[0])
        for row in _rows(connection, "evidence_invalidations", project_id)
    )


def authorized_snapshot(connection, store, owner, project_id, request):
    """Owner-scoped snapshot that must match the caller's expected identity."""
    project = store.read(connection, owner, project_id)
    version = PlanService(store).read(connection, project_id, request.plan_version_id)
    if project.revision_id != request.expected_inventory_revision_id:
        raise ProjectError(409, "stale_version", "Inventory changed; reload it")
    if project.active_version_id != request.plan_version_id:
        raise ProjectError(409, "stale_version", "Active plan changed; reload it")
    events = tuple(
        PhysicalEvent.model_validate_json(row[0])
        for row in _rows(connection, "progress_events", project_id)
    )
    cursor = events[-1].id if events else None
    if cursor != request.expected_last_event_id:
        raise ProjectError(409, "stale_version", "Physical history changed; reload it")
    evidence = tuple(
        Evidence.model_validate_json(row[0])
        for row in _rows(connection, "progress_evidence", project_id)
    )
    return runtime.StabilitySnapshot(
        project,
        version,
        progress_snapshot(connection, version.plan),
        cursor,
        events,
        evidence,
        invalidations(connection, project_id),
        latest_record(connection, project_id, version.version_id),
        typed_evidence_ids(connection, project_id, version.version_id),
    )


def evaluate(snapshot, resolver):
    try:
        return runtime.evaluate(snapshot, resolver)
    except ValueError:
        raise ProjectError(
            422,
            "validation_error",
            "Server stability context does not match the authorized snapshot",
        ) from None


def _evidence_ids(analysis: StabilityInput):
    found = set()

    def visit(value):
        if isinstance(value, dict):
            found.update(value.get("evidence_ids") or ())
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(analysis.model_dump(mode="json"))
    return tuple(sorted(found))


def build_record(evaluation, source, now=None) -> SavedStabilityReport | None:
    """The immutable record for an evaluation, or None when it has no report."""
    response, analysis = evaluation.response, evaluation.analysis
    if response.report is None or analysis is None:
        return None
    return SavedStabilityReport(
        report_id=report_id(response.report),
        project_id=response.project_id,
        plan_version_id=response.plan_version_id,
        inventory_revision_id=response.inventory_revision_id,
        history_cursor=response.last_event_id,
        created_at=now or datetime.now(UTC),
        source=source,
        analysis_status=response.status,
        blockers=response.blockers,
        input_hash=digest(analysis.model_dump(mode="json")),
        analysis_input=analysis,
        report=response.report,
        dependencies=dependencies(),
        evidence_ids=_evidence_ids(analysis),
    )


def store_record(connection, record: SavedStabilityReport):
    """Insert once; an identical calculation returns the first saved record."""
    existing = read_record(connection, record.project_id, record.report_id)
    if existing is not None:
        return existing, True
    connection.execute(
        "INSERT INTO stability_reports VALUES (?, ?, ?, ?)",
        (
            record.report_id,
            record.project_id,
            record.plan_version_id,
            record.model_dump_json(),
        ),
    )
    return record, False


def read_record(connection, project_id, saved_id):
    row = connection.execute(
        "SELECT body FROM stability_reports WHERE id=? AND project_id=?",
        (saved_id, project_id),
    ).fetchone()
    return None if row is None else SavedStabilityReport.model_validate_json(row[0])


def freshness(saved, project, cursor, invalidated) -> ReportFreshness:
    reasons = []
    if project.active_version_id != saved.plan_version_id:
        reasons.append("plan_changed")
    if project.revision_id != saved.inventory_revision_id:
        reasons.append("inventory_changed")
    if cursor != saved.history_cursor:
        reasons.append("history_changed")
    if any(
        item.evidence_id in saved.evidence_ids
        and item.invalidated_for_version_id == saved.plan_version_id
        for item in invalidated
    ):
        reasons.append("evidence_invalidated")
    return ReportFreshness(current=not reasons, stale_reasons=tuple(reasons))


def summarize(saved, fresh) -> StabilityReportSummary:
    return StabilityReportSummary(
        report_id=saved.report_id,
        plan_version_id=saved.plan_version_id,
        inventory_revision_id=saved.inventory_revision_id,
        history_cursor=saved.history_cursor,
        created_at=saved.created_at,
        source=saved.source,
        analysis_status=saved.analysis_status,
        report_status=saved.report.status,
        coverage=saved.report.coverage,
        policy_id=saved.report.policy.policy_id,
        policy_version=saved.report.policy.version,
        case_ids=tuple(case.case_id for case in saved.analysis_input.cases),
        freshness=fresh,
    )


class ProjectState:
    """Current project identity used to judge saved-report freshness."""

    def __init__(self, connection, store, owner, project_id):
        self.project = store.read(connection, owner, project_id)
        self.cursor = last_event_id(connection, project_id)
        self.invalidated = invalidations(connection, project_id)

    def freshness(self, saved):
        return freshness(saved, self.project, self.cursor, self.invalidated)

    def summary(self, saved):
        return summarize(saved, self.freshness(saved))


def history(connection, store, owner, project_id, plan_version_id=None, limit=None):
    state = ProjectState(connection, store, owner, project_id)
    limit = HISTORY_LIMIT if limit is None else limit
    query = "SELECT body FROM stability_reports WHERE project_id=?"
    params: tuple = (project_id,)
    if plan_version_id is not None:
        query += " AND version_id=?"
        params += (plan_version_id,)
    rows = connection.execute(
        query + " ORDER BY rowid DESC LIMIT ?", params + (limit,)
    ).fetchall()
    return StabilityReportHistory(
        project_id=project_id,
        active_plan_version_id=state.project.active_version_id,
        inventory_revision_id=state.project.revision_id,
        last_event_id=state.cursor,
        reports=tuple(
            state.summary(SavedStabilityReport.model_validate_json(row[0]))
            for row in rows
        ),
    )


def detail(connection, store, owner, project_id, saved_id):
    state = ProjectState(connection, store, owner, project_id)
    saved = read_record(connection, project_id, saved_id)
    if saved is None:
        raise ProjectError(404, "not_found", "Stability report not found")
    return StabilityReportDetail(saved=saved, freshness=state.freshness(saved))


def _margins(report):
    return {o.case_id: o.signed_margin_m for o in report.overlays}


def compare(connection, store, owner, project_id, first_id, second_id):
    state = ProjectState(connection, store, owner, project_id)
    if first_id == second_id:
        raise ProjectError(422, "validation_error", "Choose two different reports")
    first, second = (
        read_record(connection, project_id, i) for i in (first_id, second_id)
    )
    if first is None or second is None:
        raise ProjectError(404, "not_found", "Stability report not found")
    a, b = first.report, second.report
    mismatches = []
    if a.policy != b.policy:
        mismatches.append("Reports use different analysis policies or margins")
    if (
        a.report_version != b.report_version
        or first.dependencies != second.dependencies
    ):
        mismatches.append(
            "Reports were produced by different engine or dependency versions"
        )
    cases_a = {c.case_id: c.orientation for c in first.analysis_input.cases}
    cases_b = {c.case_id: c.orientation for c in second.analysis_input.cases}
    if cases_a != cases_b:
        mismatches.append("Reports evaluate different load cases")
    comparable = not mismatches
    tolerance = a.policy.length_tolerance_m
    index_a = {(r.case_id, r.check_type): r for r in a.results}
    index_b = {(r.case_id, r.check_type): r for r in b.results}
    margins_a, margins_b = _margins(a), _margins(b)
    rows = []
    for key in sorted(index_a.keys() | index_b.keys()):
        case_id, check_type = key
        ra, rb = index_a.get(key), index_b.get(key)
        decisive = ("modeled_pass", "modeled_fail")
        ma = margins_a.get(case_id) if check_type == "tip" else None
        mb = margins_b.get(case_id) if check_type == "tip" else None
        if not comparable:
            outcome = "not_comparable"
        elif (
            ra is None
            or rb is None
            or ra.status not in decisive
            or rb.status not in decisive
        ):
            outcome = "unknown"
        elif ma is not None and mb is not None:
            if abs(ma - mb) <= tolerance:
                outcome = "equal_within_tolerance"
            else:
                outcome = "first_larger_margin" if ma > mb else "second_larger_margin"
        else:
            outcome = "same_status" if ra.status == rb.status else "different_status"
        rows.append(
            ComparisonRow(
                case_id=case_id,
                check_type=check_type,
                first_status=ra.status if ra else None,
                second_status=rb.status if rb else None,
                first_margin_m=ma,
                second_margin_m=mb,
                outcome=outcome,
            )
        )
    return StabilityReportComparison(
        project_id=project_id,
        first=state.summary(first),
        second=state.summary(second),
        comparable=comparable,
        mismatches=tuple(mismatches),
        rows=tuple(rows),
    )
