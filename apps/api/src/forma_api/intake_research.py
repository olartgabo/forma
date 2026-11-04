"""Optional web research over the existing stock-feasible stand search."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, time
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from forma_synthesizer import search
from pydantic import Field, StrictBool, field_validator, model_validator

from forma_api import intake_research_muse as muse
from forma_api import measurement_runtime, synthesis_runtime
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.projects import Key, ProjectError, ProjectStore
from forma_api.provider_diagnostics import ProviderUsage, summarize_usage
from forma_domain.models import ID, Record, Text
from forma_domain.synthesis_contracts import SynthesisResult

SCOPE = ":intake-research"
LEASE_SCOPE = "intake-research-leases"
BRIEFS = {
    "phone_stand": "Research a low-risk cardboard tabletop phone stand made with tape and no glue.",
    "reading_stand": "Research a low-risk cardboard tabletop reading stand made with tape and no glue.",
}
UNCERTAIN = {"timeout", "network_error", "budget_exhausted", "provider_outcome_unknown"}
DEADLINE_SECONDS = 20
MAX_CONCURRENT = 2


class IntakeResearchAvailability(Record):
    enabled: bool


class IntakeResearchRequest(Record):
    expected_inventory_revision_id: ID
    idempotency_key: Key
    consented: Literal[True]
    use_case: Literal["phone_stand", "reading_stand"]
    needs_plug_clearance: StrictBool

    @field_validator("consented", mode="before")
    @classmethod
    def require_explicit_consent(cls, value):
        if value is not True:
            raise ValueError("Explicit consent is required")
        return value


class IntakeResearchResult(Record):
    project_id: ID
    inventory_revision_id: ID
    coverage: Literal["complete", "partial", "no_sources", "unavailable", "not_run"]
    decision: Literal[
        "eligible", "needs_input", "blocked", "undetermined", "unsupported"
    ]
    findings: tuple[muse.ResearchFinding, ...] = Field(default=(), max_length=4)
    reason: Text
    question: Text | None = None
    search: SynthesisResult | None = None
    recommended_candidate_id: ID | None = None
    provider_elapsed_ms: int | None = Field(default=None, ge=0)
    usage: ProviderUsage | None = None
    replayed: bool = False

    @model_validator(mode="after")
    def recommendation_is_checked(self):
        if self.search is not None and (
            self.decision != "eligible"
            or self.search.status != "candidates_found"
            or self.search.identity.project_id != self.project_id
            or self.search.identity.inventory_revision_id != self.inventory_revision_id
        ):
            raise ValueError("Only eligible results carry current checked designs")
        if self.recommended_candidate_id is not None and (
            not self.findings
            or self.search is None
            or self.recommended_candidate_id
            not in {candidate.candidate_id for candidate in self.search.candidates}
        ):
            raise ValueError("The recommendation must cite checked designs and sources")
        return self


def enabled() -> bool:
    return os.environ.get("FORMA_INTAKE_RESEARCH") == "1"


def _engine_result(store, owner, project_id, body, identity, data, resolver):
    base = IntakeResearchResult(
        project_id=project_id,
        inventory_revision_id=identity.expected_inventory_revision_id,
        coverage="not_run",
        decision="unsupported",
        reason="Plug clearance is essential and has no supported check in this stand workflow.",
    )
    if body.needs_plug_clearance:
        return base
    result = search(data, identity.budget)
    if result.status == "candidates_found":
        required_checks = {"compiler", "canonical-geometry", "fabrication-order"}
        checked = tuple(
            candidate
            for candidate in result.candidates
            if required_checks.issubset(
                check.check_id
                for check in candidate.checks
                if check.status == "modeled_pass"
            )
        )
        if not checked:
            reason = next(
                (
                    check.detail
                    for candidate in result.candidates
                    for check in candidate.checks
                    if check.check_id in required_checks
                    and check.status != "modeled_pass"
                ),
                "Confirm the inputs required for fabrication.",
            )
            return base.model_copy(update={"decision": "needs_input", "reason": reason})
        return base.model_copy(
            update={
                "decision": "eligible",
                "reason": "The existing stand search found checked proposals for the saved inventory.",
                "search": result.model_copy(update={"candidates": checked}),
            }
        )
    if result.status == "infeasible":
        return base.model_copy(
            update={
                "decision": "blocked",
                "reason": (
                    result.blockers[0].message
                    if result.blockers
                    else "No supported design fits the saved materials and constraints."
                ),
            }
        )
    if result.status == "search_exhausted":
        return base.model_copy(
            update={
                "decision": "undetermined",
                "reason": "The stand search reached its limit before finding a checked design.",
            }
        )
    decision = measurement_runtime.decide(
        store,
        owner,
        project_id,
        measurement_runtime.DecisionRequest(
            expected_inventory_revision_id=identity.expected_inventory_revision_id,
            expected_active_version_id=None,
        ),
        resolver,
    )
    question = decision.question
    return base.model_copy(
        update={
            "decision": "needs_input",
            "reason": (
                question.why
                if question is not None
                else result.blockers[0].message
                if result.blockers
                else "The stand search needs confirmed project inputs."
            ),
            "question": (
                f"{question.target.label}. {question.method}"[:2000]
                if question is not None
                else None
            ),
        }
    )


def _investigate(base, gateway, brief, deadline, current):
    started = monotonic()
    findings = ()
    analysis = None
    uncertain = False
    scout_succeeded = False
    with ThreadPoolExecutor(max_workers=2) as pool:
        scout_job = pool.submit(muse.scout, gateway, brief, deadline)
        analysis_job = pool.submit(muse.analyze, gateway, brief, deadline)
        try:
            findings = scout_job.result()
            scout_succeeded = True
        except GatewayError as exc:
            uncertain = exc.code in UNCERTAIN
        try:
            analysis = analysis_job.result()
        except GatewayError as exc:
            uncertain |= exc.code in UNCERTAIN

    coverage = "no_sources" if scout_succeeded else "unavailable"
    reason = base.reason
    recommended = None
    if findings:
        candidates = base.search.candidates
        if len(candidates) == 1:
            coverage = "complete" if analysis is not None else "partial"
            reason = "The stand search found one checked proposal. The sources describe related approaches."
        else:
            coverage = "partial"
            if (
                analysis is not None
                and not uncertain
                and monotonic() < deadline
                and current()
            ):
                first, second = candidates
                options = (
                    muse.ResearchOption(id="option-a", tradeoff="least_stock"),
                    muse.ResearchOption(
                        id="option-b",
                        tradeoff="alternative_stock_or_base",
                        uses_alternate_sheet=(
                            second.design.sheet_stock_id != first.design.sheet_stock_id
                        ),
                        different_base_depth=(
                            second.design.footprint_depth_mm
                            != first.design.footprint_depth_mm
                        ),
                        uses_less_tape=(
                            second.material is not None
                            and first.material is not None
                            and second.material.tape_length_mm
                            < first.material.tape_length_mm
                        ),
                    ),
                )
                try:
                    selection = muse.adjudicate(
                        gateway, brief, findings, analysis, options, deadline
                    )
                    selected = {option.id: c for option, c in zip(options, candidates)}
                    if selection in selected:
                        recommended = selected[selection].candidate_id
                        coverage = "complete"
                        reason = (
                            "Research favored the stock-saving checked proposal."
                            if selection == "option-a"
                            else "Research favored the checked alternative stock or base."
                        )
                    elif selection == muse.NO_PREFERENCE:
                        coverage = "complete"
                        reason = (
                            "The sources did not distinguish the checked proposals."
                        )
                except GatewayError as exc:
                    uncertain |= exc.code in UNCERTAIN

    if uncertain:
        reason += (
            " A research request may still be processing. Further research is paused."
        )

    return base.model_copy(
        update={
            "coverage": coverage,
            "findings": findings,
            "recommended_candidate_id": recommended,
            "reason": reason,
            "provider_elapsed_ms": round((monotonic() - started) * 1000),
            "usage": summarize_usage(gateway.traces),
        }
    ), uncertain


def intake_research_router(store: ProjectStore, authenticate) -> APIRouter:
    router = APIRouter(tags=["intake research"])
    Owner = Annotated[str, Depends(authenticate)]
    path = "/{project_id}/synthesis/research"

    @router.get(path, response_model=IntakeResearchAvailability)
    def availability(project_id: ID, owner: Owner, response: Response):
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
        response.headers["Cache-Control"] = "no-store"
        return IntakeResearchAvailability(enabled=enabled())

    @router.post(path, response_model=IntakeResearchResult)
    def investigate(
        project_id: ID, body: IntakeResearchRequest, owner: Owner, response: Response
    ):
        response.headers["Cache-Control"] = "no-store"
        scope = project_id + SCOPE
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
        if not enabled():
            raise ProjectError(404, "not_found", "Intake research is disabled")
        identity = synthesis_runtime.SynthesisSearchRequest(
            expected_inventory_revision_id=body.expected_inventory_revision_id,
            expected_active_version_id=None,
            expected_last_event_id=None,
        )
        resolver = synthesis_runtime.default_context_resolver()
        data = synthesis_runtime.resolve(store, owner, project_id, identity, resolver)
        payload = {
            "request": body.model_dump(mode="json"),
            "context": data.identity.model_dump(mode="json"),
        }

        with store.transaction() as connection:
            if not synthesis_runtime.stored_identity_matches(
                connection, store, owner, project_id, data.identity
            ):
                raise ProjectError(409, "stale_version", "Project inputs changed")
            digest, replay = store.replay(
                connection, owner, scope, body.idempotency_key, payload
            )
            if replay is not None:
                return _replayed_result(replay)

        deadline = monotonic() + DEADLINE_SECONDS
        base = _engine_result(store, owner, project_id, body, identity, data, resolver)
        if (
            synthesis_runtime.resolve(store, owner, project_id, identity, resolver)
            != data
        ):
            raise ProjectError(409, "stale_version", "Project inputs changed")
        if base.search is None:
            return base

        try:
            gateway = MetaGateway.from_env()
        except (GatewayError, ValueError):
            return base.model_copy(update={"coverage": "unavailable"})

        with store.transaction() as connection:
            if not synthesis_runtime.stored_identity_matches(
                connection, store, owner, project_id, data.identity
            ):
                raise ProjectError(409, "stale_version", "Project inputs changed")
            digest, replay = store.replay(
                connection, owner, scope, body.idempotency_key, payload
            )
            if replay is not None:
                return _replayed_result(replay)
            if connection.execute(
                "SELECT 1 FROM requests WHERE owner=? AND scope=? "
                "AND (json_extract(response, '$.pending')=1 "
                "OR json_extract(response, '$.uncertain')=1)",
                (owner, scope),
            ).fetchone():
                return _outcome_unknown(
                    "A previous research outcome is still unresolved. Continue without research."
                )
            if monotonic() >= deadline:
                return base.model_copy(update={"coverage": "unavailable"})
            now = time()
            # Capacity leases contain no project data and outlive deletion of
            # a project's receipt. Expiry releases capacity after a crash,
            # while an unresolved project receipt still prevents redispatch.
            connection.execute(
                "DELETE FROM requests WHERE scope=? "
                "AND json_extract(response, '$.expires_at')<=?",
                (LEASE_SCOPE, now),
            )
            in_flight, owner_in_flight = connection.execute(
                "SELECT COUNT(*), COUNT(CASE WHEN owner=? THEN 1 END) FROM requests "
                "WHERE scope=?",
                (owner, LEASE_SCOPE),
            ).fetchone()
            if in_flight >= MAX_CONCURRENT or owner_in_flight:
                return JSONResponse(
                    {"code": "rate_limit", "message": "Intake research is busy."},
                    status_code=429,
                    headers={"Cache-Control": "no-store"},
                )
            lease_id = uuid4().hex
            store.remember(
                connection,
                owner,
                LEASE_SCOPE,
                lease_id,
                lease_id,
                {"expires_at": now + DEADLINE_SECONDS},
            )
            store.remember(
                connection,
                owner,
                scope,
                body.idempotency_key,
                digest,
                {"pending": True},
            )

        # A crash leaves a durable pending reservation. A late provider outcome
        # never promotes a stale result or creates another paid dispatch.
        def current_snapshot():
            try:
                return synthesis_runtime.resolve(
                    store, owner, project_id, identity, resolver
                )
            except ProjectError as exc:
                if exc.status not in (404, 409):
                    raise
                return None

        result, uncertain = _investigate(
            base,
            gateway,
            BRIEFS[body.use_case],
            deadline,
            lambda: current_snapshot() == data,
        )
        fresh = current_snapshot()
        with store.transaction() as connection:
            connection.execute(
                "DELETE FROM requests WHERE owner=? AND scope=? AND key=?",
                (owner, LEASE_SCOPE, lease_id),
            )
            current = fresh == data and synthesis_runtime.stored_identity_matches(
                connection, store, owner, project_id, data.identity
            )
            if current:
                connection.execute(
                    "UPDATE requests SET response=? WHERE owner=? AND scope=? AND key=?",
                    (
                        _receipt(result, uncertain),
                        owner,
                        scope,
                        body.idempotency_key,
                    ),
                )
            elif uncertain:
                connection.execute(
                    "UPDATE requests SET response=? WHERE owner=? AND scope=? AND key=?",
                    (_receipt(None, True), owner, scope, body.idempotency_key),
                )
            else:
                connection.execute(
                    "DELETE FROM requests WHERE owner=? AND scope=? AND key=?",
                    (owner, scope, body.idempotency_key),
                )
        if not current:
            if fresh is None:
                with store.transaction() as connection:
                    store.read(connection, owner, project_id)
            raise ProjectError(409, "stale_version", "Project inputs changed")
        return result

    return router


def _receipt(result: IntakeResearchResult | None, uncertain: bool) -> str:
    return json.dumps(
        {
            "result": result.model_dump(mode="json") if result is not None else None,
            "uncertain": uncertain,
        }
    )


def _replayed_result(replay: dict) -> IntakeResearchResult | JSONResponse:
    if replay.get("result") is None:
        return _outcome_unknown(
            "The previous research may still be running or its outcome is unknown."
        )
    return IntakeResearchResult.model_validate({**replay["result"], "replayed": True})


def _outcome_unknown(message: str) -> JSONResponse:
    return JSONResponse(
        {"code": "generation_outcome_unknown", "message": message},
        status_code=409,
        headers={"Cache-Control": "no-store"},
    )
