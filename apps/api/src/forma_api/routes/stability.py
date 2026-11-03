"""Owner-scoped, read-only, active-plan stability analysis."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api import stability_runtime as runtime
from forma_api.plans import PlanService
from forma_api.progress import snapshot
from forma_api.projects import ProjectError, ProjectStore
from forma_api.stability_measurements import (
    StabilityMeasurementRequest,
    StabilityMeasurementResponse,
    latest_record,
    save_measurements,
    typed_evidence_ids,
)
from forma_api.stability_stages import (
    StageAnalysisRequest,
    StageAnalysisResponse,
    analyze_stage,
)
from forma_domain.models import ID, Evidence, EvidenceInvalidation, PhysicalEvent


def stability_router(store: ProjectStore, authenticate, resolver=None) -> APIRouter:
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["stability"])

    @router.get(
        "/{project_id}/stability/context", response_model=runtime.StabilityContext
    )
    def context(project_id: ID, plan_version_id: ID, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            PlanService(store).read(connection, project_id, plan_version_id)
            if project.active_version_id != plan_version_id:
                raise ProjectError(
                    409, "stale_version", "Active plan changed; reload it"
                )
            row = connection.execute(
                "SELECT id FROM progress_events WHERE project_id=? ORDER BY rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            return runtime.StabilityContext(
                project_id=project_id,
                plan_version_id=plan_version_id,
                inventory_revision_id=project.revision_id,
                last_event_id=row[0] if row else None,
            )

    @router.post(
        "/{project_id}/stability/analyses",
        response_model=runtime.StabilityAnalysisResponse,
    )
    def analyze(
        project_id: ID,
        body: runtime.StabilityAnalysisRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            version = PlanService(store).read(
                connection, project_id, body.plan_version_id
            )
            if project.revision_id != body.expected_inventory_revision_id:
                raise ProjectError(409, "stale_version", "Inventory changed; reload it")
            if project.active_version_id != body.plan_version_id:
                raise ProjectError(
                    409, "stale_version", "Active plan changed; reload it"
                )
            current = snapshot(connection, version.plan)
            events = tuple(
                PhysicalEvent.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT body FROM progress_events WHERE project_id=? ORDER BY rowid",
                    (project_id,),
                )
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
            cursor = events[-1].id if events else None
            if cursor != body.expected_last_event_id:
                raise ProjectError(
                    409, "stale_version", "Physical history changed; reload it"
                )
            authorized = runtime.StabilitySnapshot(
                project,
                version,
                current,
                cursor,
                events,
                evidence,
                invalidations,
                latest_record(connection, project_id, version.version_id),
                typed_evidence_ids(connection, project_id, version.version_id),
            )
            try:
                return runtime.analyze(authorized, resolver)
            except ValueError:
                raise ProjectError(
                    422,
                    "validation_error",
                    "Server stability context does not match the authorized snapshot",
                ) from None

    @router.post(
        "/{project_id}/stability/measurements",
        response_model=StabilityMeasurementResponse,
    )
    def measurements(
        project_id: ID,
        body: StabilityMeasurementRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            version = PlanService(store).read(
                connection, project_id, body.plan_version_id
            )
            events = tuple(
                PhysicalEvent.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT body FROM progress_events WHERE project_id=? ORDER BY rowid",
                    (project_id,),
                )
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
            cursor = events[-1].id if events else None
            authorized = runtime.StabilitySnapshot(
                project,
                version,
                snapshot(connection, version.plan),
                cursor,
                events,
                evidence,
                invalidations,
                latest_record(connection, project_id, version.version_id),
                typed_evidence_ids(connection, project_id, version.version_id),
            )
            return save_measurements(connection, store, owner, authorized, body)

    @router.post(
        "/{project_id}/stability/stage-analyses", response_model=StageAnalysisResponse
    )
    def stage_analysis(
        project_id: ID, body: StageAnalysisRequest, owner: Owner, response: Response
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            version = PlanService(store).read(
                connection, project_id, body.plan_version_id
            )
            current = snapshot(connection, version.plan)
            row = connection.execute(
                "SELECT id FROM progress_events WHERE project_id=? ORDER BY rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            invalidations = tuple(
                EvidenceInvalidation.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT body FROM evidence_invalidations WHERE project_id=? ORDER BY rowid",
                    (project_id,),
                )
                if EvidenceInvalidation.model_validate_json(
                    row[0]
                ).invalidated_for_version_id
                == version.version_id
            )
            return analyze_stage(
                project, version, current, row[0] if row else None, body, invalidations
            )

    return router
