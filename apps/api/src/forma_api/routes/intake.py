"""Connected intake route: private photo to a read-only Muse observation."""

from typing import Annotated, Callable

from fastapi import APIRouter, Depends

from forma_api import intake_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.projects import ProjectError, ProjectStore
from forma_domain.models import ID


def _provider_error(exc: GatewayError) -> ProjectError:
    status, code, message = intake_runtime.gateway_error_details(exc.code)
    return ProjectError(status, code, message)


def intake_router(
    store: ProjectStore,
    authenticate,
    gateway_factory: Callable[[], MetaGateway] | None = None,
) -> APIRouter:
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["intake"])

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
                raise ProjectError(404, "not_found", "Photo not found")
            content_type, image_data = row[0], bytes(row[1])
        if project.revision_id != body.expected_revision_id:
            raise ProjectError(409, "stale_version", "Inventory changed; reload it")
        if body.provider_transfer_consented is not True:
            raise ProjectError(
                422,
                "consent_required",
                "Consent to transfer this photo to the model provider is required",
            )
        if content_type not in intake_runtime.SUPPORTED_IMAGE_TYPES:
            raise ProjectError(
                415,
                "validation_error",
                "Intake requires a stored JPEG or PNG photo",
            )
        if not 0 < len(image_data) <= intake_runtime.MAX_PROVIDER_IMAGE_BYTES:
            raise ProjectError(
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
            raise ProjectError(
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
                raise ProjectError(
                    409, "stale_version", "Inventory changed; reload it"
                )
            if (
                connection.execute(
                    "SELECT 1 FROM media WHERE id=? AND project_id=?",
                    (body.media_id, project_id),
                ).fetchone()
                is None
            ):
                raise ProjectError(404, "not_found", "Photo not found")
        return intake_runtime.IntakeResult(
            project_id=project_id,
            revision_id=current.revision_id,
            media_id=body.media_id,
            observation=observation,
            diagnostics=diagnostics,
        )

    return router
