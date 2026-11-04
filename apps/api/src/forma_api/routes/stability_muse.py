"""Consented MetaMuse stability explanations through bounded read-only tools."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from forma_api import design_runtime
from forma_api import stability_muse as muse
from forma_api import stability_reports as reports
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
        "The project changed while MetaMuse was answering; nothing was saved. Reload and ask again.",
    )


def _unknown(message):
    return DesignError(409, "generation_outcome_unknown", message)


def stability_muse_router(
    store: ProjectStore, authenticate, gateway_factory=None, resolver=None
):
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["stability"], route_class=DesignRoute)

    @router.post(
        "/{project_id}/stability/muse-explanations",
        response_model=muse.StabilityMuseResult,
        responses={
            status: {"model": design_runtime.DesignErrorResponse}
            for status in (401, 404, 409, 422, 429, 502, 503, 504)
        },
    )
    def explain(
        project_id: ID,
        body: muse.StabilityMuseRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        scope = project_id + ":stability-muse"
        digest = _digest(
            dict(
                request=body.model_dump(mode="json"),
                project_id=project_id,
                prompt_version=muse.PROMPT_VERSION,
            )
        )
        legacy_digest = _digest(
            dict(
                request=body.model_dump(mode="json"),
                project_id=project_id,
                prompt_version=muse.LEGACY_PROMPT_VERSION,
            )
        )

        def receipt(connection):
            """Settled answer for this exact request, with freshness judged now."""
            row = connection.execute(
                "SELECT digest, response FROM requests WHERE owner=? AND scope=? AND key=?",
                (owner, scope, body.idempotency_key),
            ).fetchone()
            if row is None:
                return None
            if row[0] not in (digest, legacy_digest):
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
                    "A stability explanation is already in progress",
                )
            if row[1] == _STALE:
                raise _stale()
            value = json.loads(row[1])
            saved = reports.read_record(
                connection, project_id, value["report"]["report_id"]
            )
            if saved is None:
                raise DesignError(
                    404,
                    "not_found",
                    "The saved stability report is no longer available",
                )
            focus = (
                muse.default_focus(
                    saved.report,
                    tuple(case.case_id for case in saved.analysis_input.cases),
                )
                if row[0] == legacy_digest
                else muse.StabilityMuseFocus.model_validate(value["focus"])
            )
            if focus is None:
                raise DesignError(
                    422,
                    "blocked",
                    "The saved report contains no check results. Its completed provider request will not be sent again.",
                )
            # Legacy free text is never parsed into or returned as an explanation.
            value.update(
                focus=focus.model_dump(mode="json"),
                explanation=muse.render_focus(saved.report, focus).model_dump(
                    mode="json"
                ),
                focused_results=[
                    row.model_dump(mode="json")
                    for row in muse.selected_results(saved.report, focus)
                ],
                prompt_version=muse.PROMPT_VERSION,
            )
            result = muse.StabilityMuseResult.model_validate(value)
            state = reports.ProjectState(connection, store, owner, project_id)
            return result.model_copy(
                update={
                    "replayed": True,
                    "report": state.current_summary(connection, result.report),
                }
            )

        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            # A completed request replays even after the project moved on, so
            # a lost response never turns a retry into a second paid dispatch.
            prior = receipt(connection)
            if prior is not None:
                return prior
            if not body.provider_context_consented:
                raise DesignError(
                    422,
                    "consent_required",
                    "Consent to share this stability report with MetaMuse is required",
                )
            snapshot = reports.authorized_snapshot(
                connection, store, owner, project_id, body
            )
            if body.mode == "analyze_current":
                evaluation = reports.evaluate(snapshot, resolver)
                report = evaluation.response.report
                if report is None:
                    raise DesignError(
                        422,
                        "blocked",
                        "No stability report is available yet: "
                        + "; ".join(evaluation.response.blockers[:4]),
                    )
                expected = reports.report_id(report)
                handler = muse.AnalyzeTool(snapshot, resolver, expected)
                allowed_cases = [c.case_id for c in evaluation.analysis.cases]
                context = dict(
                    mode=body.mode,
                    project_id=project_id,
                    allowed_plan_version_id=body.plan_version_id,
                    allowed_report_ids=[expected],
                    allowed_case_ids=allowed_cases,
                    allowed_result_pairs=[
                        dict(case_id=r.case_id, check_type=r.check_type)
                        for r in report.results
                    ],
                )
            else:
                state = reports.ProjectState(connection, store, owner, project_id)
                saved = reports.read_record(connection, project_id, body.report_id)
                if saved is None:
                    raise DesignError(404, "not_found", "Stability report not found")
                expected = saved.report_id
                fresh = state.freshness(saved)
                handler = muse.ExplainTool(saved, fresh)
                context = dict(
                    mode=body.mode,
                    project_id=project_id,
                    allowed_report_ids=[expected],
                    allowed_case_ids=[c.case_id for c in saved.analysis_input.cases],
                    report_is_current=fresh.current,
                    stale_reasons=list(fresh.stale_reasons),
                    allowed_result_pairs=[
                        dict(case_id=r.case_id, check_type=r.check_type)
                        for r in saved.report.results
                    ],
                )
        with store.transaction() as connection:
            reports.authorized_snapshot(connection, store, owner, project_id, body)
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
                    "Another stability explanation is already in progress",
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
            explanation, focus, usage = muse.explain(
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
                "MetaMuse cited a report or case that the read-only tool did not return; nothing was saved.",
            ) from None
        except Exception:
            settle(_uncertain_marker("server_error"))
            raise _unknown(
                "The explanation could not be confirmed. Keep this request identity and reconcile it before another request."
            ) from None
        try:
            with store.transaction() as connection:
                try:
                    reports.authorized_snapshot(
                        connection, store, owner, project_id, body
                    )
                except ProjectError as exc:
                    if exc.status != 409:
                        raise
                    connection.execute(
                        "UPDATE requests SET response=? WHERE owner=? AND scope=? AND key=? AND digest=? AND response=?",
                        (_STALE, owner, scope, body.idempotency_key, digest, _PENDING),
                    )
                    stale = True
                else:
                    stale = False
                if not stale:
                    if isinstance(handler, muse.AnalyzeTool):
                        record = reports.build_record(handler.evaluation, "muse_tool")
                        saved, _ = reports.store_record(connection, record)
                    else:
                        saved = handler.saved
                    result = muse.StabilityMuseResult(
                        project_id=project_id,
                        plan_version_id=body.plan_version_id,
                        mode=body.mode,
                        tool_name=handler.name,
                        prompt_version=muse.PROMPT_VERSION,
                        report=reports.ProjectState(
                            connection, store, owner, project_id
                        ).summary(saved),
                        explanation=explanation,
                        focus=focus,
                        focused_results=muse.selected_results(saved.report, focus),
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
