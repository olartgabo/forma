"""Owner-scoped advisory research with durable reservations and no physical writes."""

import hashlib
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from forma_api.model_gateway import GatewayError
from forma_api.projects import ProjectStore
from forma_api.sourcing import (
    ResearchRequest,
    ResearchRun,
    SourcingErrorResponse,
    SourcingNeed,
    SourcingNeeds,
    SourcingUsage,
)
from forma_api.sourcing_gateway import PendingResearch, default_gateway_factory
from forma_api.sourcing_http import valid_response_id
from forma_domain.models import ID


class SourcingError(Exception):
    def __init__(self, status, code, message):
        self.status, self.body = status, {"code": code, "message": message}


class SourcingRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                response = await original(request)
            except SourcingError as exc:
                response = JSONResponse(exc.body, status_code=exc.status)
            except RequestValidationError:
                response = JSONResponse(
                    {"code": "validation_error", "message": "Invalid sourcing request"},
                    status_code=422,
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


def table(connection):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS sourcing_runs (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, request_key TEXT NOT NULL, digest TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(project_id,request_key))"
    )


def sourcing_router(store: ProjectStore, authenticate, gateway_factory=None):
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["sourcing"], route_class=SourcingRoute)

    @router.get("/{project_id}/sourcing/needs", response_model=SourcingNeeds)
    def needs(project_id: ID, owner: Owner):
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            table(connection)
            pending = connection.execute(
                "SELECT id FROM sourcing_runs WHERE project_id=? AND json_extract(body,'$.status') IN ('running','outcome_unknown') ORDER BY rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            engine_needs = []
            if project.active_version_id:
                from forma_api.fabrication_runtime import active_report

                report = active_report(connection, project, project.active_version_id)
                seen = set()
                for operation in report.operations:
                    if operation.status == "completed":
                        continue
                    for check in operation.tools:
                        if check.status != "not_declared" or check.tool in seen:
                            continue
                        seen.add(check.tool)
                        engine_needs.append(
                            SourcingNeed(
                                id="need-"
                                + hashlib.sha256(
                                    (
                                        report.snapshot.inputs_sha256 + ":" + check.tool
                                    ).encode()
                                ).hexdigest(),
                                label=check.tool.replace("_", " "),
                                kind="tool",
                                reason=f"Fabrication operation {operation.operation_id} in version {project.active_version_id} requires this tool class, but it was not declared available. Confirm possession before buying. Report {report.snapshot.inputs_sha256}.",
                            )
                        )
        guidance = [
            "Research a user-requested item below. Listed items are not confirmed inventory."
        ]
        if not project.inventory_confirmed:
            guidance.append(
                "Confirm your existing materials before deciding what is missing."
            )
        if any(
            not stock.width_mm.confirmed or not stock.height_mm.confirmed
            for stock in project.stocks
            if stock.kind == "sheet"
        ):
            guidance.append(
                "Measure unknown sheet dimensions first; unknown size does not mean you need to buy material."
            )
        return SourcingNeeds(
            project_id=project.id,
            revision_id=project.revision_id,
            active_version_id=project.active_version_id,
            guidance=tuple(guidance),
            needs=tuple(engine_needs),
            pending_run_id=pending[0] if pending else None,
        )

    @router.get("/{project_id}/sourcing/research/{run_id}", response_model=ResearchRun)
    def read_run(project_id: ID, run_id: ID, owner: Owner):
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            table(connection)
            row = connection.execute(
                "SELECT body FROM sourcing_runs WHERE id=? AND project_id=?",
                (run_id, project_id),
            ).fetchone()
            if row is None:
                raise SourcingError(404, "not_found", "Research not found")
            original_body = row[0]
            run = ResearchRun.model_validate_json(original_body)
        if (
            run.kind in {"public_discovery", "supplier_page"}
            and not run.provider_response_id
            and run.status == "running"
        ):
            started = datetime.fromisoformat(run.observed_at)
            if (
                started.tzinfo is not None
                and (datetime.now(timezone.utc) - started).total_seconds() >= 120
            ):
                result = run.model_copy(
                    update={
                        "status": "failed",
                        "error": "Public supplier lookup was interrupted. You can retry this search with a new request.",
                    }
                )
                with store.transaction() as connection:
                    store.read(connection, owner, project_id)
                    connection.execute(
                        "UPDATE sourcing_runs SET body=? WHERE id=? AND project_id=? AND body=?",
                        (result.model_dump_json(), run.id, project_id, original_body),
                    )
                    saved = connection.execute(
                        "SELECT body FROM sourcing_runs WHERE id=? AND project_id=?",
                        (run.id, project_id),
                    ).fetchone()
                    if saved is None:
                        raise SourcingError(404, "not_found", "Research not found")
                    return ResearchRun.model_validate_json(saved[0])
        if not run.provider_response_id or run.status not in {
            "running",
            "outcome_unknown",
        }:
            return run
        # Retrieve the existing generation only. Never restart a timed-out POST.
        # No database transaction remains open during provider network work.
        body = ResearchRequest(
            expected_revision_id=run.revision_id,
            idempotency_key="poll-existing-response",
            item=run.item,
            area=run.area,
            currency=run.currency,
            provider_transfer_consented=True,
        )
        try:
            gateway = (gateway_factory or default_gateway_factory)()
            offers, usage = gateway.poll(run.provider_response_id, body)
            result = run.model_copy(
                update={
                    "status": "succeeded" if offers else "no_verified_results",
                    "offers": offers,
                    "usage": usage,
                    "error": None,
                }
            )
        except PendingResearch as exc:
            if exc.response_id != run.provider_response_id:
                raise SourcingError(
                    502,
                    "invalid_response",
                    "Provider returned a different research identity",
                ) from None
            result = run.model_copy(
                update={"status": "running", "error": None, "usage": exc.sourcing_usage}
            )
        except GatewayError as exc:
            usage = getattr(exc, "sourcing_usage", None)
            result = run.model_copy(
                update={
                    "status": "failed"
                    if exc.code == "research_incomplete"
                    else "outcome_unknown",
                    "error": "Research status could not be retrieved. Check status again; no new generation was started.",
                    "usage": usage if isinstance(usage, SourcingUsage) else run.usage,
                }
            )
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            # An older running poll cannot overwrite a concurrently completed poll.
            connection.execute(
                "UPDATE sourcing_runs SET body=? WHERE id=? AND project_id=? AND body=?",
                (result.model_dump_json(), run.id, project_id, original_body),
            )
            saved = connection.execute(
                "SELECT body FROM sourcing_runs WHERE id=? AND project_id=?",
                (run.id, project_id),
            ).fetchone()
            if saved is None:
                raise SourcingError(404, "not_found", "Research not found")
            return ResearchRun.model_validate_json(saved[0])

    @router.post(
        "/{project_id}/sourcing/research",
        response_model=ResearchRun,
        responses={503: {"model": SourcingErrorResponse}},
    )
    def research(project_id: ID, body: ResearchRequest, owner: Owner):
        digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            if body.source == "marketplace":
                raise SourcingError(
                    403,
                    "authorization_required",
                    "Marketplace retrieval requires Meta authorization; open Facebook yourself instead.",
                )
            if (
                body.source == "suppliers"
                and body.location is None
                and not body.provider_transfer_consented
            ):
                raise SourcingError(
                    422,
                    "consent_required",
                    "Consent to send this item and approximate area to Meta is required.",
                )
            table(connection)
            row = connection.execute(
                "SELECT digest,body FROM sourcing_runs WHERE project_id=? AND request_key=?",
                (project_id, body.idempotency_key),
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise SourcingError(
                        409, "idempotency_conflict", "Request key already used"
                    )
                return ResearchRun.model_validate_json(row[1]).model_copy(
                    update={"replayed": True}
                )
            if project.revision_id != body.expected_revision_id:
                raise SourcingError(
                    409, "stale_version", "Project changed; reload before researching"
                )
            unresolved = connection.execute(
                "SELECT 1 FROM sourcing_runs WHERE project_id=? AND json_extract(body,'$.status') IN ('running','outcome_unknown')",
                (project_id,),
            ).fetchone()
            if unresolved:
                raise SourcingError(
                    409,
                    "outcome_unknown",
                    "A prior research request needs reconciliation; no new provider call was made.",
                )
        # Factory preflight before reserving: configuration failure consumes nothing.
        try:
            if body.location is not None:
                from forma_api.sourcing_discovery import (
                    NearbyDiscoveryGateway,
                    NearbyMetaGateway,
                )

                gateway = (
                    NearbyMetaGateway((gateway_factory or default_gateway_factory)())
                    if body.provider_transfer_consented
                    else NearbyDiscoveryGateway()
                )
            elif body.source == "supplier_page":
                from forma_api.supplier_page import SupplierPageGateway

                gateway = SupplierPageGateway()
            else:
                gateway = (gateway_factory or default_gateway_factory)()
        except (GatewayError, ValueError):
            raise SourcingError(
                503,
                "source_unavailable",
                "Supplier research is not configured on this server. You can use the Marketplace handoff meanwhile.",
            ) from None
        run = ResearchRun(
            kind="public_discovery"
            if body.location is not None and not body.provider_transfer_consented
            else "supplier_page"
            if body.source == "supplier_page"
            else "meta",
            id="research-" + uuid4().hex,
            project_id=project_id,
            revision_id=project.revision_id,
            status="running",
            active_version_id=project.active_version_id,
            item=body.item,
            area=body.area,
            currency=body.currency,
            observed_at=datetime.now(timezone.utc).isoformat(),
        )
        with store.transaction() as connection:
            current = store.read(connection, owner, project_id)
            if current.revision_id != body.expected_revision_id:
                raise SourcingError(
                    409, "stale_version", "Project changed; reload before researching"
                )
            # Serialize reservation creation and guard against concurrent fresh keys.
            if connection.execute(
                "SELECT 1 FROM sourcing_runs WHERE project_id=? AND (request_key=? OR json_extract(body,'$.status') IN ('running','outcome_unknown'))",
                (project_id, body.idempotency_key),
            ).fetchone():
                raise SourcingError(
                    409,
                    "outcome_unknown",
                    "Another research request is already reserved; reload its status.",
                )
            connection.execute(
                "INSERT INTO sourcing_runs VALUES (?,?,?,?,?)",
                (
                    run.id,
                    project_id,
                    body.idempotency_key,
                    digest,
                    run.model_dump_json(),
                ),
            )
        try:
            offers, usage = gateway.research(body)
            result = run.model_copy(
                update={
                    "status": "succeeded" if offers else "no_verified_results",
                    "offers": offers,
                    "usage": usage,
                    "nearby_places": getattr(gateway, "places", ()),
                    "discovery_message": getattr(gateway, "message", None),
                }
            )
        except PendingResearch as exc:
            result = run.model_copy(
                update={
                    "status": "running",
                    "provider_response_id": exc.response_id,
                    "usage": exc.sourcing_usage,
                    "error": None,
                    "nearby_places": getattr(gateway, "places", ()),
                    "discovery_message": getattr(gateway, "message", None),
                }
            )
        except GatewayError as exc:
            # After dispatch, malformed/truncated/5xx responses cannot prove
            # the provider did not process and charge the request. Preserve the
            # reservation and prohibit fresh keys rather than retry blindly.
            uncertain = run.kind == "meta" and exc.code not in {
                "authentication",
                "access_denied",
                "rate_limit",
                "supplier_page_error",
                "discovery_failed",
                "research_incomplete",
            }
            reported_usage = getattr(exc, "sourcing_usage", None)
            reported_response_id = getattr(exc, "sourcing_response_id", None)
            result = run.model_copy(
                update={
                    "provider_response_id": reported_response_id
                    if valid_response_id(reported_response_id)
                    else run.provider_response_id,
                    "usage": reported_usage
                    if isinstance(reported_usage, SourcingUsage)
                    else None,
                    "status": "outcome_unknown" if uncertain else "failed",
                    "error": "Provider outcome unknown; do not retry."
                    if uncertain
                    else "Nearby supplier lookup did not complete. Try again later."
                    if exc.code == "discovery_failed"
                    else "Provider returned no usable research result.",
                    "nearby_places": getattr(gateway, "places", ()),
                    "discovery_message": getattr(gateway, "message", None),
                }
            )
        except Exception:
            # Only Meta adapters can have an unknown generated-provider outcome.
            # Public HTTP lookups never dispatch a paid model request.
            result = run.model_copy(
                update={
                    "status": "outcome_unknown" if run.kind == "meta" else "failed",
                    "error": "Provider outcome unknown; do not retry."
                    if run.kind == "meta"
                    else "Public supplier lookup was interrupted. You can retry this search with a new request.",
                    "nearby_places": getattr(gateway, "places", ()),
                    "discovery_message": getattr(gateway, "message", None),
                }
            )
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            connection.execute(
                "UPDATE sourcing_runs SET body=? WHERE id=? AND project_id=? AND body=?",
                (result.model_dump_json(), run.id, project_id, run.model_dump_json()),
            )
            # A stalled worker must not overwrite an explicit stale-run recovery.
            saved = connection.execute(
                "SELECT body FROM sourcing_runs WHERE id=? AND project_id=?",
                (run.id, project_id),
            ).fetchone()
            if saved is None:
                raise SourcingError(404, "not_found", "Research not found")
            return ResearchRun.model_validate_json(saved[0])

    return router
