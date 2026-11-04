"""Durable, owner-scoped, single-dispatch SAM photo localization."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends

from forma_api import photo_localization as runtime
from forma_api.design_runtime import DesignErrorResponse
from forma_api.intake_runtime import MAX_PROVIDER_IMAGE_BYTES, SUPPORTED_IMAGE_TYPES
from forma_api.model_gateway import Box, GatewayError, ImageInput
from forma_api.projects import ProjectStore
from forma_api.provider_diagnostics import summarize_usage
from forma_api.routes.designs import DesignError, DesignRoute, _digest
from forma_domain.models import ID

_PENDING = json.dumps({"pending": True})
_UNKNOWN = json.dumps({"unknown": True})


def unknown():
    return DesignError(
        409,
        "generation_outcome_unknown",
        "SAM outcome is unknown. Keep this request identity; ask the operator to reconcile it before another SAM request. Manual boxes remain available.",
    )


class LocalizationRoute(DesignRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            response = await original(request)
            response.headers["Cache-Control"] = "no-store"
            return response

        return handle


def photo_localization_router(store: ProjectStore, authenticate):
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["photo-localization"], route_class=LocalizationRoute)

    @router.post(
        "/{project_id}/photo-localizations",
        response_model=runtime.PhotoLocalizationResult,
        responses={
            s: {"model": DesignErrorResponse}
            for s in (401, 404, 409, 413, 415, 422, 502, 503)
        },
    )
    def localize(project_id: ID, body: runtime.PhotoLocalizationRequest, owner: Owner):
        scope = project_id + ":photo-localization"
        digest = _digest(body.model_dump(mode="json"))
        identity = (owner, scope, body.idempotency_key)
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            row = connection.execute(
                "SELECT content_type, body, width_px, height_px FROM media WHERE id=? AND project_id=?",
                (body.media_id, project_id),
            ).fetchone()
            if row is None:
                raise DesignError(404, "not_found", "Photo not found")
            prior = connection.execute(
                "SELECT digest, response FROM requests WHERE owner=? AND scope=? AND key=?",
                identity,
            ).fetchone()
            if prior:
                if prior[0] != digest:
                    raise DesignError(
                        409,
                        "idempotency_conflict",
                        "Key already used for another request",
                    )
                if prior[1] == _UNKNOWN:
                    raise unknown()
                if prior[1] == _PENDING:
                    raise DesignError(
                        409,
                        "generation_in_progress",
                        "SAM request remains pending. Retry this exact request to check its receipt; do not dispatch another.",
                    )
                saved = json.loads(prior[1])
                if "terminal_error" in saved:
                    raise DesignError(*saved["terminal_error"])
                return runtime.PhotoLocalizationResult.model_validate(saved).model_copy(
                    update={"replayed": True}
                )
            if project.revision_id != body.expected_revision_id:
                raise DesignError(409, "stale_version", "Inventory changed; reload it")
            if not body.provider_transfer_consented:
                raise DesignError(
                    422,
                    "consent_required",
                    "Consent to send this photo and concept to Meta SAM is required",
                )
            content_type, data, width, height = row
            if content_type not in SUPPORTED_IMAGE_TYPES:
                raise DesignError(
                    415, "validation_error", "SAM requires a JPEG or PNG photo"
                )
            if not 0 < len(data) <= MAX_PROVIDER_IMAGE_BYTES:
                raise DesignError(
                    413,
                    "validation_error",
                    "SAM photos must contain 1 to 5000000 bytes",
                )
            outstanding = connection.execute(
                "SELECT response FROM requests WHERE owner=? AND scope=?",
                (owner, scope),
            ).fetchall()
            if any(r[0] == _UNKNOWN for r in outstanding):
                raise unknown()
            if any(r[0] == _PENDING for r in outstanding):
                raise DesignError(
                    409,
                    "generation_in_progress",
                    "Another SAM request remains pending; resolve it before starting another",
                )
            # Construct before reserving: configuration failure cannot be paid.
            try:
                gateway = runtime.default_gateway_factory()
                gateway.max_retries = 0
            except (GatewayError, ValueError, RuntimeError):
                raise DesignError(
                    503,
                    "provider_not_configured",
                    "SAM is not configured on the server",
                ) from None
            connection.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                (*identity, digest, _PENDING),
            )

        def settle(value):
            with store.transaction() as connection:
                cursor = connection.execute(
                    "UPDATE requests SET response=? WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                    (value, *identity, digest, _PENDING),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("receipt not confirmed")

        try:
            offset = len(gateway.traces)
            boxes = tuple(
                Box.model_validate(b)
                for b in gateway.segment(
                    ImageInput(bytes(data), content_type, True), body.concept
                )
            )
            if any(
                (b.width, b.height) != (width, height) or b.source != "sam"
                for b in boxes
            ):
                raise GatewayError("invalid_segmentation")
            result = runtime.PhotoLocalizationResult(
                project_id=project_id,
                revision_id=body.expected_revision_id,
                media_id=body.media_id,
                width_px=width,
                height_px=height,
                boxes=boxes,
                model=gateway.sam,
                usage=summarize_usage(gateway.traces[offset:]),
            )
        except GatewayError as exc:
            if exc.code in {"timeout", "network_error", "budget_exhausted"}:
                settle(_UNKNOWN)
                raise unknown() from None
            # Completed errors are terminal receipts too. Exact retries never pay again.
            error = (
                502,
                "invalid_response",
                "SAM did not return usable photo boxes. This request will not be sent again; use a manual box or explicitly start a new request.",
            )
            settle(json.dumps({"terminal_error": error}))
            raise DesignError(*error) from None
        except Exception:
            settle(_UNKNOWN)
            raise unknown() from None
        try:
            with store.transaction() as connection:
                current = store.read(connection, owner, project_id)
                media_exists = connection.execute(
                    "SELECT 1 FROM media WHERE id=? AND project_id=?",
                    (body.media_id, project_id),
                ).fetchone()
                stale = (
                    current.revision_id != body.expected_revision_id or not media_exists
                )
                error = (
                    409,
                    "stale_version",
                    "Project or photo changed during SAM localization; discard these boxes and reload",
                )
                value = (
                    json.dumps({"terminal_error": error})
                    if stale
                    else result.model_dump_json()
                )
                cursor = connection.execute(
                    "UPDATE requests SET response=? WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                    (value, *identity, digest, _PENDING),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("receipt not confirmed")
        except Exception:
            # A surviving pending receipt also blocks redispatch if settlement fails.
            try:
                settle(_UNKNOWN)
            except Exception:
                raise unknown() from None
            raise unknown() from None
        if stale:
            raise DesignError(*error)
        return result

    return router
