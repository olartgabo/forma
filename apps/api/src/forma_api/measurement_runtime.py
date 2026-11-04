"""Owner-scoped measurement decisions (#149).

Reads authorized facts from the existing design-search and stability services
and applies the pure decision rule. It stores no measurements: stock and
requirement answers go through the existing inventory confirmation, and
assembled-stand answers through the #146 measurement flow. The only write here
is a "measurement unavailable" marker in the existing request-receipt table.
"""

import json
from typing import Literal

from forma_measurement import (
    ActiveFacts,
    CaseMargin,
    active_decision,
    compare,
    design_decision,
)
from forma_synthesizer import search

from forma_api import stability_reports as reports
from forma_api import synthesis_runtime
from forma_api.projects import Key, ProjectError
from forma_domain.measurement_contracts import (
    DecisionChange,
    MeasurementDecision,
    TargetKey,
)
from forma_domain.models import ID, Record

SCOPE = ":measurement-unavailable"


class DecisionRequest(Record):
    expected_inventory_revision_id: ID
    expected_active_version_id: ID | None


class UnavailableRequest(DecisionRequest):
    expected_last_event_id: ID | None
    question_id: str
    target_key: TargetKey
    idempotency_key: Key
    user_confirmed: Literal[True]


class RecalculateRequest(DecisionRequest):
    baseline: MeasurementDecision


class _Identity(Record):
    """The search/stability identity request shapes the existing services take."""

    expected_inventory_revision_id: ID
    expected_active_version_id: ID | None
    expected_last_event_id: ID | None
    plan_version_id: ID | None = None


def default_context_resolver():
    return synthesis_runtime.default_context_resolver()


def _declined(connection, owner, project_id) -> frozenset[str]:
    rows = connection.execute(
        "SELECT response FROM requests WHERE owner=? AND scope=?",
        (owner, project_id + SCOPE),
    ).fetchall()
    return frozenset(json.loads(row[0])["target_key"] for row in rows)


def _stale_previews(connection, project) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT version_id FROM plans WHERE project_id=? AND inventory_revision_id<>? ORDER BY rowid",
        (project.id, project.revision_id),
    ).fetchall()
    if not rows or project.active_version_id is not None:
        return ()
    return (
        f"{len(rows)} proposed plan(s) saved for an earlier inventory can no longer be approved; search again.",
    )


def _identity(store, owner, project_id, body: DecisionRequest) -> _Identity:
    with store.transaction() as connection:
        project = store.read(connection, owner, project_id)
        if project.revision_id != body.expected_inventory_revision_id:
            raise ProjectError(409, "stale_version", "Inventory changed; reload it")
        if project.active_version_id != body.expected_active_version_id:
            raise ProjectError(
                409, "stale_version", "The active plan changed; reload it"
            )
        row = connection.execute(
            "SELECT id FROM progress_events WHERE project_id=? ORDER BY rowid DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    return _Identity(
        expected_inventory_revision_id=project.revision_id,
        expected_active_version_id=project.active_version_id,
        expected_last_event_id=row[0] if row else None,
        plan_version_id=project.active_version_id,
    )


def decide(store, owner, project_id, body: DecisionRequest, resolver):
    """Read-only. The decision is computed from one authorized snapshot."""
    request = _identity(store, owner, project_id, body)
    data = synthesis_runtime.resolve(store, owner, project_id, request, resolver)
    with store.transaction() as connection:
        project = store.read(connection, owner, project_id)
        declined = _declined(connection, owner, project_id)
        invalidated = _stale_previews(connection, project)
        if request.plan_version_id is not None:
            snapshot = reports.authorized_snapshot(
                connection, store, owner, project_id, request
            )
            evaluation = reports.evaluate(snapshot, None)
    if request.plan_version_id is None:
        return design_decision(data, search(data), declined, invalidated)
    return active_decision(_active_facts(data, snapshot, evaluation), declined)


def _active_facts(data, snapshot, evaluation) -> ActiveFacts:
    response = evaluation.response
    report = response.report
    geometry = response.geometry_preview
    stage = geometry.stage if geometry is not None else None
    if report is not None:
        stage = "reported_assembled"
    cases, required, band = (), None, None
    if report is not None:
        overlays = {o.case_id: o.signed_margin_m for o in report.overlays}
        statuses = {}
        for result in report.results:
            if result.check_type == "tip":
                statuses[result.case_id] = result.status
        cases = tuple(
            CaseMargin(
                case_id=case,
                status=statuses.get(case, "not_run"),
                signed_margin_m=overlays.get(case),
            )
            for case in sorted(set(statuses) | set(overlays))
        )
        required = report.policy.required_margin_m
        record = snapshot.measurements
        if record is not None:
            data_ = record.measurements
            # First-order position resolution only (support edge plus the
            # coarsest centre-of-mass reading); not a conservative bound.
            band = data_.support.resolution_m + max(
                [data_.stand.position_resolution_m]
                + [c.device.position_resolution_m for c in data_.cases]
            )
    part_ids = (
        geometry.active_part_ids
        if geometry is not None
        else tuple(p.id for p in snapshot.version.plan.parts)
    )
    return ActiveFacts(
        data=data,
        plan_version_id=snapshot.version.version_id,
        analysis_status=response.status,
        stage=stage,
        part_ids=part_ids,
        blockers=tuple(response.blockers),
        cases=cases,
        required_margin_m=required,
        resolution_band_m=band,
    )


def mark_unavailable(store, owner, project_id, body: UnavailableRequest, resolver):
    """Record that the selected measurement cannot be taken, then decide again.

    A saved marker replays by key before any freshness check. The freshness
    check and the write share one write transaction.
    """
    scope = project_id + SCOPE
    payload = body.model_dump(mode="json")
    with store.transaction() as connection:
        store.read(connection, owner, project_id)
        digest, replay = store.replay(
            connection, owner, scope, body.idempotency_key, payload
        )
    if replay is None:
        current = decide(store, owner, project_id, body, resolver)
        question = current.question
        if (
            question is None
            or question.question_id != body.question_id
            or question.target.key != body.target_key
        ):
            raise ProjectError(
                409,
                "stale_version",
                "This is no longer the selected measurement; reload it",
            )
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            row = connection.execute(
                "SELECT id FROM progress_events WHERE project_id=? ORDER BY rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if (
                project.revision_id != body.expected_inventory_revision_id
                or project.active_version_id != body.expected_active_version_id
                or (row[0] if row else None) != body.expected_last_event_id
                or _declined(connection, owner, project_id)
                != frozenset(current.identity.declined_target_keys)
            ):
                raise ProjectError(
                    409, "stale_version", "The project changed; reload it"
                )
            store.remember(
                connection,
                owner,
                scope,
                body.idempotency_key,
                digest,
                {"target_key": body.target_key, "question_id": body.question_id},
            )
    # Saved or replayed, the answer is the project's current decision.
    with store.transaction() as connection:
        project = store.read(connection, owner, project_id)
    return decide(
        store,
        owner,
        project_id,
        DecisionRequest(
            expected_inventory_revision_id=project.revision_id,
            expected_active_version_id=project.active_version_id,
        ),
        resolver,
    )


def recalculate(
    store, owner, project_id, body: RecalculateRequest, resolver
) -> DecisionChange:
    """Explicit, bounded recalculation compared with an earlier decision."""
    if body.baseline.identity.project_id != project_id:
        raise ProjectError(
            422, "validation_error", "The earlier decision is for another project"
        )
    return compare(body.baseline, decide(store, owner, project_id, body, resolver))
