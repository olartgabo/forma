"""Owner-scoped, read-only, active-plan stability analysis."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from forma_api import stability_reports as reports
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
            authorized = reports.authorized_snapshot(
                connection, store, owner, project_id, body
            )
            return reports.evaluate(authorized, resolver).response

    @router.post(
        "/{project_id}/stability/reports",
        response_model=reports.StabilityReportSaveResponse,
    )
    def save_report(
        project_id: ID,
        body: reports.StabilityReportSaveRequest,
        owner: Owner,
        response: Response,
    ):
        """Calculate on the authorized snapshot and save the immutable report."""
        response.headers["Cache-Control"] = "no-store"
        scope = project_id + ":stability-reports"
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            hashed, replay = store.replay(
                connection,
                owner,
                scope,
                body.idempotency_key,
                body.model_dump(mode="json"),
            )
            if replay is not None:
                return reports.StabilityReportSaveResponse.model_validate(replay)
            authorized = reports.authorized_snapshot(
                connection, store, owner, project_id, body
            )
            evaluation = reports.evaluate(authorized, resolver)
            record = reports.build_record(evaluation, "builder")
            saved, cached = None, False
            if record is not None:
                record, cached = reports.store_record(connection, record)
                saved = reports.ProjectState(
                    connection, store, owner, project_id
                ).summary(record)
            result = reports.StabilityReportSaveResponse(
                analysis=evaluation.response, saved=saved, cached=cached
            )
            store.remember(
                connection,
                owner,
                scope,
                body.idempotency_key,
                hashed,
                result.model_dump(mode="json"),
            )
            return result

    @router.get(
        "/{project_id}/stability/reports",
        response_model=reports.StabilityReportHistory,
    )
    def report_history(
        project_id: ID,
        owner: Owner,
        response: Response,
        plan_version_id: ID | None = None,
        limit: Annotated[int, Query(ge=1, le=reports.HISTORY_LIMIT)] = (
            reports.HISTORY_LIMIT
        ),
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            return reports.history(
                connection, store, owner, project_id, plan_version_id, limit
            )

    @router.get(
        "/{project_id}/stability/reports/{report_id}",
        response_model=reports.StabilityReportDetail,
    )
    def report_detail(project_id: ID, report_id: ID, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            return reports.detail(connection, store, owner, project_id, report_id)

    @router.get(
        "/{project_id}/stability/report-comparison",
        response_model=reports.StabilityReportComparison,
    )
    def report_comparison(
        project_id: ID, first: ID, second: ID, owner: Owner, response: Response
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            return reports.compare(connection, store, owner, project_id, first, second)

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
