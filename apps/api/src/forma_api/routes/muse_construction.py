"""Consented model proposals with saved materials and durable dispatch receipts."""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api import design_context, design_runtime, muse_construction
from forma_api.intake_runtime import MAX_PROVIDER_IMAGE_BYTES, SUPPORTED_IMAGE_TYPES
from forma_api.model_gateway import (
    MODEL_ID_RE,
    GatewayError,
    ImageInput,
    ProposalBudget,
)
from forma_api.projects import ProjectError, ProjectStore
from forma_api.provider_diagnostics import summarize_usage
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


def _replacement_rows(connection, owner, project_id):
    # Legacy read-only databases may predate the append-only authorization table.
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='construction_replacements'"
    ).fetchone():
        return []
    return connection.execute(
        "SELECT original_key, original_digest, replacement_key, revision_id FROM construction_replacements "
        "WHERE owner=? AND project_id=? ORDER BY rowid",
        (owner, project_id),
    ).fetchall()


def _ancestors(key, rows, requests):
    """Only the latest grant for each original may authorize a successor.

    All original digests and unknown states must still match. No request is
    edited by this traversal, including an unknown ancestor's usage evidence.
    """
    latest = {r[0]: r for r in rows}
    incoming = {r[2]: r for r in rows}
    found = set()
    while key in incoming:
        row = incoming[key]
        original, digest, _, _ = row
        saved = requests.get(original)
        if (
            latest.get(original) != row
            or original in found
            or saved is None
            or saved[0] != digest
            or not _is_uncertain(saved[1])
        ):
            raise DesignError(
                409,
                "blocked",
                "Replacement authorization no longer matches its original request",
            )
        found.add(original)
        key = original
    return found


def _current(project, revision):
    if project.revision_id != revision:
        raise DesignError(409, "stale_version", "Inventory changed; reload it")
    if project.active_version_id is not None:
        raise DesignError(
            409, "blocked", "Active builds require the fabrication and repair flow"
        )


def _completed_ancestors(rows, requests, project_id):
    """Exempt historical unknowns only behind a validated completed successor.

    No ancestor receipt or unknown usage is changed. Pending, unknown, corrupt
    and superseded successors cannot establish completion of the authorized chain.
    """
    historical = set()
    for key, revision in {row[2]: row[3] for row in rows}.items():
        if key not in requests:
            continue
        _, saved = requests[key]
        if saved == _PENDING or _is_uncertain(saved):
            continue
        try:
            result = muse_construction.MuseConstructionResult.model_validate_json(saved)
            if (
                result.project_id == project_id
                and result.inventory_revision_id == revision
            ):
                historical.update(_ancestors(key, rows, requests))
        except (ValueError, DesignError):
            continue
    return historical


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


def _failure_evidence(budget, stage):
    """Private receipt metadata, never prompts, provider bodies or exception text.

    These are observed transport attempts, not confirmed provider dispatches or
    billing. Missing traces cannot establish that no provider call occurred.
    """

    def count(value, maximum):
        return value if type(value) is int and 0 <= value <= maximum else None

    attempts = []
    for trace in budget.traces[:16]:
        attempts.append(
            dict(
                endpoint=trace.endpoint
                if trace.endpoint in ("/chat/completions", "/responses")
                else "unknown",
                model=trace.model
                if isinstance(trace.model, str) and MODEL_ID_RE.fullmatch(trace.model)
                else "unknown",
                status=trace.status
                if trace.status
                in {
                    "ok",
                    "timeout",
                    "network_error",
                    "budget_exhausted",
                    "invalid_response",
                    "response_too_large",
                    "rate_limit",
                    "provider_http_error",
                    "authentication",
                    "access_denied",
                }
                else "unknown",
                elapsed_ms=count(trace.elapsed_ms, 86_400_000),
                input_tokens=count(trace.input_tokens, 10**9),
                output_tokens=count(trace.output_tokens, 10**9),
            )
        )
    return dict(
        stage=stage,
        observed_attempt_count=len(attempts) if attempts else None,
        attempts=attempts,
        usage=summarize_usage(attempts).model_dump(mode="json") if attempts else None,
    )


