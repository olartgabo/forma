"""Live Muse repair-proposal route. Proposes only; never mutates state."""

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from forma_api import diagnosis_runtime, repair_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.plans import PlanService
from forma_api.progress import snapshot
from forma_api.projects import ProjectStore
from forma_domain.models import ID


class RepairError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.body = repair_runtime.RepairProposeErrorResponse(
            code=code, message=message
        )


class RepairRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def repair_route_handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                body = repair_runtime.RepairProposeErrorResponse(
                    code="validation_error", message="Request validation failed"
                )
                return JSONResponse(body.model_dump(mode="json"), status_code=422)
            except RepairError as exc:
                return JSONResponse(
                    exc.body.model_dump(mode="json"), status_code=exc.status
                )

        return repair_route_handler


def _provider_error(exc: GatewayError) -> RepairError:
    status, code, message = repair_runtime.gateway_error_details(exc.code)
    if (
        code
        not in repair_runtime.RepairProposeErrorResponse.model_fields[
            "code"
        ].annotation.__args__
    ):
        code = "provider_error"
    return RepairError(status, code, message)


def repairs_router(
    store: ProjectStore,
    authenticate,
    gateway_factory: Callable[[], MetaGateway] | None = None,
) -> APIRouter:
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["repairs"], route_class=RepairRoute)

    @router.post(
        "/{project_id}/repairs/propose",
        response_model=repair_runtime.RepairProposeResult,
        responses={
            status: {"model": repair_runtime.RepairProposeErrorResponse}
            for status in (404, 409, 422, 429, 502, 503, 504)
        },
    )
    def propose(
        project_id: ID,
        body: repair_runtime.RepairProposeRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            if project.active_version_id is None:
                raise RepairError(
                    409, "stale_version", "Project has no active plan; reload it"
                )
            if project.active_version_id != body.expected_version_id:
                raise RepairError(
                    409, "stale_version", "Active plan changed; reload it"
                )
            plan = (
                PlanService(store)
                .read(connection, project_id, body.expected_version_id)
                .plan
            )
            progress = snapshot(connection, plan)
            if progress.last_event_id != body.expected_last_event_id:
                raise RepairError(
                    409, "stale_version", "Physical history changed; reload it"
                )
            try:
                diagnosis_runtime.validate_diagnosis(body.diagnosis, plan=plan)
            except GatewayError:
                raise RepairError(
                    422,
                    "validation_error",
                    "Diagnosis references unknown plan items or is empty",
                ) from None
        if body.provider_context_consented is not True:
            raise RepairError(
                422,
                "consent_required",
                "Consent to share saved project context with the model provider is required",
            )
        factory = gateway_factory or repair_runtime.default_gateway_factory
        try:
            gateway = factory()
        except GatewayError as exc:
            raise _provider_error(exc) from None
        except ValueError:
            raise RepairError(
                503,
                "provider_not_configured",
                "Model provider is not configured on the server",
            ) from None
        context = repair_runtime.build_context(
            project_id=project_id,
            project_goal=project.goal,
            reported_problem=body.reported_problem,
            diagnosis=body.diagnosis,
            plan=plan,
            progress=progress,
        )
        try:
            proposals, diagnostics = repair_runtime.propose_repairs(
                gateway,
                context=context,
                plan=plan,
                expected_remaining_stock=progress.expected_remaining_stock,
            )
        except GatewayError as exc:
            raise _provider_error(exc) from None
        return repair_runtime.RepairProposeResult(
            project_id=project_id,
            base_version_id=plan.version_id,
            base_last_event_id=progress.last_event_id,
            candidates=proposals.candidates,
            questions=proposals.questions,
            diagnostics=diagnostics,
        )

    return router
