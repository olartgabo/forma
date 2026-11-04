"""Measurement decisions (#149). Deciding and recalculating write nothing."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api import measurement_runtime as runtime
from forma_api.projects import ProjectStore
from forma_domain.measurement_contracts import DecisionChange, MeasurementDecision
from forma_domain.models import ID


def measurement_router(store: ProjectStore, authenticate) -> APIRouter:
    router = APIRouter(tags=["measurement"])
    Owner = Annotated[str, Depends(authenticate)]

    @router.post(
        "/{project_id}/measurement-decisions", response_model=MeasurementDecision
    )
    def decide(
        project_id: ID,
        body: runtime.DecisionRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        return runtime.decide(
            store, owner, project_id, body, runtime.default_context_resolver()
        )

    @router.post(
        "/{project_id}/measurement-decisions/unavailable",
        response_model=MeasurementDecision,
    )
    def unavailable(
        project_id: ID,
        body: runtime.UnavailableRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        return runtime.mark_unavailable(
            store, owner, project_id, body, runtime.default_context_resolver()
        )

    @router.post(
        "/{project_id}/measurement-decisions/recalculate",
        response_model=DecisionChange,
    )
    def recalculate(
        project_id: ID,
        body: runtime.RecalculateRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        return runtime.recalculate(
            store, owner, project_id, body, runtime.default_context_resolver()
        )

    return router
