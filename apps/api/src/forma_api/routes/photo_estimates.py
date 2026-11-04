"""Photo estimate routes (#177). Local computation; no provider transfer."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api import photo_measurement_runtime as runtime
from forma_api.projects import ProjectStore
from forma_domain.models import ID


def photo_estimates_router(store: ProjectStore, authenticate) -> APIRouter:
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["photo-estimates"])

    @router.post(
        "/{project_id}/photo-estimates", response_model=runtime.PhotoEstimateRecord
    )
    def create(
        project_id: ID,
        body: runtime.PhotoEstimateRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        return runtime.create(store, owner, project_id, body)

    @router.get(
        "/{project_id}/photo-estimates", response_model=runtime.PhotoEstimateList
    )
    def records(project_id: ID, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return runtime.list_records(store, owner, project_id)

    @router.post(
        "/{project_id}/photo-outline-suggestions",
        response_model=runtime.OutlineSuggestion,
    )
    def outline_suggestion(
        project_id: ID,
        body: runtime.OutlineSuggestionRequest,
        owner: Owner,
        response: Response,
    ):
        # Local and read-only; for when SAM finds no region.
        response.headers["Cache-Control"] = "no-store"
        return runtime.suggest(store, owner, project_id, body)

    return router


reference_router = APIRouter(tags=["photo-estimates"])


@reference_router.get("/photo-reference-card.svg", response_class=Response)
def reference_card():
    """Public printable card. Contains no project data."""

    return Response(runtime.card_payload(), media_type="image/svg+xml")
