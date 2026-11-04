"""Owner-scoped stock-feasible design search, probe and explicit selection (#148).

Search and probe only read. Selection saves an ordinary plan preview through the
existing ``PlanService`` transaction; activation stays the separate approval.
"""

from typing import Literal

from forma_synthesizer import (
    MeasurementBasis,
    SearchInput,
    check_design,
    design_candidate,
    domain_values,
    domains_for,
    evaluate,
    missing_inputs,
    probe,
    search,
    search_id,
    stand_parameters,
)
from pydantic import Field

from forma_api import design_context
from forma_api.adapt import RepairBase, confirmed_remaining
from forma_api.plans import CompilePreview, PlanCompileResult, PlanService
from forma_api.projects import Key, Project, ProjectError, ProjectStore
from forma_domain.models import ID, Blocker, Positive, Record, RepairPatch
from forma_domain.stability_measurements import StabilityMeasurementRecord
from forma_domain.synthesis_contracts import (
    ProbeResult,
    RepairProbeSummary,
    SearchBudget,
    SearchIdentity,
    SearchParameter,
    StandDesign,
    SynthesisResult,
)

# Production never accepts synthetic fixture evidence; tests opt in explicitly.
ALLOW_SYNTHETIC = False
SearchId = str
REPAIR_TARGETS = {
    "footprint_depth_mm": "stand-base",
    "support_length_mm": "stand-support",
}


class SynthesisSearchRequest(Record):
    expected_inventory_revision_id: ID
    expected_active_version_id: ID | None
    expected_last_event_id: ID | None
    budget: SearchBudget = SearchBudget()


class SynthesisProbeRequest(SynthesisSearchRequest):
    search_id: SearchId = Field(pattern=r"^[0-9a-f]{64}$")
    design: StandDesign | None = None
    parameter: SearchParameter
    value_mm: Positive


class SynthesisSelectRequest(SynthesisSearchRequest):
    search_id: SearchId = Field(pattern=r"^[0-9a-f]{64}$")
    design: StandDesign
    idempotency_key: Key
    user_selected: Literal[True]


def default_context_resolver():
    return design_context.default_context_resolver()


def default_plan_service(store: ProjectStore) -> PlanService:
    return PlanService(store, allow_synthetic=ALLOW_SYNTHETIC)


