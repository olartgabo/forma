"""Read-only fabrication reports for the active plan and saved repair previews."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api import fabrication_runtime
from forma_api.projects import ProjectStore
from forma_domain.fabrication_contracts import FabricationReport
from forma_domain.models import ID


def fabrication_router(store: ProjectStore, authenticate) -> APIRouter:
    router = APIRouter()
    Owner = Annotated[str, Depends(authenticate)]

    @router.get(
        "/{project_id}/versions/{version_id}/fabrication",
        response_model=FabricationReport,
    )
    def version_report(
        project_id: ID, version_id: ID, owner: Owner, response: Response
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            return fabrication_runtime.active_report(connection, project, version_id)

    @router.post(
        "/{project_id}/versions/{version_id}/fabrication/assess",
        response_model=FabricationReport,
    )
    def assess_version(
        project_id: ID,
        version_id: ID,
        body: fabrication_runtime.FabricationAssessment,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            return fabrication_runtime.assess_active(
                connection, project, version_id, body
            )

    @router.get(
        "/{project_id}/adapt/previews/{preview_id}/fabrication",
        response_model=FabricationReport,
    )
    def preview_report(
        project_id: ID, preview_id: ID, owner: Owner, response: Response
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            return fabrication_runtime.preview_report(connection, project, preview_id)

    return router
