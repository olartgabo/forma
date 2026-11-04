"""Owner-scoped read-only assembly display snapshot."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api.assembly_view_runtime import assembly_view
from forma_api.plans import PlanService
from forma_api.progress import snapshot
from forma_api.projects import ProjectError, ProjectStore
from forma_api.stability_measurements import latest_record, typed_evidence_ids
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
                return assembly_view(authorized)
            except ValueError:
                raise ProjectError(
                    422,
                    "validation_error",
                    "Assembly context is unavailable; use the SVG manual",
                ) from None

    return router
