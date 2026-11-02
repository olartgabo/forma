"""Connected diagnosis route: saved private photo to read-only Muse diagnosis."""

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from forma_api import diagnosis_runtime, intake_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.plans import PlanService
from forma_api.progress import record_diagnosis_evidence
from forma_api.projects import ProjectStore
from forma_domain.models import ID


class DiagnosisError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.body = diagnosis_runtime.DiagnosisErrorResponse(code=code, message=message)


class DiagnosisRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def diagnosis_route_handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                body = diagnosis_runtime.DiagnosisErrorResponse(
                    code="validation_error", message="Request validation failed"
                )
                return JSONResponse(body.model_dump(mode="json"), status_code=422)
            except DiagnosisError as exc:
                return JSONResponse(
                    exc.body.model_dump(mode="json"), status_code=exc.status
                )

        return diagnosis_route_handler


def _provider_error(exc: GatewayError) -> DiagnosisError:
    status, code, message = diagnosis_runtime.gateway_error_details(exc.code)
    if (
        code
        not in diagnosis_runtime.DiagnosisErrorResponse.model_fields[
            "code"
        ].annotation.__args__
    ):
        code = "provider_error"
    return DiagnosisError(status, code, message)


def _load_plan(store: ProjectStore, connection, project_id: str, version_id: str):
    return PlanService(store).read(connection, project_id, version_id)


def _resolve_operation(plan, operation_id: str):
    operation = next(
        (item for item in plan.operations if item.id == operation_id), None
    )
    if operation is None:
        raise DiagnosisError(
            422,
            "validation_error",
            "Current operation does not belong to the active plan",
        )
    return operation


def diagnosis_router(
    store: ProjectStore,
    authenticate,
    gateway_factory: Callable[[], MetaGateway] | None = None,
) -> APIRouter:
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["diagnosis"], route_class=DiagnosisRoute)

    @router.post(
        "/{project_id}/diagnose",
        response_model=diagnosis_runtime.DiagnosisResult,
        responses={
            status: {"model": diagnosis_runtime.DiagnosisErrorResponse}
            for status in (404, 409, 413, 415, 422, 429, 502, 503, 504)
        },
    )
    def diagnose(
        project_id: ID, body: diagnosis_runtime.DiagnosisRequest, owner: Owner
    ):
        plan = None
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            row = connection.execute(
                "SELECT content_type, body FROM media WHERE id=? AND project_id=?",
                (body.media_id, project_id),
            ).fetchone()
            if row is None:
                raise DiagnosisError(404, "not_found", "Photo not found")
            content_type, image_data = row[0], bytes(row[1])
            if body.expected_active_version_id is not None:
                if project.active_version_id != body.expected_active_version_id:
                    raise DiagnosisError(
                        409, "stale_version", "Active plan changed; reload it"
                    )
                version = _load_plan(
                    store, connection, project_id, body.expected_active_version_id
                )
                plan = version.plan
                _resolve_operation(plan, body.current_operation_id)
        if project.revision_id != body.expected_revision_id:
            raise DiagnosisError(409, "stale_version", "Inventory changed; reload it")
        if body.provider_transfer_consented is not True:
            raise DiagnosisError(
                422,
                "consent_required",
                "Consent to transfer this photo to the model provider is required",
            )
        if content_type not in intake_runtime.SUPPORTED_IMAGE_TYPES:
            raise DiagnosisError(
                415,
                "validation_error",
                "Diagnosis requires a stored JPEG or PNG photo",
            )
        if not 0 < len(image_data) <= intake_runtime.MAX_PROVIDER_IMAGE_BYTES:
            raise DiagnosisError(
                413,
                "validation_error",
                "Photo must contain 1 to 5000000 bytes for provider transfer",
            )
        factory = gateway_factory or diagnosis_runtime.default_gateway_factory
        try:
            gateway = factory()
        except GatewayError as exc:
            raise _provider_error(exc) from None
        except ValueError:
            raise DiagnosisError(
                503,
                "provider_not_configured",
                "Model provider is not configured on the server",
            ) from None
        context = diagnosis_runtime.build_context(
            project_id=project_id,
            revision_id=project.revision_id,
            project_goal=project.goal,
            reported_problem=body.reported_problem,
            stocks=project.stocks,
            plan=plan,
            current_operation_id=body.current_operation_id,
        )
        try:
            proposal, diagnostics = diagnosis_runtime.diagnose_photo(
                gateway,
                image_data=image_data,
                content_type=content_type,
                context=context,
                plan=plan,
            )
        except GatewayError as exc:
            raise _provider_error(exc) from None
        with store.transaction() as connection:
            current = store.read(connection, owner, project_id)
            if current.revision_id != body.expected_revision_id:
                raise DiagnosisError(
                    409, "stale_version", "Inventory changed; reload it"
                )
            if (
                connection.execute(
                    "SELECT 1 FROM media WHERE id=? AND project_id=?",
                    (body.media_id, project_id),
                ).fetchone()
                is None
            ):
                raise DiagnosisError(404, "not_found", "Photo not found")
            if body.expected_active_version_id is not None:
                if current.active_version_id != body.expected_active_version_id:
                    raise DiagnosisError(
                        409, "stale_version", "Active plan changed; reload it"
                    )
                version = _load_plan(
                    store, connection, project_id, body.expected_active_version_id
                )
                _resolve_operation(version.plan, body.current_operation_id)
                part_id_set = {part.id for part in version.plan.parts}
                record_diagnosis_evidence(
                    connection,
                    project_id=project_id,
                    version_id=body.expected_active_version_id,
                    operation_id=body.current_operation_id,
                    media_id=body.media_id,
                    diagnosis=proposal,
                    part_ids=tuple(
                        item for item in proposal.affected_ids if item in part_id_set
                    ),
                )
            # A photo-only request stays valid if a plan was activated during
            # the call; the revision and media checks above are its stale gates.
        return diagnosis_runtime.DiagnosisResult(
            project_id=project_id,
            revision_id=current.revision_id,
            media_id=body.media_id,
            active_version_id=body.expected_active_version_id,
            current_operation_id=body.current_operation_id,
            diagnosis=proposal,
            diagnostics=diagnostics,
        )

    return router
