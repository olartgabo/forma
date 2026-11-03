"""Bounded repair search; results are previews approved through adapt/commit."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api import repair_search_runtime
from forma_api.projects import ProjectStore
from forma_api.repair_search_runtime import RepairSearchRequest, RepairSearchResult
from forma_domain.models import ID


def repair_search_router(store: ProjectStore, authenticate) -> APIRouter:
    router = APIRouter()
    Owner = Annotated[str, Depends(authenticate)]

    @router.post("/{project_id}/repairs/search", response_model=RepairSearchResult)
    def search(
        project_id: ID, body: RepairSearchRequest, owner: Owner, response: Response
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            scope = project_id + ":repair-search"
            digest, replay = store.replay(
                connection,
                owner,
                scope,
                body.idempotency_key,
                body.model_dump(mode="json"),
            )
            if replay is not None:
                return replay
            result = repair_search_runtime.search(connection, project, body)
            store.remember(
                connection, owner, scope, body.idempotency_key, digest, result
            )
            return result

    return router
