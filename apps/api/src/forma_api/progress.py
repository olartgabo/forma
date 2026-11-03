"""Append-only user reports; expected stock is separate from physical measurement."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import Field, StringConstraints, model_validator

from forma_api.plans import PlanService, read_revision
from forma_api.projects import Key, ProjectError, ProjectStore
from forma_domain.models import (
    ID,
    BuildPlan,
    Evidence,
    MaterialTransaction,
    Measurement,
    PhysicalEvent,
    Record,
    Region,
    Stock,
)


class ProgressUpdate(Record):
    expected_version_id: ID
    expected_last_event_id: ID | None
    idempotency_key: Key
    operation_id: ID
    result: Literal["completed", "passed", "failed"]
    observation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    user_confirmed: Literal[True]
    checks_confirmed: Literal[True]
    photo_ids: tuple[ID, ...] = Field(default=(), max_length=8)

    @model_validator(mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if isinstance(value, dict) and any(
            value.get(field) is not True
            for field in ("user_confirmed", "checks_confirmed")
        ):
            raise ValueError("Explicit confirmation is required")
        return value

    @model_validator(mode="after")
    def distinct_photos(self):
        if len(set(self.photo_ids)) != len(self.photo_ids):
            raise ValueError("Duplicate photo IDs")
        return self


class DamageReport(Record):
    """Damage the builder saw, tied to the step where it happened."""

    expected_version_id: ID
    expected_last_event_id: ID | None
    idempotency_key: Key
    operation_id: ID
    part_ids: tuple[ID, ...] = Field(min_length=1, max_length=16)
    observation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    user_confirmed: Literal[True]
    photo_ids: tuple[ID, ...] = Field(default=(), max_length=8)

    @model_validator(mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if isinstance(value, dict) and value.get("user_confirmed") is not True:
            raise ValueError("Explicit confirmation is required")
        return value

    @model_validator(mode="after")
    def distinct_ids(self):
        if len(set(self.photo_ids)) != len(self.photo_ids):
            raise ValueError("Duplicate photo IDs")
        if len(set(self.part_ids)) != len(self.part_ids):
            raise ValueError("Duplicate part IDs")
        return self


class MaterialReport(Record):
    """Material the builder discarded, lost or recovered at a step.

    Sheet waste names a whole current region; connector waste is a measured
    length lost on a tape joint; salvage returns a region wasted earlier in
    this version. These are the only losses the replanner can reconcile."""

    expected_version_id: ID
    expected_last_event_id: ID | None
    idempotency_key: Key
    operation_id: ID
    kind: Literal["waste", "salvage"]
    stock_id: ID
    region_id: ID | None = None
    length_mm: Annotated[float, Field(gt=0)] | None = None
    observation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    user_confirmed: Literal[True]
    photo_ids: tuple[ID, ...] = Field(default=(), max_length=8)

    @model_validator(mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if isinstance(value, dict) and value.get("user_confirmed") is not True:
            raise ValueError("Explicit confirmation is required")
        return value

    @model_validator(mode="after")
    def one_quantity(self):
        if (self.region_id is None) == (self.length_mm is None):
            raise ValueError("Give either a region or a measured length")
        if self.kind == "salvage" and self.region_id is None:
            raise ValueError("Salvage returns a previously wasted region")
        if len(set(self.photo_ids)) != len(self.photo_ids):
            raise ValueError("Duplicate photo IDs")
        return self


class ProgressSnapshot(Record):
    project_id: ID
    version_id: ID
    last_event_id: ID | None
    events: tuple[PhysicalEvent, ...]
    evidence: tuple[Evidence, ...]
    material_transactions: tuple[MaterialTransaction, ...]
    completed_operation_ids: tuple[ID, ...]
    carried_operation_ids: tuple[ID, ...] = ()
    failed_operation_ids: tuple[ID, ...]
    damaged_part_ids: tuple[ID, ...] = ()
    expected_remaining_stock: tuple[Stock, ...]
    status: Literal["not_started", "building", "needs_review", "passed"]


class ProgressResult(Record):
    progress: ProgressSnapshot
    replayed: bool = False


def expected_stock(
    plan: BuildPlan,
    completed: set[str],
    transactions: tuple[MaterialTransaction, ...] = (),
) -> tuple[Stock, ...]:
    regions = {stock.id: list(stock.usable_regions) for stock in plan.stocks}
    # Account in reported decimal lengths without rounding away consumed stock.
    lengths = {
        stock.id: Decimal(str(stock.remaining_length_mm.value))
        if stock.remaining_length_mm.value is not None
        else None
        for stock in plan.stocks
    }
    used_connectors = set()
    for operation in plan.operations:
        if operation.id not in completed:
            continue
        if operation.type == "cut_rect":
            sid = operation.args.stock_id
            regions[sid] = [
                region
                for region in regions[sid]
                if region.id != operation.args.source_region_id
            ] + list(operation.effects.created_offcuts)
        elif operation.type == "tape_joint":
            sid = operation.args.stock_id
            amount = Decimal(str(operation.args.length_mm))
            if lengths[sid] is None or lengths[sid] < amount:
                raise ProjectError(409, "blocked", "Confirmed use exceeds known stock")
            lengths[sid] -= amount
            used_connectors.add(sid)
    # Recorded losses and salvage, in ingestion order, as the replanner applies them.
    for item in transactions:
        sid = item.source_stock_id
        if item.kind == "waste" and item.unit == "mm":
            amount = Decimal(str(item.quantity))
            if lengths[sid] is None or lengths[sid] < amount:
                raise ProjectError(409, "blocked", "Recorded loss exceeds known stock")
            lengths[sid] -= amount
            used_connectors.add(sid)
        elif item.kind == "waste":
            regions[sid] = [r for r in regions[sid] if r.id != item.source_region_id]
        elif item.kind == "salvage":
            regions[sid] = regions[sid] + [item.output_region]
    return tuple(
        Stock(
            **{
                **stock.model_dump(),
                "usable_regions": tuple(regions[stock.id]),
                "remaining_length_mm": Measurement(
                    value=float(lengths[stock.id]),
                    unit="mm",
                    source="calculated",
                    confirmed=False,
                )
                if stock.id in used_connectors
                else stock.remaining_length_mm,
            }
        )
        for stock in plan.stocks
    )


def snapshot(connection, plan: BuildPlan) -> ProgressSnapshot:
    def records(table, model):
        return tuple(
            model.model_validate_json(row[0])
            for row in connection.execute(
                f"SELECT body FROM {table} WHERE project_id=? AND version_id=? ORDER BY rowid",
                (plan.project_id, plan.version_id),
            )
        )

    events = records("progress_events", PhysicalEvent)
    evidence = records("progress_evidence", Evidence)
    transactions = records("progress_material", MaterialTransaction)
    revision = read_revision(connection, plan.project_id, plan.version_id)
    carried = set(revision.carried_completed_operation_ids) if revision else set()
    completed = carried | {
        event.operation_id for event in events if event.kind == "operation_confirmed"
    }
    # Reported damage pauses the build like a failed check. The damage itself
    # is user-confirmed, which the replanner requires before a replacement.
    failed = {
        event.operation_id
        for event in events
        if event.verification_state == "failed" or event.kind == "damage"
    }
    damage_evidence = {
        evidence_id
        for event in events
        if event.kind == "damage"
        for evidence_id in event.evidence_ids
    }
    damaged = {
        part_id
        for item in evidence
        if item.id in damage_evidence
        for part_id in item.part_ids
    }
    status = "not_started"
    if failed:
        status = "needs_review"
    elif events or carried:
        status = (
            "passed"
            if (
                all(operation.id in completed for operation in plan.operations)
                and any(
                    event.kind == "test" and event.test_result == "passed"
                    for event in events
                )
            )
            else "building"
        )
    return ProgressSnapshot(
        project_id=plan.project_id,
        version_id=plan.version_id,
        last_event_id=events[-1].id if events else None,
        events=events,
        evidence=evidence,
        material_transactions=transactions,
        completed_operation_ids=tuple(
            op.id for op in plan.operations if op.id in completed
        ),
        carried_operation_ids=tuple(
            op.id for op in plan.operations if op.id in carried
        ),
        failed_operation_ids=tuple(op.id for op in plan.operations if op.id in failed),
        damaged_part_ids=tuple(part.id for part in plan.parts if part.id in damaged),
        expected_remaining_stock=expected_stock(plan, completed, transactions),
        status=status,
    )


def record_diagnosis_evidence(
    connection,
    *,
    project_id,
    version_id,
    operation_id,
    media_id,
    diagnosis,
    part_ids,
) -> None:
    """Append a validated Muse diagnosis as unverified model evidence.

    Idempotent for an identical diagnosis: the deterministic id makes a
    retry an INSERT OR IGNORE no-op, while a different diagnosis appends.
    Only the media id is stored; never photo bytes.
    """
    sections = [f"Muse diagnosis (unverified): {diagnosis.failure_type}"]
    for label, items in (
        ("Visible observations", diagnosis.visible_observations),
        ("Hypotheses", diagnosis.hypotheses),
        ("Questions or measurements", diagnosis.questions_or_measurements),
    ):
        if items:
            sections.append(f"{label}: " + "; ".join(items))
    description = "\n".join(sections)[:2000]
    canonical = json.dumps(
        {
            "project_id": project_id,
            "version_id": version_id,
            "operation_id": operation_id,
            "media_id": media_id,
            "diagnosis": diagnosis.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    evidence = Evidence(
        id="evidence-" + hashlib.sha256(canonical.encode()).hexdigest(),
        project_id=project_id,
        version_id=version_id,
        kind="model_interpretation",
        provenance="model",
        verification_state="vision_observed",
        asset_id=media_id,
        operation_ids=(operation_id,),
        part_ids=tuple(part_ids),
        recorded_at=datetime.now(UTC),
        description=description,
    )
    connection.execute(
        "INSERT OR IGNORE INTO progress_evidence VALUES (?, ?, ?, ?, ?)",
        (
            evidence.id,
            project_id,
            version_id,
            evidence.asset_id,
            evidence.model_dump_json(),
        ),
    )


def _require_photos(connection, project_id: str, photo_ids) -> None:
    for photo_id in photo_ids:
        if (
            connection.execute(
                "SELECT 1 FROM media WHERE project_id=? AND id=?",
                (project_id, photo_id),
            ).fetchone()
            is None
        ):
            raise ProjectError(422, "validation_error", "Photo is outside this project")


def _next_recorded_at(current: ProgressSnapshot) -> datetime:
    # Keep server ingestion order even if the clock moves backwards.
    recorded_at = datetime.now(UTC)
    if current.events and recorded_at <= current.events[-1].recorded_at:
        recorded_at = current.events[-1].recorded_at + timedelta(microseconds=1)
    return recorded_at


def _append(connection, project_id, version_id, evidence, events, transactions=()):
    for item in evidence:
        connection.execute(
            "INSERT INTO progress_evidence VALUES (?, ?, ?, ?, ?)",
            (item.id, project_id, version_id, item.asset_id, item.model_dump_json()),
        )
    for item in events:
        connection.execute(
            "INSERT INTO progress_events VALUES (?, ?, ?, ?)",
            (item.id, project_id, version_id, item.model_dump_json()),
        )
    for item in transactions:
        connection.execute(
            "INSERT INTO progress_material VALUES (?, ?, ?, ?)",
            (item.id, project_id, version_id, item.model_dump_json()),
        )


def _known_region(plan: BuildPlan, stock_id: str, region_id: str) -> Region | None:
    """A region of this stock as originally recorded or created by a planned cut."""
    for stock in plan.stocks:
        if stock.id == stock_id:
            for region in stock.usable_regions:
                if region.id == region_id:
                    return region
    for operation in plan.operations:
        if operation.type == "cut_rect" and operation.args.stock_id == stock_id:
            for region in operation.effects.created_offcuts:
                if region.id == region_id:
                    return region
    return None


def progress_router(store: ProjectStore, authenticate) -> APIRouter:
    router = APIRouter()
    plans = PlanService(store)
    Owner = Annotated[str, Depends(authenticate)]

    @router.get(
        "/{project_id}/versions/{version_id}/progress", response_model=ProgressSnapshot
    )
    def get_progress(project_id: ID, version_id: ID, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            return snapshot(
                connection, plans.read(connection, project_id, version_id).plan
            )

    @router.post("/{project_id}/events", response_model=ProgressResult)
    def report(project_id: ID, body: ProgressUpdate, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            scope = project_id + ":progress"
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
            plan = plans.read(connection, project_id, body.expected_version_id).plan
            current = snapshot(connection, plan)
            if current.last_event_id != body.expected_last_event_id:
                raise ProjectError(
                    409, "stale_version", "Physical history changed; reload it"
                )
            operation = next(
                (op for op in plan.operations if op.id == body.operation_id), None
            )
            if operation is None:
                raise ProjectError(422, "validation_error", "Unknown operation")
            if operation.type not in {
                "cut_rect",
                "fold",
                "tape_joint",
                "detach",
                "inspect",
                "functional_test",
            }:
                raise ProjectError(
                    409, "blocked", "This operation needs a supported progress flow"
                )
            if current.failed_operation_ids:
                raise ProjectError(
                    409, "blocked", "Review the failed check before continuing"
                )
            if operation.id in current.completed_operation_ids:
                raise ProjectError(409, "blocked", "This operation is already recorded")
            if not set(operation.depends_on) <= set(current.completed_operation_ids):
                raise ProjectError(
                    409, "blocked", "Complete the operation prerequisites first"
                )
            checking = operation.type in {"inspect", "functional_test"}
            if (body.result == "completed") == checking:
                raise ProjectError(
                    422, "validation_error", "Result does not match the operation"
                )
            if operation.preconditions.confirmed_measurement_ids:
                raise ProjectError(
                    409,
                    "blocked",
                    "Measurement confirmation needs a supported progress flow",
                )
            _require_photos(connection, project_id, body.photo_ids)
            recorded_at = _next_recorded_at(current)
            failed = body.result == "failed"
            state = "failed" if failed else "user_confirmed"
            parts = tuple(
                dict.fromkeys(operation.part_ids + operation.effects.created_part_ids)
            )
            checks = tuple(
                check.id
                for check in plan.checkpoints
                if check.after_operation_id == operation.id
            )
            evidence = [
                Evidence(
                    id="evidence-" + uuid4().hex,
                    project_id=project_id,
                    version_id=plan.version_id,
                    kind="physical_test"
                    if operation.type == "functional_test"
                    else "user_report",
                    provenance="user",
                    operation_ids=(operation.id,),
                    part_ids=parts,
                    checkpoint_ids=checks,
                    recorded_at=recorded_at,
                    description=body.observation,
                    verification_state=state,
                )
            ]
            for photo_id in body.photo_ids:
                evidence.append(
                    Evidence(
                        id="evidence-" + uuid4().hex,
                        project_id=project_id,
                        version_id=plan.version_id,
                        kind="photo",
                        provenance="user",
                        asset_id=photo_id,
                        operation_ids=(operation.id,),
                        part_ids=parts,
                        checkpoint_ids=checks,
                        recorded_at=recorded_at,
                        description=body.observation,
                        verification_state=state,
                    )
                )
            shared = dict(
                project_id=project_id,
                version_id=plan.version_id,
                operation_id=operation.id,
                actor="user",
                observation=body.observation,
                recorded_at=recorded_at,
                evidence_ids=tuple(item.id for item in evidence),
                verification_state=state,
            )
            events = []
            if operation.type == "functional_test":
                events.append(
                    PhysicalEvent(
                        id="event-" + uuid4().hex,
                        kind="test",
                        test_result=body.result,
                        **shared,
                    )
                )
            if not failed:
                events.append(
                    PhysicalEvent(
                        id="event-" + uuid4().hex, kind="operation_confirmed", **shared
                    )
                )
            elif operation.type != "functional_test":
                events.append(
                    PhysicalEvent(
                        id="event-" + uuid4().hex, kind="observation", **shared
                    )
                )
            transactions = []
            completion = next(
                (event for event in events if event.kind == "operation_confirmed"), None
            )
            if completion and operation.type in {"cut_rect", "tape_joint"}:
                source = next(
                    stock
                    for stock in current.expected_remaining_stock
                    if stock.id == operation.args.stock_id
                )
                transaction_fields = dict(
                    project_id=project_id,
                    version_id=plan.version_id,
                    operation_id=operation.id,
                    source_stock_id=source.id,
                    physical_event_id=completion.id,
                    recorded_at=recorded_at,
                )
                if operation.type == "cut_rect":
                    region = next(
                        (
                            region
                            for region in source.usable_regions
                            if region.id == operation.args.source_region_id
                        ),
                        None,
                    )
                    if region is None:
                        raise ProjectError(
                            409, "blocked", "The cut source region is unavailable"
                        )
                    transactions.append(
                        MaterialTransaction(
                            id="material-" + uuid4().hex,
                            kind="consume",
                            source_region_id=region.id,
                            quantity=region.geometry.width * region.geometry.height,
                            unit="mm2",
                            **transaction_fields,
                        )
                    )
                    for offcut in operation.effects.created_offcuts:
                        transactions.append(
                            MaterialTransaction(
                                id="material-" + uuid4().hex,
                                kind="offcut",
                                output_region=offcut,
                                quantity=offcut.geometry.width * offcut.geometry.height,
                                unit="mm2",
                                **transaction_fields,
                            )
                        )
                else:
                    transactions.append(
                        MaterialTransaction(
                            id="material-" + uuid4().hex,
                            kind="consume",
                            quantity=operation.args.length_mm,
                            unit="mm",
                            **transaction_fields,
                        )
                    )
            _append(
                connection, project_id, plan.version_id, evidence, events, transactions
            )
            result = ProgressResult(progress=snapshot(connection, plan)).model_dump(
                mode="json"
            )
            store.remember(
                connection, owner, scope, body.idempotency_key, digest, result
            )
            return result

    @router.post("/{project_id}/damage", response_model=ProgressResult)
    def report_damage(
        project_id: ID, body: DamageReport, owner: Owner, response: Response
    ):
        """Record damage the builder saw. It pauses the build like a failed check
        until an approved revision; it consumes no stock and completes nothing."""
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            scope = project_id + ":damage"
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
            plan = plans.read(connection, project_id, body.expected_version_id).plan
            current = snapshot(connection, plan)
            if current.last_event_id != body.expected_last_event_id:
                raise ProjectError(
                    409, "stale_version", "Physical history changed; reload it"
                )
            if all(op.id != body.operation_id for op in plan.operations):
                raise ProjectError(422, "validation_error", "Unknown operation")
            if not set(body.part_ids) <= {part.id for part in plan.parts}:
                raise ProjectError(422, "validation_error", "Unknown part")
            _require_photos(connection, project_id, body.photo_ids)
            recorded_at = _next_recorded_at(current)
            shared = dict(
                project_id=project_id,
                version_id=plan.version_id,
                provenance="user",
                operation_ids=(body.operation_id,),
                part_ids=body.part_ids,
                recorded_at=recorded_at,
                description=body.observation,
                verification_state="user_confirmed",
            )
            evidence = [
                Evidence(id="evidence-" + uuid4().hex, kind="user_report", **shared)
            ] + [
                Evidence(
                    id="evidence-" + uuid4().hex,
                    kind="photo",
                    asset_id=photo_id,
                    **shared,
                )
                for photo_id in body.photo_ids
            ]
            event = PhysicalEvent(
                id="event-" + uuid4().hex,
                project_id=project_id,
                version_id=plan.version_id,
                operation_id=body.operation_id,
                kind="damage",
                evidence_ids=tuple(item.id for item in evidence),
                recorded_at=recorded_at,
                actor="user",
                observation=body.observation,
                verification_state="user_confirmed",
            )
            _append(connection, project_id, plan.version_id, evidence, [event])
            result = ProgressResult(progress=snapshot(connection, plan)).model_dump(
                mode="json"
            )
            store.remember(
                connection, owner, scope, body.idempotency_key, digest, result
            )
            return result

    @router.post("/{project_id}/materials", response_model=ProgressResult)
    def report_material(
        project_id: ID, body: MaterialReport, owner: Owner, response: Response
    ):
        """Record measured or discarded material. It changes expected stock and
        never completes work or changes build status."""
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            scope = project_id + ":materials"
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
            plan = plans.read(connection, project_id, body.expected_version_id).plan
            current = snapshot(connection, plan)
            if current.last_event_id != body.expected_last_event_id:
                raise ProjectError(
                    409, "stale_version", "Physical history changed; reload it"
                )
            operation = next(
                (op for op in plan.operations if op.id == body.operation_id), None
            )
            original = next((st for st in plan.stocks if st.id == body.stock_id), None)
            if operation is None or original is None:
                raise ProjectError(
                    422, "validation_error", "Unknown operation or stock"
                )
            remaining = next(
                st for st in current.expected_remaining_stock if st.id == original.id
            )
            transaction_fields = dict(
                project_id=project_id,
                version_id=plan.version_id,
                operation_id=operation.id,
                source_stock_id=original.id,
            )
            if original.kind in ("tape", "cord"):
                if body.length_mm is None or body.kind != "waste":
                    raise ProjectError(
                        422,
                        "validation_error",
                        "Connector loss is a measured length of waste",
                    )
                if (
                    operation.type not in ("tape_joint", "tie_joint")
                    or operation.args.stock_id != original.id
                ):
                    raise ProjectError(
                        422,
                        "validation_error",
                        "Record connector loss on a joint that uses this connector",
                    )
                if not original.remaining_length_mm.confirmed:
                    raise ProjectError(
                        409,
                        "blocked",
                        "Confirm the original connector length before recording loss",
                    )
                left = remaining.remaining_length_mm.value
                if left is None or body.length_mm > left:
                    raise ProjectError(
                        409, "blocked", "Recorded loss exceeds known stock"
                    )
                quantity = dict(quantity=body.length_mm, unit="mm")
                summary = f"{body.length_mm} mm of {original.id} lost"
            else:
                if body.region_id is None:
                    raise ProjectError(422, "validation_error", "Name the sheet region")
                if body.kind == "waste":
                    region = next(
                        (r for r in remaining.usable_regions if r.id == body.region_id),
                        None,
                    )
                    if region is None:
                        raise ProjectError(
                            409, "blocked", "That region is not currently usable"
                        )
                    quantity = dict(source_region_id=region.id)
                else:
                    wasted = {
                        item.source_region_id
                        for item in current.material_transactions
                        if item.kind == "waste" and item.unit == "mm2"
                    } - {
                        item.output_region.id
                        for item in current.material_transactions
                        if item.kind == "salvage"
                    }
                    region = _known_region(plan, original.id, body.region_id)
                    if body.region_id not in wasted or region is None:
                        raise ProjectError(
                            409,
                            "blocked",
                            "Only a region wasted in this version can be salvaged",
                        )
                    quantity = dict(output_region=region)
                area = region.geometry.width * region.geometry.height
                quantity |= dict(quantity=area, unit="mm2")
                summary = f"{original.id} region {region.id} ({area:g} mm2) " + (
                    "discarded" if body.kind == "waste" else "recovered"
                )
            _require_photos(connection, project_id, body.photo_ids)
            recorded_at = _next_recorded_at(current)
            shared = dict(
                project_id=project_id,
                version_id=plan.version_id,
                provenance="user",
                operation_ids=(operation.id,),
                recorded_at=recorded_at,
                description=f"{summary}. {body.observation}"[:2000],
                verification_state="user_confirmed",
            )
            evidence = [
                Evidence(id="evidence-" + uuid4().hex, kind="measurement", **shared)
            ] + [
                Evidence(
                    id="evidence-" + uuid4().hex,
                    kind="photo",
                    asset_id=photo_id,
                    **shared,
                )
                for photo_id in body.photo_ids
            ]
            event = PhysicalEvent(
                id="event-" + uuid4().hex,
                project_id=project_id,
                version_id=plan.version_id,
                operation_id=operation.id,
                kind="measurement",
                evidence_ids=tuple(item.id for item in evidence),
                recorded_at=recorded_at,
                actor="user",
                observation=shared["description"],
                verification_state="user_confirmed",
            )
            transaction = MaterialTransaction(
                id="material-" + uuid4().hex,
                kind=body.kind,
                recorded_at=recorded_at,
                physical_event_id=event.id,
                **transaction_fields,
                **quantity,
            )
            _append(
                connection,
                project_id,
                plan.version_id,
                evidence,
                [event],
                [transaction],
            )
            result = ProgressResult(progress=snapshot(connection, plan)).model_dump(
                mode="json"
            )
            store.remember(
                connection, owner, scope, body.idempotency_key, digest, result
            )
            return result

    return router