def _last_event_id(connection, project_id: str) -> str | None:
    row = connection.execute(
        "SELECT id FROM progress_events WHERE project_id=? ORDER BY rowid DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    return row[0] if row else None


def _measurements(connection, project_id: str) -> tuple[MeasurementBasis, ...]:
    rows = connection.execute(
        "SELECT body FROM stability_measurements WHERE project_id=? "
        "ORDER BY rowid DESC LIMIT 64",
        (project_id,),
    ).fetchall()
    records = [StabilityMeasurementRecord.model_validate_json(r[0]) for r in rows]
    return tuple(
        MeasurementBasis(
            record_id=r.id,
            plan_version_id=r.plan_version_id,
            geometry_basis_hash=r.geometry_basis_hash,
        )
        for r in reversed(records)
    )


def _require_current(project: Project, last_event_id, body: SynthesisSearchRequest):
    if project.revision_id != body.expected_inventory_revision_id:
        raise ProjectError(409, "stale_version", "Inventory changed; reload it")
    if project.active_version_id != body.expected_active_version_id:
        raise ProjectError(409, "stale_version", "The active plan changed; reload it")
    if last_event_id != body.expected_last_event_id:
        raise ProjectError(409, "stale_version", "Physical history changed; reload it")


def resolve(store, owner, project_id, body, resolver) -> SearchInput:
    """Read the authorized snapshot; reject stale or foreign identities (404/409)."""
    with store.transaction() as connection:
        project = store.read(connection, owner, project_id)
        last_event_id = _last_event_id(connection, project_id)
        _require_current(project, last_event_id, body)
        measurements = _measurements(connection, project_id)
    # Manifest I/O happens outside the transaction, as in the design route;
    # the identity is rechecked afterwards.
    resolved = resolver(project_id, project.revision_id)
    with store.transaction() as connection:
        again = store.read(connection, owner, project_id)
        _require_current(again, _last_event_id(connection, project_id), body)
    requirements = project.requirements
    blockers = tuple(resolved.blockers)
    if not project.inventory_confirmed:
        blockers += (
            Blocker(code="needs_confirmation", message="Confirm the saved inventory."),
        )
    return SearchInput(
        identity=SearchIdentity(
            project_id=project.id,
            inventory_revision_id=project.revision_id,
            active_version_id=project.active_version_id,
            last_event_id=last_event_id,
            context_fingerprint=resolved.fingerprint,
            measurement_record_ids=tuple(b.record_id for b in measurements),
        ),
        stocks=project.stocks,
        constraints=requirements.constraints if requirements else None,
        process=resolved.process,
        parameters=resolved.parameters,
        joint_profiles=resolved.joint_profiles,
        kerf_mm=resolved.kerf_mm,
        edge_margin_mm=resolved.edge_margin_mm,
        declared_tools=tuple(requirements.tools) if requirements else None,
        measurements=measurements,
        context_blockers=blockers,
        allow_synthetic=ALLOW_SYNTHETIC,
    )


def run_search(store, owner, project_id, body, resolver) -> SynthesisResult:
    return search(resolve(store, owner, project_id, body, resolver), body.budget)


def _require_search(data: SearchInput, body) -> None:
    if search_id(data, body.budget) != body.search_id:
        raise ProjectError(
            409, "stale_version", "Search inputs changed; run the search again"
        )


def run_probe(store, owner, project_id, body, resolver) -> ProbeResult:
    data = resolve(store, owner, project_id, body, resolver)
    _require_search(data, body)
    if data.identity.active_version_id is None:
        if body.design is None:
            raise ProjectError(422, "validation_error", "Choose a candidate to probe")
        return probe(data, body.budget, body.design, body.parameter, body.value_mm)
    return _probe_active(store, project_id, data, body)


def _unsupported(fields, message, status="unsupported") -> ProbeResult:
    return ProbeResult(
        **fields,
        status=status,
        blockers=(Blocker(code="unsupported", message=message),),
    )


def _probe_active(store, project_id, data: SearchInput, body) -> ProbeResult:
    """An active build only changes through the existing repair simulation."""
    fields = dict(
        search_id=body.search_id,
        identity=data.identity,
        parameter=body.parameter,
        value_mm=body.value_mm,
    )
    missing = missing_inputs(data)
    if missing:
        return ProbeResult(**fields, status="unsupported", blockers=tuple(missing[:16]))
    target = REPAIR_TARGETS.get(body.parameter)
    if target is None:
        return _unsupported(
            fields,
            "Changing the panel width of an active build would resize all three "
            "panels; no supported repair continuation exists.",
        )
    with store.transaction() as connection:
        base = RepairBase(connection, project_id, data.identity.active_version_id)
        if base.progress.last_event_id != data.identity.last_event_id:
            raise ProjectError(
                409, "stale_version", "Physical history changed; reload it"
            )
        # Unmeasured connector balances stay unconfirmed; the replanner decides.
        remaining = confirmed_remaining(base, (), require_all=False)
    plan = base.version.plan
    part = next((p for p in plan.parts if p.id == target), None)
    sheet = next(
        (s for s in data.stocks if part is not None and s.id == part.source_stock_id),
        None,
    )
    if part is None or sheet is None or len(sheet.usable_regions) != 1:
        return _unsupported(
            fields,
            "The active plan is not the original supported stand layout; use the "
            "repair flow.",
        )
    domain = next(d for d in domains_for(data, sheet) if d.parameter == body.parameter)
    if body.value_mm not in domain_values(domain):
        return _unsupported(
            fields,
            f"{body.parameter} = {body.value_mm:g} mm is outside its finite domain.",
            status="outside_domain",
        )
    lip = data.parameters.lip_mm.value
    is_base = target == "stand-base"
    patch = RepairPatch(
        id="probe-" + target,
        base_version_id=plan.version_id,
        kind="resize_part",
        target_id=target,
        replacement_stock_id=None,
        replacement_profile_id=None,
        width_mm=part.geometry.width,
        height_mm=body.value_mm if is_base else body.value_mm + lip,
        angle_deg=None,
        rationale="Bounded design probe; simulation only, nothing is committed.",
    )
    result = base.simulate(patch, remaining)
    return ProbeResult(
        **fields,
        previous_value_mm=part.geometry.height
        if is_base
        else part.geometry.height - lip,
        status="requires_repair",
        repair=RepairProbeSummary(
            patch_kind=patch.kind,
            target_part_id=target,
            status=result.status,
            preserved_operation_ids=result.preserved_operation_ids[:64],
            undo_operation_ids=result.required_undo_operation_ids[:64],
            recheck_ids=result.invalidated_checkpoint_ids[:64],
            blockers=result.blockers[:32],
        ),
    )


def run_select(
    store, owner, project_id, body, resolver, plan_service
) -> PlanCompileResult:
    """Recheck the design server-side, then save an ordinary proposed preview.

    A saved selection replays by key before any freshness check, so retrying a
    lost response can never save a second preview.
    """
    scope = project_id + ":synthesis-select"
    payload = body.model_dump(mode="json")
    with store.transaction() as connection:
        store.read(connection, owner, project_id)
        digest, replay = store.replay(
            connection, owner, scope, body.idempotency_key, payload
        )
    if replay is not None:
        return PlanCompileResult.model_validate(replay)
    data = resolve(store, owner, project_id, body, resolver)
    _require_search(data, body)
    if data.identity.active_version_id is not None:
        return _blocked(
            "A build is already active for this project; change it through the repair flow."
        )
    missing = missing_inputs(data)
    if missing:
        return PlanCompileResult(
            status="needs_measurement", blockers=tuple(missing[:16])
        )
    problems = check_design(data, body.design)
    if problems:
        return PlanCompileResult(status="blocked", blockers=tuple(problems[:16]))
    report = evaluate(data, body.design)
    if report.status != "acceptable":
        failures = tuple(
            Blocker(code="geometry_invalid", message=c.detail)
            for c in report.checks
            if c.status == "modeled_failure"
        )
        return PlanCompileResult(
            status="blocked", blockers=(report.blockers or failures)[:16]
        )
    try:
        result = plan_service.compile_preview(
            owner,
            project_id,
            CompilePreview(
                expected_revision_id=data.identity.inventory_revision_id,
                idempotency_key=body.idempotency_key,
                candidate=design_candidate(body.design),
            ),
            process=data.process,
            parameters=stand_parameters(data.parameters, body.design),
            joint_profiles=data.joint_profiles,
            kerf_mm=data.kerf_mm,
            edge_margin_mm=data.edge_margin_mm,
        )
    except ProjectError as error:
        if error.status != 409 or error.envelope.code != "blocked":
            raise
        if "At most two designs" in error.envelope.message:
            return _blocked(
                "Two proposed designs are already saved for this inventory. Review "
                "or approve one of the saved plans below; nothing new was saved."
            )
        return _blocked(
            "A build is already active for this project; change it through the repair flow."
        )
    if result.status == "accepted":
        with store.transaction() as connection:
            prior = connection.execute(
                "SELECT 1 FROM requests WHERE owner=? AND scope=? AND key=?",
                (owner, scope, body.idempotency_key),
            ).fetchone()
            if prior is None:
                store.remember(
                    connection,
                    owner,
                    scope,
                    body.idempotency_key,
                    digest,
                    result.model_dump(mode="json"),
                )
    return result


def _blocked(message: str) -> PlanCompileResult:
    return PlanCompileResult(
        status="blocked", blockers=(Blocker(code="unsupported", message=message),)
    )
