"""Repair previews and explicit atomic approval; simulation never commits."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from forma_compiler import CutProcess
from forma_renderer import (
    StandParameters,
    diff_manuals,
    render_manual,
    stand_continuation_blockers,
)
from forma_renderer.template import profile_evidence_valid
from forma_replanner import SimulationResult, rank_feasible, simulate_patch
from pydantic import AwareDatetime, Field, model_validator

from forma_api.plans import (
    PlanRevision,
    PlanVersion,
    manual_document,
    read_revision,
)
from forma_api.progress import snapshot
from forma_api.projects import Key, Project, ProjectError, ProjectStore
from forma_domain.models import (
    ID,
    Blocker,
    BuildPlan,
    Evidence,
    EvidenceInvalidation,
    MaterialTransaction,
    Measurement,
    Nonnegative,
    PhysicalEvent,
    Record,
    RepairPatch,
    ReplannerInput,
    Stock,
)

# Production previews require measured process and reviewed profile evidence.
# Tests opt in explicitly to compile synthetic fixtures.
ALLOW_SYNTHETIC = False


class ConnectorMeasurement(Record):
    stock_id: ID
    remaining_length_mm: Nonnegative


class AdaptSimulateRequest(Record):
    expected_version_id: ID
    expected_last_event_id: ID | None
    idempotency_key: Key
    candidates: tuple[RepairPatch, ...] = Field(min_length=1, max_length=3)
    connector_measurements: tuple[ConnectorMeasurement, ...] = Field(
        default=(), max_length=8
    )
    remaining_confirmed: Literal[True]

    @model_validator(mode="after")
    def distinct(self):
        if len({c.id for c in self.candidates}) != len(self.candidates):
            raise ValueError("Duplicate candidate IDs")
        stock_ids = [item.stock_id for item in self.connector_measurements]
        if len(set(stock_ids)) != len(stock_ids):
            raise ValueError("Duplicate connector measurements")
        return self


class PanelDiff(Record):
    unchanged: tuple[int, ...]
    changed: tuple[int, ...]
    added: tuple[int, ...]
    removed: tuple[int, ...]


class AdaptPreview(Record):
    preview_id: ID
    rank: int | None = None
    patch: RepairPatch
    simulation: SimulationResult
    version: PlanVersion | None = None
    panel_diff: PanelDiff | None = None
    render_blockers: tuple[Blocker, ...] = ()


class AdaptPreviewSet(Record):
    project_id: ID
    base_version_id: ID
    base_last_event_id: ID | None
    remaining_stock: tuple[Stock, ...]
    previews: tuple[AdaptPreview, ...]
    replayed: bool = False


class StoredPreview(Record):
    preview: AdaptPreview
    base_last_event_id: ID | None
    remaining_stock: tuple[Stock, ...]
    created_at: AwareDatetime


class AdaptCommitRequest(Record):
    expected_version_id: ID
    expected_last_event_id: ID | None
    preview_id: ID
    idempotency_key: Key
    user_approved: Literal[True]


class AdaptCommitResult(Record):
    project: Project
    revision: PlanRevision
    invalidations: tuple[EvidenceInvalidation, ...]
    replayed: bool = False


class _Base:
    """Trusted saved inputs for simulating repairs of one active version."""

    def __init__(self, connection, project_id: str, version_id: str):
        row = connection.execute(
            "SELECT body, process, parameters FROM plans "
            "WHERE project_id=? AND version_id=?",
            (project_id, version_id),
        ).fetchone()
        if row is None:
            raise ProjectError(404, "not_found", "Plan not found")
        self.version = PlanVersion.model_validate_json(row[0])
        self.process_json, self.parameters_json = row[1], row[2]
        self.process = CutProcess.model_validate_json(row[1])
        self.parameters = StandParameters.model_validate_json(row[2])
        self.progress = snapshot(connection, self.version.plan)
        self.ancestors = _ancestors(connection, project_id, self.version.plan)
        versions = (self.version.plan.version_id,) + tuple(
            plan.version_id for plan in self.ancestors
        )
        self.events = _records(
            connection, "progress_events", PhysicalEvent, project_id, versions
        )
        self.evidence = _records(
            connection, "progress_evidence", Evidence, project_id, versions
        )
        self.transactions = _records(
            connection, "progress_material", MaterialTransaction, project_id, versions
        )

    def simulate(
        self, patch: RepairPatch, remaining: tuple[Stock, ...]
    ) -> SimulationResult:
        plan = self.version.plan
        if not profile_evidence_valid(
            plan.joint_profiles,
            self.parameters.profile_evidence,
            plan.project_id,
            allow_synthetic=ALLOW_SYNTHETIC,
        ):
            return SimulationResult(
                patch_id=patch.id,
                base_version_id=plan.version_id,
                status="blocked",
                blockers=(
                    Blocker(
                        code="unsupported_profile",
                        message="Resolve measured profile evidence before simulating a repair.",
                    ),
                ),
            )
        return simulate_patch(
            ReplannerInput(
                base_plan=plan,
                events=self.events,
                evidence=self.evidence,
                material_transactions=self.transactions,
                remaining_stock=remaining,
                patch=patch,
            ),
            process=self.process,
            allow_synthetic=ALLOW_SYNTHETIC,
            historical_plans=self.ancestors,
            family_validator=stand_continuation_blockers,
        )

    def render(self, plan: BuildPlan):
        return render_manual(
            plan,
            process=self.process,
            profile_evidence=self.parameters.profile_evidence,
            allow_synthetic=ALLOW_SYNTHETIC,
        )


def _ancestors(connection, project_id: str, plan: BuildPlan) -> tuple[BuildPlan, ...]:
    found = []
    parent = plan.parent_version_id
    while parent is not None:
        row = connection.execute(
            "SELECT body FROM plans WHERE project_id=? AND version_id=?",
            (project_id, parent),
        ).fetchone()
        if row is None or any(p.version_id == parent for p in found):
            raise ProjectError(409, "blocked", "Plan history is incomplete")
        ancestor = PlanVersion.model_validate_json(row[0]).plan
        found.append(ancestor)
        parent = ancestor.parent_version_id
    return tuple(found)


def _records(connection, table, model, project_id, versions):
    marks = ",".join("?" for _ in versions)
    return tuple(
        model.model_validate_json(row[0])
        for row in connection.execute(
            f"SELECT body FROM {table} WHERE project_id=? "
            f"AND version_id IN ({marks}) ORDER BY rowid",
            (project_id, *versions),
        )
    )


def _remaining(base: _Base, body: AdaptSimulateRequest) -> tuple[Stock, ...]:
    measured = {
        item.stock_id: item.remaining_length_mm for item in body.connector_measurements
    }
    stocks = []
    for stock in base.progress.expected_remaining_stock:
        length = stock.remaining_length_mm
        # Confirmed joins turn the connector balance into an unconfirmed
        # calculation; the replanner only accepts an actual measurement.
        spent = stock.kind in ("tape", "cord") and length.source == "calculated"
        if spent and not length.confirmed:
            if stock.id not in measured:
                raise ProjectError(
                    422,
                    "validation_error",
                    "Measure the remaining connector length before simulating a repair",
                )
            stock = stock.model_copy(
                update={
                    "remaining_length_mm": Measurement(
                        value=measured.pop(stock.id),
                        unit="mm",
                        source="user_ruler",
                        confirmed=True,
                    )
                }
            )
        stocks.append(stock)
    if measured:
        raise ProjectError(
            422,
            "validation_error",
            "Only connectors used by confirmed work need a measurement",
        )
    return tuple(stocks)


def _require_base(project: Project, base: _Base, body) -> None:
    if project.active_version_id != body.expected_version_id:
        raise ProjectError(409, "stale_version", "The active plan changed; reload it")
    if base.progress.last_event_id != body.expected_last_event_id:
        raise ProjectError(409, "stale_version", "Physical history changed; reload it")


def adapt_router(store: ProjectStore, authenticate) -> APIRouter:
    router = APIRouter()
    Owner = Annotated[str, Depends(authenticate)]

    @router.post("/{project_id}/adapt/simulate", response_model=AdaptPreviewSet)
    def simulate(
        project_id: ID, body: AdaptSimulateRequest, owner: Owner, response: Response
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            scope = project_id + ":adapt-simulate"
            digest, replay = store.replay(
                connection,
                owner,
                scope,
                body.idempotency_key,
                body.model_dump(mode="json"),
            )
            if replay is not None:
                return replay
            if project.active_version_id != body.expected_version_id:
                raise ProjectError(
                    409, "stale_version", "The active plan changed; reload it"
                )
            base = _Base(connection, project_id, body.expected_version_id)
            _require_base(project, base, body)
            remaining = _remaining(base, body)
            results = {
                patch.id: base.simulate(patch, remaining) for patch in body.candidates
            }
            ranked = rank_feasible(tuple(results.values()))
            ranks = {result.patch_id: index + 1 for index, result in enumerate(ranked)}
            old_manual = base.render(base.version.plan)
            created_at = datetime.now(UTC)
            previews = []
            order = [r.patch_id for r in ranked] + [
                p.id for p in body.candidates if p.id not in ranks
            ]
            patches = {patch.id: patch for patch in body.candidates}
            for patch_id in order:
                result = results[patch_id]
                preview = AdaptPreview(
                    preview_id="preview-" + uuid4().hex,
                    patch=patches[patch_id],
                    simulation=result,
                )
                if result.status == "feasible":
                    manual = base.render(result.plan)
                    if manual.status == "accepted":
                        change = diff_manuals(old_manual, manual)
                        preview = preview.model_copy(
                            update={
                                "rank": ranks[patch_id],
                                "version": PlanVersion(
                                    project_id=project_id,
                                    version_id=result.plan.version_id,
                                    inventory_revision_id=project.revision_id,
                                    candidate_id=patch_id,
                                    created_at=created_at,
                                    plan=result.plan,
                                    manual=manual_document(
                                        project_id, result.plan, manual
                                    ),
                                ),
                                "panel_diff": PanelDiff(
                                    unchanged=change.unchanged,
                                    changed=change.changed,
                                    added=change.added,
                                    removed=change.removed,
                                ),
                            }
                        )
                    else:
                        preview = preview.model_copy(
                            update={"render_blockers": manual.blockers}
                        )
                previews.append(preview)
                connection.execute(
                    "INSERT INTO adapt_previews VALUES (?, ?, ?, ?)",
                    (
                        preview.preview_id,
                        project_id,
                        body.expected_version_id,
                        StoredPreview(
                            preview=preview,
                            base_last_event_id=body.expected_last_event_id,
                            remaining_stock=remaining,
                            created_at=created_at,
                        ).model_dump_json(),
                    ),
                )
            result = AdaptPreviewSet(
                project_id=project_id,
                base_version_id=body.expected_version_id,
                base_last_event_id=body.expected_last_event_id,
                remaining_stock=remaining,
                previews=tuple(previews),
            ).model_dump(mode="json")
            store.remember(
                connection, owner, scope, body.idempotency_key, digest, result
            )
            return result

    @router.post("/{project_id}/adapt/commit", response_model=AdaptCommitResult)
    def commit(
        project_id: ID, body: AdaptCommitRequest, owner: Owner, response: Response
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            scope = project_id + ":adapt-commit"
            digest, replay = store.replay(
                connection,
                owner,
                scope,
                body.idempotency_key,
                body.model_dump(mode="json"),
            )
            if replay is not None:
                return replay
            if project.active_version_id != body.expected_version_id:
                raise ProjectError(
                    409, "stale_version", "The active plan changed; reload it"
                )
            row = connection.execute(
                "SELECT body FROM adapt_previews WHERE id=? AND project_id=? "
                "AND base_version_id=?",
                (body.preview_id, project_id, body.expected_version_id),
            ).fetchone()
            if row is None:
                raise ProjectError(404, "not_found", "Repair preview not found")
            stored = StoredPreview.model_validate_json(row[0])
            base = _Base(connection, project_id, body.expected_version_id)
            _require_base(project, base, body)
            if stored.base_last_event_id != body.expected_last_event_id:
                raise ProjectError(
                    409, "stale_version", "Physical history changed; simulate again"
                )
            preview = stored.preview
            if preview.version is None:
                raise ProjectError(
                    409, "blocked", "This repair candidate cannot be approved"
                )
            # Re-derive the revision from saved history instead of trusting the
            # stored draft; any drift means the preview is no longer accurate.
            result = base.simulate(preview.patch, stored.remaining_stock)
            if result != preview.simulation:
                raise ProjectError(
                    409, "stale_version", "Repair inputs changed; simulate again"
                )
            incomplete = set(result.incomplete_operation_ids)
            carried = tuple(
                op.id for op in result.plan.operations if op.id not in incomplete
            )
            if not set(carried) <= set(base.progress.completed_operation_ids):
                raise ProjectError(
                    409, "blocked", "Repair preview does not match recorded work"
                )
            approved_at = datetime.now(UTC)
            version = preview.version
            revision = PlanRevision(
                version_id=version.version_id,
                base_version_id=body.expected_version_id,
                base_last_event_id=body.expected_last_event_id,
                preview_id=preview.preview_id,
                patch=preview.patch,
                simulation=result,
                carried_completed_operation_ids=carried,
                approved_at=approved_at,
            )
            if read_revision(connection, project_id, version.version_id) is not None:
                raise ProjectError(409, "blocked", "This revision already exists")
            connection.execute(
                "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)",
                (
                    version.version_id,
                    project_id,
                    version.inventory_revision_id,
                    version.model_dump_json(),
                    base.process_json,
                    base.parameters_json,
                ),
            )
            connection.execute(
                "INSERT INTO plan_revisions VALUES (?, ?, ?, ?)",
                (
                    version.version_id,
                    project_id,
                    body.expected_version_id,
                    revision.model_dump_json(),
                ),
            )
            invalidations = tuple(
                EvidenceInvalidation(
                    id="invalidation-" + uuid4().hex,
                    evidence_id=evidence_id,
                    invalidated_for_version_id=version.version_id,
                    reason="Approved repair changed a part, operation or check this evidence describes.",
                    recorded_at=approved_at,
                )
                for evidence_id in result.invalidated_evidence_ids
            )
            for item in invalidations:
                connection.execute(
                    "INSERT INTO evidence_invalidations VALUES (?, ?, ?, ?, ?)",
                    (
                        item.id,
                        project_id,
                        item.evidence_id,
                        version.version_id,
                        item.model_dump_json(),
                    ),
                )
            updated = Project(
                **{**project.model_dump(), "active_version_id": version.version_id}
            )
            connection.execute(
                "UPDATE projects SET body=? WHERE id=? AND owner=?",
                (updated.model_dump_json(), project_id, owner),
            )
            outcome = AdaptCommitResult(
                project=updated, revision=revision, invalidations=invalidations
            ).model_dump(mode="json")
            store.remember(
                connection, owner, scope, body.idempotency_key, digest, outcome
            )
            return outcome

    return router
