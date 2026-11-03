"""Bounded repair search over the active version, stored as ordinary previews.

Ranked candidates are saved exactly like adapt/simulate previews, so approval
goes through the existing atomic adapt/commit. Searching records no physical
event, receipt or revision.
"""

from typing import Literal

from forma_repair_search import generate_candidates, search_repairs
from pydantic import Field

from forma_api.adapt import (
    AdaptPreviewSet,
    ConnectorMeasurement,
    RepairBase,
    confirmed_remaining,
    require_current_base,
    save_previews,
)
from forma_api.fabrication_runtime import ProposedReports
from forma_api.projects import Key, Project, ProjectError
from forma_domain.models import ID, Record
from forma_domain.repair_search_contracts import (
    MAX_EVALUATED,
    REPAIR_SEARCH_VERSION,
    CandidateOutcome,
    RepairSearchLimits,
    RepairSearchSummary,
    ResizeMeasurement,
)


class RepairSearchRequest(Record):
    expected_version_id: ID
    expected_last_event_id: ID | None
    idempotency_key: Key
    target_ids: tuple[ID, ...] = Field(default=(), max_length=8)
    resize_measurements: tuple[ResizeMeasurement, ...] = Field(default=(), max_length=8)
    connector_measurements: tuple[ConnectorMeasurement, ...] = Field(
        default=(), max_length=8
    )
    remaining_confirmed: Literal[True]
    max_evaluated: int = Field(default=MAX_EVALUATED, ge=1, le=MAX_EVALUATED)


class RepairSearchResult(Record):
    summary: RepairSearchSummary
    previews: AdaptPreviewSet
    replayed: bool = False


def _targets(base: RepairBase, body: RepairSearchRequest) -> tuple[str, ...]:
    plan = base.version.plan
    known = {p.id for p in plan.parts} | {j.id for j in plan.joints}
    if body.target_ids:
        if not set(body.target_ids) <= known:
            raise ProjectError(
                422, "validation_error", "Repair targets must be parts or joints"
            )
        return tuple(dict.fromkeys(body.target_ids))
    progress = base.progress
    if progress.damaged_part_ids:
        return progress.damaged_part_ids
    failed = set(progress.failed_operation_ids)
    parts = {
        part_id for op in plan.operations if op.id in failed for part_id in op.part_ids
    }
    if not parts:
        raise ProjectError(
            409,
            "blocked",
            "Report damage or a failed check, or choose a part to repair",
        )
    return tuple(p.id for p in plan.parts if p.id in parts)


def search(connection, project: Project, body: RepairSearchRequest) -> dict:
    if project.active_version_id != body.expected_version_id:
        raise ProjectError(409, "stale_version", "The active plan changed; reload it")
    base = RepairBase(connection, project.id, body.expected_version_id)
    require_current_base(project, base, body)
    remaining = confirmed_remaining(base, body.connector_measurements)
    targets = _targets(base, body)
    part_ids = {p.id for p in base.version.plan.parts}
    if any(
        size.part_id not in part_ids or size.part_id not in targets
        for size in body.resize_measurements
    ):
        raise ProjectError(
            422, "validation_error", "Measured sizes must name a target part"
        )
    limits = RepairSearchLimits(max_evaluated=body.max_evaluated, max_results=3)
    result = search_repairs(
        generate_candidates(
            base.version.plan, targets, remaining, body.resize_measurements
        ),
        limits=limits,
        simulate=lambda patch: base.simulate(patch, remaining),
        schedule=ProposedReports(connection, project),
        prior_plans=(base.version.plan, *base.ancestors),
    )
    shown = [
        o
        for o in result.outcomes
        if o.rank is not None and o.rank <= limits.max_results
    ]
    previews = save_previews(
        connection,
        project,
        base,
        remaining,
        body.expected_last_event_id,
        [(o.patch, o.simulation, o.rank) for o in shown],
    )
    preview_ids = {p.patch.id: p.preview_id for p in previews}
    summary = RepairSearchSummary(
        search_version=REPAIR_SEARCH_VERSION,
        status=result.status,
        target_ids=targets,
        generated_count=result.generated_count,
        evaluated_count=result.evaluated_count,
        limits=limits,
        outcomes=tuple(
            CandidateOutcome(
                patch=o.patch,
                status=o.status,
                rank=o.rank,
                preview_id=preview_ids.get(o.patch.id),
                blockers=o.blockers,
            )
            for o in result.outcomes
        ),
        unknown_cost_terms=("time", "purchase_price", "strength"),
        stability_coverage="unverified",
    )
    return RepairSearchResult(
        summary=summary,
        previews=AdaptPreviewSet(
            project_id=project.id,
            base_version_id=body.expected_version_id,
            base_last_event_id=body.expected_last_event_id,
            remaining_stock=remaining,
            previews=previews,
        ),
    ).model_dump(mode="json")
