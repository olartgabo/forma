"""Consented MetaMuse comparison of proposed designs through one read-only tool."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from forma_synthesizer import domain_values, domains_for, search, search_id

from forma_api import design_runtime
from forma_api import synthesis_muse as muse
from forma_api import synthesis_runtime as runtime
from forma_api.model_gateway import GatewayError
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

_STALE = json.dumps({"terminal": True, "error_code": "stale_version"})


def _stale():
    return DesignError(
        409,
        "stale_version",
        "The project changed while MetaMuse was answering; nothing was saved. Search again and ask again.",
    )


def _unknown(message):
    return DesignError(409, "generation_outcome_unknown", message)


def synthesis_muse_router(store: ProjectStore, authenticate, gateway_factory=None):
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["synthesis"], route_class=DesignRoute)

    @router.post(
        "/{project_id}/synthesis/muse-explanations",
        response_model=muse.SynthesisMuseResult,
        responses={
            status: {"model": design_runtime.DesignErrorResponse}
            for status in (401, 404, 409, 422, 429, 502, 503, 504)
        },
    )
    def explain(
        project_id: ID,
        body: muse.SynthesisMuseRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        scope = project_id + ":synthesis-muse"
        digest = _digest(
            dict(
                request=body.model_dump(mode="json"),
                project_id=project_id,
                prompt_version=muse.PROMPT_VERSION,
            )
        )

        def receipt(connection):
            row = connection.execute(
                "SELECT digest, response FROM requests WHERE owner=? AND scope=? AND key=?",
                (owner, scope, body.idempotency_key),
            ).fetchone()
            if row is None:
                return None
            if row[0] != digest:
                raise DesignError(
                    409, "idempotency_conflict", "Key already used for another request"
                )
            if _is_uncertain(row[1]):
                raise _unknown(
                    "The prior provider outcome is unknown; reconcile it before another request"
                )
            if row[1] == _PENDING:
                raise DesignError(
                    409,
                    "generation_in_progress",
                    "A design comparison is already in progress",
                )
            if row[1] == _STALE:
                raise _stale()
            return muse.SynthesisMuseResult.model_validate_json(row[1]).model_copy(
                update={"replayed": True}
            )

        def authorized():
            try:
                data = runtime.resolve(
                    store, owner, project_id, body, runtime.default_context_resolver()
                )
            except ProjectError as exc:
                raise DesignError(
                    exc.status, exc.envelope.code, exc.envelope.message
                ) from None
            return data

        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            # A completed request replays even after the project moved on, so a
            # lost response never turns a retry into a second paid dispatch.
            prior = receipt(connection)
            if prior is not None:
                return prior
        if not body.provider_context_consented:
            raise DesignError(
                422,
                "consent_required",
                "Consent to share the proposed designs with MetaMuse is required",
            )
        data = authorized()
        result = search(data, body.budget)
        if result.search_id != body.search_id:
            raise _stale()
        if result.status != "candidates_found":
            raise DesignError(
                422, "blocked", "There are no proposed designs to compare yet."
            )
        handler = muse.CompareTool(data, body.budget, result)
        context = muse.tool_context(
            project_id, result, data, domains_for, domain_values
        )
        with store.transaction() as connection:
            prior = receipt(connection)
            if prior is not None:
                return prior
            # Changing a retry key must never bypass an unresolved paid dispatch.
            outstanding = connection.execute(
                "SELECT response FROM requests WHERE owner=? AND scope=?",
                (owner, scope),
            ).fetchall()
            if any(_is_uncertain(r[0]) for r in outstanding):
                raise _unknown(
                    "A previous provider outcome is unknown; reconcile it before another request"
                )
            if any(r[0] == _PENDING for r in outstanding):
                raise DesignError(
                    409,
                    "generation_in_progress",
                    "Another design comparison is already in progress",
                )
            connection.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                (owner, scope, body.idempotency_key, digest, _PENDING),
            )

        def settle(value):
            with store.transaction() as connection:
                if value is None:
                    connection.execute(
                        "DELETE FROM requests WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                        (owner, scope, body.idempotency_key, digest, _PENDING),
                    )
                else:
                    connection.execute(
                        "UPDATE requests SET response=? WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                        (value, owner, scope, body.idempotency_key, digest, _PENDING),
                    )

        try:
            gateway = (gateway_factory or design_runtime.default_gateway_factory)()
        except GatewayError as exc:
            settle(None)
            raise _provider_error(exc) from None
        except (ValueError, RuntimeError):
            settle(None)
            raise DesignError(
                503,
                "provider_not_configured",
                "Model provider is not configured on the server",
            ) from None
        try:
            explanation, usage = muse.explain(
                gateway, handler, context=context, question=body.question
            )
        except GatewayError as exc:
            if exc.code in _UNCERTAIN_CODES:
                settle(_uncertain_marker(_provider_error(exc).body.code))
                raise _unknown(
                    "The provider outcome could not be confirmed. Keep this request identity and reconcile it before another request."
                ) from None
            settle(None)
            raise _provider_error(exc) from None
        except ValueError:
            settle(None)
            raise DesignError(
                502,
                "invalid_response",
                "MetaMuse cited a search or design that the read-only tool did not return; nothing was saved.",
            ) from None
        except Exception:
            settle(_uncertain_marker("server_error"))
            raise _unknown(
                "The explanation could not be confirmed. Keep this request identity and reconcile it before another request."
            ) from None
        try:
            try:
                current = runtime.resolve(
                    store, owner, project_id, body, runtime.default_context_resolver()
                )
                stale = search_id(current, body.budget) != body.search_id
            except ProjectError as exc:
                if exc.status != 409:
                    raise
                stale = True
            with store.transaction() as connection:
                # The write lock is held from here: an inventory or history
                # change can no longer slip between this check and the save.
                if not stale:
                    stale = not runtime.stored_identity_matches(
                        connection, store, owner, project_id, current.identity
                    )
                if stale:
                    connection.execute(
                        "UPDATE requests SET response=? WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                        (_STALE, owner, scope, body.idempotency_key, digest, _PENDING),
                    )
                else:
                    result = muse.SynthesisMuseResult(
                        project_id=project_id,
                        search_id=body.search_id,
                        prompt_version=muse.PROMPT_VERSION,
                        explanation=explanation,
                        engine_probe=handler.probe,
                        usage=usage,
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
                        raise RuntimeError("receipt not confirmed")
        except Exception:
            settle(_uncertain_marker("result_not_confirmed"))
            raise _unknown(
                "MetaMuse returned, but the project or result receipt could no longer be confirmed. Keep this request identity and reconcile it before another request."
            ) from None
        if stale:
            raise _stale()
        return result

    return router