def muse_construction_router(
    store: ProjectStore, authenticate, gateway_factory=None, context_resolver=None
):
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["construction-proposals"], route_class=DesignRoute)

    @router.get(
        "/{project_id}/construction/receipts",
        response_model=muse_construction.MuseConstructionReceipts,
    )
    def receipt_list(project_id: ID, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        database = (store.directory / "projects.sqlite3").resolve()
        if not database.is_file():
            raise DesignError(404, "not_found", "Project not found")
        # Opening SQLite read-only also prevents receipt inspection from
        # initializing tables or changing unknown legacy records.
        with closing(
            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        ) as connection:
            connection.execute("BEGIN")
            store.read(connection, owner, project_id)
            rows = connection.execute(
                "SELECT key, digest, response FROM requests WHERE owner=? AND scope=? ORDER BY rowid DESC LIMIT 16",
                (owner, project_id + ":construction-proposal"),
            ).fetchall()
            replacements = _replacement_rows(connection, owner, project_id)
        outgoing = {r[0]: r for r in replacements}
        incoming = {r[2]: r for r in replacements}
        receipts = []
        safe_codes = {
            "timeout",
            "network_error",
            "budget_exhausted",
            "server_error",
            "result_not_confirmed",
            "stale_version",
            "blocked",
            "not_found",
            "generation_outcome_unknown",
        }
        for key, digest, saved in rows:
            state, code = "unknown", "result_not_confirmed"
            try:
                value = json.loads(saved)
                if isinstance(value, dict) and value.get("uncertain") is True:
                    code = value.get("error_code")
                    code = (
                        code if isinstance(code, str) and code in safe_codes else None
                    )
                elif saved == _PENDING:
                    state, code = "pending", None
                else:
                    result = muse_construction.MuseConstructionResult.model_validate(
                        value
                    )
                    if result.project_id == project_id and (
                        key not in incoming
                        or result.inventory_revision_id == incoming[key][3]
                    ):
                        state, code = "completed", None
            except ValueError:
                pass  # Corrupt response stays unknown; no raw response is exposed.
            receipts.append(
                muse_construction.MuseConstructionReceipt(
                    idempotency_key=key,
                    digest=digest,
                    state=state,
                    error_code=code,
                    replacement_idempotency_key=outgoing[key][2]
                    if key in outgoing
                    else None,
                    replacement_expected_revision_id=outgoing[key][3]
                    if key in outgoing
                    else None,
                    replaces_idempotency_key=incoming[key][0]
                    if key in incoming
                    else None,
                )
            )
        return muse_construction.MuseConstructionReceipts(receipts=tuple(receipts))

    @router.post(
        "/{project_id}/construction/replacement-authorizations",
        response_model=muse_construction.MuseConstructionReplacementAuthorization,
    )
    def authorize_replacement(
        project_id: ID,
        body: muse_construction.MuseConstructionReplacementRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        if (
            not body.acknowledge_unknown
            or body.original_idempotency_key == body.replacement_idempotency_key
        ):
            raise DesignError(
                422,
                "validation_error",
                "Explicitly acknowledge the unknown outcome and choose a new replacement identity",
            )
        scope = project_id + ":construction-proposal"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            _current(project, body.expected_revision_id)
            rows = connection.execute(
                "SELECT key, digest, response FROM requests WHERE owner=? AND scope=? ORDER BY rowid",
                (owner, scope),
            ).fetchall()
            requests = {key: (digest, saved) for key, digest, saved in rows}
            original = requests.get(body.original_idempotency_key)
            if original is None:
                raise DesignError(
                    404, "not_found", "Original construction request not found"
                )
            if original[0] != body.original_digest:
                raise DesignError(
                    409, "idempotency_conflict", "Original request digest changed"
                )
            if not _is_uncertain(original[1]):
                raise DesignError(
                    409,
                    "blocked",
                    "Only a recorded unknown outcome can authorize replacement",
                )
            replacements = _replacement_rows(connection, owner, project_id)
            latest = {r[0]: r for r in replacements}.get(body.original_idempotency_key)
            replayed = bool(
                latest
                and latest
                == (
                    body.original_idempotency_key,
                    body.original_digest,
                    body.replacement_idempotency_key,
                    body.expected_revision_id,
                )
            )
            # Exact retries return the immutable grant even after its child was
            # dispatched. They grant no second key or provider retry.
            if not replayed:
                reserved = bool(
                    latest
                    and connection.execute(
                        "SELECT 1 FROM construction_replacement_reservations WHERE owner=? AND project_id=? AND replacement_key=?",
                        (owner, project_id, latest[2]),
                    ).fetchone()
                )
                if latest and (
                    latest[3] == body.expected_revision_id
                    or latest[2] in requests
                    or reserved
                ):
                    raise DesignError(
                        409,
                        "idempotency_conflict",
                        "This unknown request already has a replacement authorization",
                    )
                if body.replacement_idempotency_key in requests or any(
                    body.replacement_idempotency_key in (r[0], r[2])
                    for r in replacements
                ):
                    raise DesignError(
                        409,
                        "idempotency_conflict",
                        "Replacement identity is already used",
                    )
                allowed = _ancestors(
                    body.original_idempotency_key, replacements, requests
                ) | {body.original_idempotency_key}
                historical = _completed_ancestors(replacements, requests, project_id)
                unresolved = [
                    key
                    for key, _, saved in rows
                    if key not in historical
                    and (_is_uncertain(saved) or saved == _PENDING)
                ]
                if (
                    not unresolved
                    or unresolved[-1] != body.original_idempotency_key
                    or any(key not in allowed for key in unresolved)
                ):
                    raise DesignError(
                        409,
                        "blocked",
                        "Address the latest unresolved construction request before authorizing replacement",
                    )
                connection.execute(
                    "INSERT INTO construction_replacements VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        owner,
                        project_id,
                        body.original_idempotency_key,
                        body.original_digest,
                        body.replacement_idempotency_key,
                        body.expected_revision_id,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        return muse_construction.MuseConstructionReplacementAuthorization(
            project_id=project_id,
            expected_revision_id=body.expected_revision_id,
            original_idempotency_key=body.original_idempotency_key,
            original_digest=body.original_digest,
            replacement_idempotency_key=body.replacement_idempotency_key,
            replayed=replayed,
        )

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
        if body.approximate and photo is None:
            raise DesignError(
                422, "validation_error", "Choose a photo for an approximate preview"
            )
        resolver = context_resolver or design_context.default_context_resolver()
        resolved = resolver(project_id, project.revision_id)
        photo_hash = _photo_hash(photo)
        digest = _digest(
            {
                "request": body.model_dump(
                    mode="json",
                    exclude={"approximate"} if not body.approximate else set(),
                ),
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
                "SELECT key, digest, response FROM requests WHERE owner=? AND scope=?",
                (owner, scope),
            ).fetchall()
            replacements = _replacement_rows(connection, owner, project_id)
            saved_requests = {r[0]: (r[1], r[2]) for r in outstanding}
            historical = _completed_ancestors(replacements, saved_requests, project_id)
            grant = next(
                (r for r in replacements if r[2] == body.idempotency_key), None
            )
            ancestors = set()
            if grant:
                if grant[3] != body.expected_revision_id:
                    raise DesignError(
                        409,
                        "stale_version",
                        "Replacement authorization is for an earlier inventory revision",
                    )
                ancestors = _ancestors(
                    body.idempotency_key,
                    replacements,
                    saved_requests,
                )
            if any(
                _is_uncertain(r[2]) and r[0] not in ancestors | historical
                for r in outstanding
            ):
                raise DesignError(
                    409,
                    "generation_outcome_unknown",
                    "A previous provider outcome is unknown; reconcile it before another request",
                )
            if any(r[2] == _PENDING for r in outstanding):
                raise DesignError(
                    409,
                    "generation_in_progress",
                    "Another construction proposal is already in progress",
                )
            connection.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                (owner, scope, body.idempotency_key, digest, _PENDING),
            )
            if grant:
                connection.execute(
                    "INSERT OR IGNORE INTO construction_replacement_reservations VALUES (?, ?, ?, ?)",
                    (
                        owner,
                        project_id,
                        body.idempotency_key,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

        def clear_pending():
            with store.transaction() as connection:
                connection.execute(
                    "DELETE FROM requests WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                    (owner, scope, body.idempotency_key, digest, _PENDING),
                )

        budget = ProposalBudget(max_rounds=1 if body.approximate else 2, seconds=120)

        def mark_uncertain(code, stage="generation", gateway_code=None):
            marker = json.loads(_uncertain_marker(code))
            marker["evidence"] = _failure_evidence(budget, stage)
            if gateway_code in _UNCERTAIN_CODES:
                marker["evidence"]["gateway_code"] = gateway_code
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE requests SET response=? WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                    (
                        json.dumps(marker),
                        owner,
                        scope,
                        body.idempotency_key,
                        digest,
                        _PENDING,
                    ),
                )

        try:
            gateway = (gateway_factory or muse_construction.default_gateway_factory)()
            if body.approximate and isinstance(gateway, muse_construction.MetaGateway):
                gateway.max_retries = 0
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
                request_budget=budget,
                approximate=body.approximate,
            )
        except GatewayError as exc:
            if exc.code in _UNCERTAIN_CODES:
                mark_uncertain(_provider_error(exc).body.code, gateway_code=exc.code)
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
                exc.body.code if isinstance(exc, DesignError) else exc.envelope.code,
                "receipt_confirmation",
            )
            raise DesignError(
                409,
                "generation_outcome_unknown",
                "The provider returned, but the project, photo, material context or result receipt could no longer be confirmed. Keep this request identity and reconcile it before another request.",
            ) from None
        except Exception:
            mark_uncertain("result_not_confirmed", "receipt_confirmation")
            raise DesignError(
                409,
                "generation_outcome_unknown",
                "The proposal result could not be confirmed. Keep this request identity and reconcile it before another request.",
            ) from None
        return result

    return router
