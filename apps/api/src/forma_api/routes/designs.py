"""Authenticated Muse design generation route; approval stays separate."""

import hashlib
import json
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from forma_api import design_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.plans import PlanService
from forma_api.projects import ProjectError, ProjectStore
from forma_domain.models import ID

_PENDING = json.dumps({"pending": True})


class DesignError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.body = design_runtime.DesignErrorResponse(code=code, message=message)


class DesignRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def design_route_handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                body = design_runtime.DesignErrorResponse(
                    code="validation_error", message="Request validation failed"
                )
                return JSONResponse(body.model_dump(mode="json"), status_code=422)
            except DesignError as exc:
                return JSONResponse(
                    exc.body.model_dump(mode="json"), status_code=exc.status
                )

        return design_route_handler


def _provider_error(exc: GatewayError) -> DesignError:
    status, code, message = design_runtime.gateway_error_details(exc.code)
    # gateway codes map into DesignErrorResponse vocabulary.
    if (
        code
        not in design_runtime.DesignErrorResponse.model_fields[
            "code"
        ].annotation.__args__
    ):
        code = "provider_error"
    return DesignError(status, code, message)


def _digest(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def designs_router(
    store: ProjectStore,
    authenticate,
    gateway_factory: Callable[[], MetaGateway] | None = None,
    context_resolver=None,
    plan_service: PlanService | None = None,
) -> APIRouter:
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["designs"], route_class=DesignRoute)

    @router.post(
        "/{project_id}/designs/generate",
        response_model=design_runtime.DesignGenerateResult,
        responses={
            status: {"model": design_runtime.DesignErrorResponse}
            for status in (401, 404, 409, 422, 429, 502, 503, 504)
        },
    )
    def generate(
        project_id: ID, body: design_runtime.DesignGenerateRequest, owner: Owner
    ):
        scope = project_id + ":design-generation"
        # Short read; no transaction is held over provider or compile work.
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
        if project.revision_id != body.expected_revision_id:
            raise DesignError(409, "stale_version", "Inventory changed; reload it")
        if body.provider_context_consented is not True:
            raise DesignError(
                422,
                "consent_required",
                "Consent to share saved project context with the model provider is required",
            )
        if project.active_version_id is not None:
            raise ProjectError(409, "blocked", "Active plans require a revision")

        resolver = context_resolver or design_runtime.default_context_resolver()
        resolved = resolver(project_id, body.expected_revision_id)
        digest = _digest(
            {
                "request": body.model_dump(mode="json"),
                "context_fingerprint": resolved.fingerprint,
                "project_id": project_id,
            }
        )

        # Reserve request identity before any gateway dispatch.
        with store.transaction() as connection:
            current = store.read(connection, owner, project_id)
            if current.revision_id != body.expected_revision_id:
                raise DesignError(409, "stale_version", "Inventory changed; reload it")
            if current.active_version_id is not None:
                raise ProjectError(409, "blocked", "Active plans require a revision")
            row = connection.execute(
                "SELECT digest, response FROM requests WHERE owner=? AND scope=? AND key=?",
                (owner, scope, body.idempotency_key),
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ProjectError(
                        409,
                        "idempotency_conflict",
                        "Key already used for another request",
                    )
                if row[1] == _PENDING:
                    raise DesignError(
                        409,
                        "generation_in_progress",
                        "Design generation is already in progress for this request; check saved previews before retrying",
                    )
                replay = design_runtime.DesignGenerateResult.model_validate_json(row[1])
                return replay.model_copy(update={"replayed": True})
            count = connection.execute(
                "SELECT COUNT(*) FROM plans WHERE project_id=? AND inventory_revision_id=?",
                (project_id, current.revision_id),
            ).fetchone()[0]
            if count >= 2:
                raise ProjectError(
                    409, "blocked", "At most two designs per inventory revision"
                )
            connection.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                (owner, scope, body.idempotency_key, digest, _PENDING),
            )
            project = current

        def clear_pending():
            try:
                with store.transaction() as connection:
                    connection.execute(
                        "DELETE FROM requests WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                        (owner, scope, body.idempotency_key, digest, _PENDING),
                    )
            except Exception:
                pass

        factory = gateway_factory or design_runtime.default_gateway_factory
        try:
            gateway = factory()
        except GatewayError as exc:
            clear_pending()
            raise _provider_error(exc) from None
        except ValueError:
            clear_pending()
            raise DesignError(
                503,
                "provider_not_configured",
                "Model provider is not configured on the server",
            ) from None
        service = plan_service or design_runtime.default_plan_service(store)
        try:
            result = design_runtime.generate_designs(
                gateway,
                store=store,
                owner=owner,
                project=project,
                resolved=resolved,
                user_notes=body.user_notes,
                plan_service=service,
                idempotency_key=body.idempotency_key,
            )
        except GatewayError as exc:
            clear_pending()
            raise _provider_error(exc) from None
        except ProjectError:
            clear_pending()
            raise

        # Recheck scope/revision before remembering; deletion must not resurrect.
        try:
            with store.transaction() as connection:
                current = store.read(connection, owner, project_id)
                if current.revision_id != body.expected_revision_id:
                    raise DesignError(
                        409, "stale_version", "Inventory changed; reload it"
                    )
                if current.active_version_id is not None:
                    raise ProjectError(
                        409, "blocked", "Active plans require a revision"
                    )
                cursor = connection.execute(
                    "UPDATE requests SET response=? WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                    (
                        result.model_dump_json(),
                        owner,
                        scope,
                        body.idempotency_key,
                        digest,
                        _PENDING,
                    ),
                )
                if cursor.rowcount != 1:
                    raise DesignError(
                        409,
                        "generation_in_progress",
                        "Design generation result could not be confirmed; check saved previews before retrying",
                    )
        except (DesignError, ProjectError):
            clear_pending()
            raise
        return result

    return router
