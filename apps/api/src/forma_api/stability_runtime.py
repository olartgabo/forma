"""Read-only stability analysis with shared canonical nominal geometry."""

from dataclasses import dataclass
from typing import Literal, Protocol

from forma_stability import evaluate_stability
from pydantic import model_validator

from forma_api.plans import PlanVersion
from forma_api.progress import ProgressSnapshot
from forma_api.projects import Project
from forma_domain.assembly_geometry_contracts import CanonicalGeometryPreview
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
from forma_domain.stability_measurements import StabilityMeasurementRecord


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
    geometry_preview: CanonicalGeometryPreview | None = None

    @model_validator(mode="after")
    def preview_identity(self):
        geometry = self.geometry_preview
        if geometry is not None:
            if (
                geometry.project_id != self.project_id
                or geometry.plan_version_id != self.plan_version_id
                or geometry.history_cursor != self.last_event_id
            ):
                raise ValueError("Geometry preview must match response identity")
            if self.status != "needs_measurement" or self.report is not None:
                raise ValueError(
                    "Unresolved geometry preview cannot establish a stability report"
                )
        return self


@dataclass(frozen=True)
class StabilitySnapshot:
    project: Project
    version: PlanVersion
    progress: ProgressSnapshot
    last_event_id: str | None
    history_events: tuple[PhysicalEvent, ...]
    history_evidence: tuple[Evidence, ...]
    evidence_invalidations: tuple[EvidenceInvalidation, ...] = ()
    measurements: StabilityMeasurementRecord | None = None
    measurement_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedStability:
    analysis: StabilityInput
    policy: AnalysisPolicy


class StabilityResolver(Protocol):
    def __call__(self, snapshot: StabilitySnapshot) -> ResolvedStability | None: ...


MISSING_PREREQUISITES = (
    "The configured mechanical resolver did not supply canonical world poses and active support contacts",
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
    if resolver is None:
        # Local import keeps the snapshot type available to the pure adapter
        # without a runtime import cycle. No fixture resolver is installed here.
        from forma_stability.geometry import UnsupportedGeometry

        from forma_api.stability_geometry import (
            missing_mechanical_inputs,
            preview_geometry,
        )

        try:
            geometry = preview_geometry(snapshot)
        except UnsupportedGeometry as error:
            return StabilityAnalysisResponse(
                **fields, status="unsupported", blockers=(str(error),)
            )
        from forma_api.stability_measurements import measured_report

        report = measured_report(snapshot, geometry)
        if report is not None:
            status = "complete"
            if report.status == "needs_measurement":
                status = "needs_measurement"
            elif report.status in ("unsupported", "indeterminate"):
                status = "unsupported"
            return StabilityAnalysisResponse(
                **fields,
                status=status,
                report=report,
                blockers=report.unresolved_predicates,
            )
        return StabilityAnalysisResponse(
            **fields,
            status="needs_measurement",
            geometry_preview=geometry,
            blockers=missing_mechanical_inputs(geometry.active_part_ids),
        )
    resolved = resolver(snapshot)
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
