"""Recognised-item card routes (#177 follow-up). No provider transfer."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api import recognized_items_runtime as runtime
from forma_api.projects import ProjectStore
from forma_domain.models import ID


def recognized_items_router(store: ProjectStore, authenticate) -> APIRouter:
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["recognized-items"])

    @router.get(
        "/{project_id}/recognized-items", response_model=runtime.RecognizedItems
    )
    def read(project_id: ID, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return runtime.read(store, owner, project_id)

    @router.put(
        "/{project_id}/recognized-items", response_model=runtime.RecognizedItems
    )
    def save(
        project_id: ID,
        body: runtime.RecognizedItemsUpdate,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        return runtime.save(store, owner, project_id, body)

    return router
