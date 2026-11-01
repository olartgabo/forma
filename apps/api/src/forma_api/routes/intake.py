"""Connected intake route: private photo to a read-only Muse observation."""

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from forma_api import intake_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.projects import ProjectStore
from forma_domain.models import ID


class IntakeError(Exception):
    """Intake-owned error; codes may exceed the domain ErrorEnvelope set."""

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.body = intake_runtime.IntakeErrorResponse(code=code, message=message)


async def _intake_error_handler(request: Request, exc: IntakeError):
    return JSONResponse(exc.body.model_dump(mode="json"), status_code=exc.status)


async def _validation_handler(request: Request, exc: RequestValidationError):
    # Registered via this router only; keep other routes' default behaviour.
    if request.url.path.endswith("/intake"):
        body = intake_runtime.IntakeErrorResponse(
            code="validation_error", message="Request validation failed"
        )
        return JSONResponse(body.model_dump(mode="json"), status_code=422)
    return await request_validation_exception_handler(request, exc)


def _provider_error(exc: GatewayError) -> IntakeError:
    status, code, message = intake_runtime.gateway_error_details(exc.code)
    return IntakeError(status, code, message)


def intake_router(
    store: ProjectStore,
    authenticate,
    gateway_factory: Callable[[], MetaGateway] | None = None,
) -> APIRouter:
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(
        tags=["intake"],
        exception_handlers={
            IntakeError: _intake_error_handler,
            RequestValidationError: _validation_handler,
        },
    )

    @router.post(
        "/{project_id}/intake",
        response_model=intake_runtime.IntakeResult,
    )
    def intake(project_id: ID, body: intake_runtime.IntakeRequest, owner: Owner):
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            row = connection.execute(
                "SELECT content_type, body FROM media WHERE id=? AND project_id=?",
                (body.media_id, project_id),
            ).fetchone()
            if row is None:
                raise IntakeError(404, "not_found", "Photo not found")
            content_type, image_data = row[0], bytes(row[1])
        if project.revision_id != body.expected_revision_id:
            raise IntakeError(409, "stale_version", "Inventory changed; reload it")
        if body.provider_transfer_consented is not True:
            raise IntakeError(
                422,
                "consent_required",
                "Consent to transfer this photo to the model provider is required",
            )
        if content_type not in intake_runtime.SUPPORTED_IMAGE_TYPES:
            raise IntakeError(
                415,
                "validation_error",
                "Intake requires a stored JPEG or PNG photo",
            )
        if not 0 < len(image_data) <= intake_runtime.MAX_PROVIDER_IMAGE_BYTES:
            raise IntakeError(
                413,
                "validation_error",
                "Photo must contain 1 to 5000000 bytes for provider transfer",
            )
        factory = gateway_factory or intake_runtime.default_gateway_factory
        try:
            gateway = factory()
        except GatewayError as exc:
            raise _provider_error(exc) from None
        except ValueError:
            raise IntakeError(
                503,
                "provider_not_configured",
                "Model provider is not configured on the server",
            ) from None
        try:
            observation, diagnostics = intake_runtime.observe_photo(
                gateway,
                project_goal=project.goal,
                image_data=image_data,
                content_type=content_type,
            )
        except GatewayError as exc:
            raise _provider_error(exc) from None
        with store.transaction() as connection:
            current = store.read(connection, owner, project_id)
            if current.revision_id != body.expected_revision_id:
                raise IntakeError(
                    409, "stale_version", "Inventory changed; reload it"
                )
            if (
                connection.execute(
                    "SELECT 1 FROM media WHERE id=? AND project_id=?",
                    (body.media_id, project_id),
                ).fetchone()
                is None
            ):
                raise IntakeError(404, "not_found", "Photo not found")
        return intake_runtime.IntakeResult(
            project_id=project_id,
            revision_id=current.revision_id,
            media_id=body.media_id,
            observation=observation,
            diagnostics=diagnostics,
        )

    return router
