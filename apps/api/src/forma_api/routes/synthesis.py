"""Stock-feasible design search (#148). Search and probe write nothing."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api import synthesis_runtime as runtime
from forma_api.plans import PlanCompileResult
from forma_api.projects import ProjectStore
from forma_domain.models import ID
from forma_domain.synthesis_contracts import ProbeResult, SynthesisResult


def synthesis_router(store: ProjectStore, authenticate) -> APIRouter:
    router = APIRouter(tags=["synthesis"])
    Owner = Annotated[str, Depends(authenticate)]

    def resolver():
        return runtime.default_context_resolver()

    @router.post("/{project_id}/synthesis/search", response_model=SynthesisResult)
    def search(
        project_id: ID,
        body: runtime.SynthesisSearchRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        return runtime.run_search(store, owner, project_id, body, resolver())

    @router.post("/{project_id}/synthesis/probe", response_model=ProbeResult)
    def probe(
        project_id: ID,
        body: runtime.SynthesisProbeRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        return runtime.run_probe(store, owner, project_id, body, resolver())

    @router.post("/{project_id}/synthesis/select", response_model=PlanCompileResult)
    def select(
        project_id: ID,
        body: runtime.SynthesisSelectRequest,
        owner: Owner,
        response: Response,
    ):
        """Save the chosen design as a proposed preview; approval is separate."""
        response.headers["Cache-Control"] = "no-store"
        return runtime.run_select(
            store,
            owner,
            project_id,
            body,
            resolver(),
            runtime.default_plan_service(store),
        )

    return router
