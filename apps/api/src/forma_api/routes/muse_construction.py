"""Consented model proposals with saved materials and durable dispatch receipts."""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api import design_context, design_runtime, muse_construction
from forma_api.intake_runtime import MAX_PROVIDER_IMAGE_BYTES, SUPPORTED_IMAGE_TYPES
from forma_api.model_gateway import GatewayError, ImageInput
from forma_api.projects import ProjectError, ProjectStore
from forma_api.routes.designs import (
    _PENDING,
    _UNCERTAIN_CODES,
    DesignError,
    DesignRoute,
    _digest,
    _is_uncertain,
    _provider_error,
    _uncertain_marker,
)
from forma_domain.models import ID


def _current(project, revision):
    if project.revision_id != revision:
        raise DesignError(409, "stale_version", "Inventory changed; reload it")
    if project.active_version_id is not None:
        raise DesignError(
            409, "blocked", "Active builds require the fabrication and repair flow"
        )


def _photo(connection, project_id, media_id):
    if media_id is None:
        return None
    row = connection.execute(
        "SELECT content_type, body FROM media WHERE id=? AND project_id=?",
        (media_id, project_id),
    ).fetchone()
    if row is None:
        raise DesignError(404, "not_found", "Photo not found")
    mime, data = row[0], bytes(row[1])
    if mime not in SUPPORTED_IMAGE_TYPES:
        raise DesignError(415, "validation_error", "Choose a stored JPEG or PNG photo")
    if not 0 < len(data) <= MAX_PROVIDER_IMAGE_BYTES:
        raise DesignError(
            413, "validation_error", "Photo exceeds provider transfer limits"
        )
    return mime, data


def _photo_hash(photo):
    return (
        None
        if photo is None
        else hashlib.sha256(photo[0].encode() + photo[1]).hexdigest()
    )


def muse_construction_router(
    store: ProjectStore, authenticate, gateway_factory=None, context_resolver=None
):
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["construction-proposals"], route_class=DesignRoute)

    @router.post(
        "/{project_id}/construction/propose",
        response_model=muse_construction.MuseConstructionResult,
        responses={
            status: {"model": design_runtime.DesignErrorResponse}
            for status in (401, 404, 409, 413, 415, 422, 429, 502, 503, 504)
        },
    )
    def propose(
        project_id: ID,
        body: muse_construction.MuseConstructionRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            _current(project, body.expected_revision_id)
            photo = _photo(connection, project_id, body.media_id)
        if not body.provider_context_consented:
            raise DesignError(
                422,
                "consent_required",
                "Consent to share the saved goal and materials with MetaMuse is required",
            )
        if photo is not None and not body.provider_transfer_consented:
            raise DesignError(
                422,
                "consent_required",
                "Consent to send the selected photo to MetaMuse is required",
            )
        resolver = context_resolver or design_context.default_context_resolver()
        resolved = resolver(project_id, project.revision_id)
        photo_hash = _photo_hash(photo)
        digest = _digest(
            {
                "request": body.model_dump(mode="json"),
                "project_id": project_id,
                "context_fingerprint": resolved.fingerprint,
                "photo_hash": photo_hash,
            }
        )
        scope = project_id + ":construction-proposal"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            _current(project, body.expected_revision_id)
            if _photo_hash(_photo(connection, project_id, body.media_id)) != photo_hash:
                raise DesignError(409, "stale_version", "Photo changed; reload it")
            row = connection.execute(
                "SELECT digest, response FROM requests WHERE owner=? AND scope=? AND key=?",
                (owner, scope, body.idempotency_key),
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise DesignError(
                        409,
                        "idempotency_conflict",
                        "Key already used for another request",
                    )
                if _is_uncertain(row[1]):
                    raise DesignError(
                        409,
                        "generation_outcome_unknown",
                        "The prior provider outcome is unknown; reconcile it before another request",
                    )
                if row[1] == _PENDING:
                    raise DesignError(
                        409,
                        "generation_in_progress",
                        "Construction proposal is already in progress",
                    )
                result = muse_construction.MuseConstructionResult.model_validate_json(
                    row[1]
                )
                return result.model_copy(update={"replayed": True})
            # Changing a retry key must never bypass an unresolved paid dispatch.
            outstanding = connection.execute(
                "SELECT response FROM requests WHERE owner=? AND scope=?",
                (owner, scope),
            ).fetchall()
            if any(_is_uncertain(r[0]) for r in outstanding):
                raise DesignError(
                    409,
                    "generation_outcome_unknown",
                    "A previous provider outcome is unknown; reconcile it before another request",
                )
            if any(r[0] == _PENDING for r in outstanding):
                raise DesignError(
                    409,
                    "generation_in_progress",
                    "Another construction proposal is already in progress",
                )
            connection.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                (owner, scope, body.idempotency_key, digest, _PENDING),
            )

        def clear_pending():
            with store.transaction() as connection:
                connection.execute(
                    "DELETE FROM requests WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                    (owner, scope, body.idempotency_key, digest, _PENDING),
                )

        def mark_uncertain(code):
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE requests SET response=? WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                    (
                        _uncertain_marker(code),
                        owner,
                        scope,
                        body.idempotency_key,
                        digest,
                        _PENDING,
                    ),
                )

        try:
            gateway = (gateway_factory or design_runtime.default_gateway_factory)()
        except GatewayError as exc:
            clear_pending()
            raise _provider_error(exc) from None
        except (ValueError, RuntimeError):
            clear_pending()
            raise DesignError(
                503,
                "provider_not_configured",
                "Model provider is not configured on the server",
            ) from None
        try:
            result = muse_construction.generate_muse_construction(
                gateway,
                project=project,
                resolved=resolved,
                user_notes=body.user_notes,
                image=ImageInput(data=photo[1], mime=photo[0], consented=True)
                if photo
                else None,
            )
        except GatewayError as exc:
            if exc.code in _UNCERTAIN_CODES:
                mark_uncertain(_provider_error(exc).body.code)
                raise DesignError(
                    409,
                    "generation_outcome_unknown",
                    "The provider outcome could not be confirmed. Keep this request identity and reconcile it before another request.",
                ) from None
            clear_pending()
            raise _provider_error(exc) from None
        except Exception:
            mark_uncertain("server_error")
            raise DesignError(
                409,
                "generation_outcome_unknown",
                "The construction result could not be confirmed. Keep this request identity and reconcile it before another request.",
            ) from None
        try:
            latest_context = resolver(project_id, project.revision_id)
            if latest_context.fingerprint != resolved.fingerprint:
                raise DesignError(
                    409, "stale_version", "Material process context changed; reload it"
                )
            with store.transaction() as connection:
                current = store.read(connection, owner, project_id)
                _current(current, body.expected_revision_id)
                if (
                    _photo_hash(_photo(connection, project_id, body.media_id))
                    != photo_hash
                ):
                    raise DesignError(409, "stale_version", "Photo changed; reload it")
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
                        "generation_outcome_unknown",
                        "The result receipt could not be confirmed",
                    )
        except (DesignError, ProjectError) as exc:
            mark_uncertain(
                exc.body.code if isinstance(exc, DesignError) else exc.envelope.code
            )
            raise DesignError(
                409,
                "generation_outcome_unknown",
                "The provider returned, but the project, photo, material context or result receipt could no longer be confirmed. Keep this request identity and reconcile it before another request.",
            ) from None
        except Exception:
            mark_uncertain("result_not_confirmed")
            raise DesignError(
                409,
                "generation_outcome_unknown",
                "The proposal result could not be confirmed. Keep this request identity and reconcile it before another request.",
            ) from None
        return result

    return router
