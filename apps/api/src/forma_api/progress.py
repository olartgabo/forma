"""Append-only user reports; expected stock is separate from physical measurement."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import Field, StringConstraints, model_validator

from forma_api.plans import PlanService
from forma_api.projects import Key, ProjectError, ProjectStore
from forma_domain.models import (
    ID,
    BuildPlan,
    Evidence,
    MaterialTransaction,
    Measurement,
    PhysicalEvent,
    Record,
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


class ProgressSnapshot(Record):
    project_id: ID
    version_id: ID
    last_event_id: ID | None
    events: tuple[PhysicalEvent, ...]
    evidence: tuple[Evidence, ...]
    material_transactions: tuple[MaterialTransaction, ...]
    completed_operation_ids: tuple[ID, ...]
    failed_operation_ids: tuple[ID, ...]
    expected_remaining_stock: tuple[Stock, ...]
    status: Literal["not_started", "building", "needs_review", "passed"]


class ProgressResult(Record):
    progress: ProgressSnapshot
    replayed: bool = False


def expected_stock(plan: BuildPlan, completed: set[str]) -> tuple[Stock, ...]:
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
    completed = {
        event.operation_id for event in events if event.kind == "operation_confirmed"
    }
    failed = {
        event.operation_id for event in events if event.verification_state == "failed"
    }
    status = "not_started"
    if failed:
        status = "needs_review"
    elif events:
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
        failed_operation_ids=tuple(op.id for op in plan.operations if op.id in failed),
        expected_remaining_stock=expected_stock(plan, completed),
        status=status,
    )


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
            for photo_id in body.photo_ids:
                if (
                    connection.execute(
                        "SELECT 1 FROM media WHERE project_id=? AND id=?",
                        (project_id, photo_id),
                    ).fetchone()
                    is None
                ):
                    raise ProjectError(
                        422, "validation_error", "Photo is outside this project"
                    )

            recorded_at = datetime.now(UTC)
            if current.events and recorded_at <= current.events[-1].recorded_at:
                recorded_at = current.events[-1].recorded_at + timedelta(microseconds=1)
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
            for item in evidence:
                connection.execute(
                    "INSERT INTO progress_evidence VALUES (?, ?, ?, ?, ?)",
                    (
                        item.id,
                        project_id,
                        plan.version_id,
                        item.asset_id,
                        item.model_dump_json(),
                    ),
                )
            for item in events:
                connection.execute(
                    "INSERT INTO progress_events VALUES (?, ?, ?, ?)",
                    (item.id, project_id, plan.version_id, item.model_dump_json()),
                )
            for item in transactions:
                connection.execute(
                    "INSERT INTO progress_material VALUES (?, ?, ?, ?)",
                    (item.id, project_id, plan.version_id, item.model_dump_json()),
                )
            result = ProgressResult(progress=snapshot(connection, plan)).model_dump(
                mode="json"
            )
            store.remember(
                connection, owner, scope, body.idempotency_key, digest, result
            )
            return result

    return router
