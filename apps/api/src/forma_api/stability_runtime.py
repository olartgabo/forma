"""Initial read-only S1 adapter. Canonical pose production and S2 storage are absent."""

from dataclasses import dataclass
from typing import Literal, Protocol

from forma_stability import evaluate_stability

from forma_api.plans import PlanVersion
from forma_api.progress import ProgressSnapshot
from forma_api.projects import Project
from forma_domain.models import (
    ID,
    Evidence,
    EvidenceInvalidation,
    PhysicalEvent,
    Record,
)
from forma_domain.stability_contracts import (
    AnalysisPolicy,
    StabilityInput,
    StabilityReport,
)


class StabilityAnalysisRequest(Record):
    plan_version_id: ID
    expected_inventory_revision_id: ID
    expected_last_event_id: ID | None


class StabilityContext(Record):
    project_id: ID
    plan_version_id: ID
    inventory_revision_id: ID
    last_event_id: ID | None


class StabilityAnalysisResponse(StabilityContext):
    status: Literal["complete", "needs_geometry", "needs_measurement", "unsupported"]
    report: StabilityReport | None = None
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class StabilitySnapshot:
    project: Project
    version: PlanVersion
    progress: ProgressSnapshot
    last_event_id: str | None
    history_events: tuple[PhysicalEvent, ...]
    history_evidence: tuple[Evidence, ...]
    evidence_invalidations: tuple[EvidenceInvalidation, ...] = ()


@dataclass(frozen=True)
class ResolvedStability:
    analysis: StabilityInput
    policy: AnalysisPolicy


class StabilityResolver(Protocol):
    def __call__(self, snapshot: StabilitySnapshot) -> ResolvedStability | None: ...


MISSING_PREREQUISITES = (
    "Canonical world poses and active support contacts from the geometry producer (#144) are unavailable",
    "Version-bound body mass and center-of-mass measurements or explicit unknown estimates are required",
    "Server-owned load cases, applicability assumptions and analysis policy are required",
)


def analyze(snapshot: StabilitySnapshot, resolver: StabilityResolver | None = None):
    fields = dict(
        project_id=snapshot.project.id,
        plan_version_id=snapshot.version.version_id,
        inventory_revision_id=snapshot.project.revision_id,
        last_event_id=snapshot.last_event_id,
    )
    resolved = resolver(snapshot) if resolver is not None else None
    if resolved is None:
        return StabilityAnalysisResponse(
            **fields, status="needs_geometry", blockers=MISSING_PREREQUISITES
        )
    analysis, policy = resolved.analysis, resolved.policy
    identity = analysis.identity
    if (
        identity.project_id != snapshot.project.id
        or identity.plan_version_id != snapshot.version.version_id
        or identity.inventory_revision != snapshot.project.revision_id
        or identity.history_cursor != snapshot.last_event_id
    ):
        raise ValueError(
            "Resolved analysis identity does not match authorized snapshot"
        )
    parts = {part.id for part in snapshot.version.plan.parts}
    if any(
        not set(body.source_part_ids) <= parts
        for body in analysis.mechanical_snapshot.bodies
    ):
        raise ValueError("Resolved body references parts outside the authorized plan")
    invalidated = {
        item.evidence_id
        for item in snapshot.evidence_invalidations
        if item.invalidated_for_version_id == snapshot.version.version_id
    }
    evidence_by_id = {
        e.id: e
        for e in snapshot.history_evidence
        if e.project_id == snapshot.project.id
        and e.version_id == snapshot.version.version_id
        and e.id not in invalidated
    }

    def validate_quantity(quantity, source_parts):
        if not set(quantity.evidence_ids) <= evidence_by_id.keys():
            raise ValueError(
                "Resolved quantities reference unauthorized or stale evidence"
            )
        if any(
            not set(evidence_by_id[key].part_ids) <= source_parts
            for key in quantity.evidence_ids
        ):
            raise ValueError(
                "Resolved quantities reference evidence for unrelated parts"
            )
        # Evidence/PhysicalEvent currently store descriptions and provenance, not
        # a validated measurement property, SI value, unit and body binding.
        # Even a current user-confirmed `measurement` record cannot authenticate
        # this scalar. Do not parse text or infer authority from an evidence ID.
        if quantity.provenance == "measured" or quantity.confirmed:
            raise ValueError(
                "Typed measurement evidence binding is unavailable; measured or confirmed stability quantities are unsupported"
            )

    for body in analysis.mechanical_snapshot.bodies:
        quantities = (
            body.mass,
            body.center_of_mass.x,
            body.center_of_mass.y,
            body.center_of_mass.z,
        )
        for quantity in quantities:
            validate_quantity(quantity, set(body.source_part_ids))
    for case in analysis.cases:
        validate_quantity(case.gravity_m_s2, set())
    report = evaluate_stability(analysis, policy)
    status = "complete"
    if report.status == "needs_measurement":
        status = "needs_measurement"
    elif report.status in ("unsupported", "indeterminate"):
        status = "unsupported"
    return StabilityAnalysisResponse(
        **fields, status=status, report=report, blockers=report.unresolved_predicates
    )
