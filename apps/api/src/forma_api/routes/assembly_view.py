"""Owner-scoped read-only assembly display snapshot."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api.assembly_view_runtime import assembly_view
from forma_api.plans import PlanService
from forma_api.progress import snapshot
from forma_api.projects import ProjectError, ProjectStore
from forma_api.stability_measurements import (
    digest,
    geometry_basis,
    latest_record,
    typed_evidence_ids,
)
from forma_api.stability_reports import SavedStabilityReport, dependencies, freshness
from forma_api.stability_runtime import StabilitySnapshot
from forma_domain.assembly_view_contracts import AssemblyViewResponse
from forma_domain.models import ID, Evidence, EvidenceInvalidation, PhysicalEvent


def assembly_view_router(store: ProjectStore, authenticate) -> APIRouter:
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["assembly-view"])

    @router.get("/{project_id}/assembly-view", response_model=AssemblyViewResponse)
    def view(
        project_id: ID,
        plan_version_id: ID,
        expected_inventory_revision_id: ID,
        expected_last_event_id: str,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            version = PlanService(store).read(connection, project_id, plan_version_id)
            if (
                project.active_version_id != plan_version_id
                or project.revision_id != expected_inventory_revision_id
            ):
                raise ProjectError(
                    409, "stale_version", "Plan or inventory changed; reload it"
                )
            events = tuple(
                PhysicalEvent.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT body FROM progress_events WHERE project_id=? ORDER BY rowid",
                    (project_id,),
                )
            )
            cursor = events[-1].id if events else None
            if cursor != (expected_last_event_id or None):
                raise ProjectError(
                    409, "stale_version", "Physical history changed; reload it"
                )
            evidence = tuple(
                Evidence.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT body FROM progress_evidence WHERE project_id=? ORDER BY rowid",
                    (project_id,),
                )
            )
            invalidations = tuple(
                EvidenceInvalidation.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT body FROM evidence_invalidations WHERE project_id=? ORDER BY rowid",
                    (project_id,),
                )
            )
            authorized = StabilitySnapshot(
                project,
                version,
                snapshot(connection, version.plan),
                cursor,
                events,
                evidence,
                invalidations,
                latest_record(connection, project_id, plan_version_id),
                typed_evidence_ids(connection, project_id, plan_version_id),
            )
            try:
                result = assembly_view(authorized)
                geometry = result.geometry
                measurement = authorized.measurements
                if geometry is None or measurement is None:
                    return result
                if (
                    measurement.project_id != project_id
                    or measurement.plan_version_id != plan_version_id
                    or measurement.inventory_revision_id != project.revision_id
                    or measurement.event_id != cursor
                    or measurement.geometry_basis_hash != geometry_basis(geometry)
                    or set(measurement.source_part_ids) != set(geometry.active_part_ids)
                ):
                    return result
                profiles_hash = digest(
                    [
                        profile.model_dump(mode="json")
                        for profile in version.plan.joint_profiles
                    ]
                )
                measured_cases = {
                    case.orientation for case in measurement.measurements.cases
                }
                for row in connection.execute(
                    "SELECT body FROM stability_reports WHERE project_id=? AND version_id=? ORDER BY rowid DESC LIMIT 50",
                    (project_id, plan_version_id),
                ):
                    saved = SavedStabilityReport.model_validate_json(row[0])
                    report = saved.report
                    identity = report.identity
                    cases = {
                        case.case_id: case.orientation
                        for case in saved.analysis_input.cases
                    }
                    if (
                        freshness(saved, project, cursor, invalidations).current
                        and saved.dependencies == dependencies()
                        and saved.project_id == project_id
                        and saved.report_id == "stability-report-" + report.cache_hash
                        and identity == saved.analysis_input.identity
                        and identity.project_id == project_id
                        and identity.plan_version_id == plan_version_id
                        and identity.inventory_revision == project.revision_id
                        and identity.history_cursor == cursor
                        and identity.canonical_geometry_hash == geometry.geometry_hash
                        and report.geometry_version == geometry.producer_version
                        and saved.analysis_input.geometry_version
                        == geometry.producer_version
                        and identity.operation_state_id == measurement.event_id
                        and identity.evidence_hash
                        == digest(measurement.model_dump(mode="json"))
                        and identity.profile_hash == profiles_hash
                        and set(cases) == measured_cases
                        and report.overlays
                        and all(
                            overlay.case_id in cases
                            and overlay.orientation == cases[overlay.case_id]
                            for overlay in report.overlays
                        )
                    ):
                        return AssemblyViewResponse.model_validate(
                            result.model_dump()
                            | {
                                "overlay_coverage": "available",
                                "overlay_report_id": saved.report_id,
                                "overlay_report": report,
                            }
                        )
                return result
            except ValueError:
                raise ProjectError(
                    422,
                    "validation_error",
                    "Assembly context is unavailable; use the SVG manual",
                ) from None

    return router
