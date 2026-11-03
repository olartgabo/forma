"""Replay recorded physical history into an execution state.

Joint state comes from the confirmed operations' own attach/detach effects in
the order they were reported, never from which operation IDs are complete. An
approved revision is a boundary: its carried work must already be confirmed,
unchanged and recorded against the exact history the revision was approved on.
"""

import hashlib
import json
from dataclasses import dataclass, field

from forma_domain.fabrication_contracts import VersionHistory
from forma_domain.models import Blocker


@dataclass
class ExecutionState:
    completed: dict[str, str] = field(default_factory=dict)
    attached: set[str] = field(default_factory=set)
    damaged: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)

    def copy(self) -> "ExecutionState":
        return ExecutionState(
            dict(self.completed),
            set(self.attached),
            set(self.damaged),
            set(self.failed),
        )


def state_id(plan_sha256: str, state: ExecutionState) -> str:
    canonical = json.dumps(
        {
            "plan": plan_sha256,
            "completed": sorted(state.completed.items()),
            "attached": sorted(state.attached),
            "damaged": sorted(state.damaged),
            "failed": sorted(state.failed),
        },
        separators=(",", ":"),
    )
    return "state-" + hashlib.sha256(canonical.encode()).hexdigest()[:40]


def joint_effect_error(state: ExecutionState, operation) -> str | None:
    for joint_id in operation.effects.attached_joint_ids:
        if joint_id in state.attached:
            return f"{joint_id} is already attached."
    for joint_id in operation.effects.detached_joint_ids:
        if joint_id not in state.attached:
            return f"{joint_id} is not attached, so it cannot be detached."
    return None


def apply_operation(state: ExecutionState, operation, version_id: str) -> None:
    state.attached.update(operation.effects.attached_joint_ids)
    state.attached.difference_update(operation.effects.detached_joint_ids)
    state.completed[operation.id] = version_id


def replay(
    lineage: tuple[VersionHistory, ...],
) -> tuple[ExecutionState, tuple[Blocker, ...]]:
    conflicts: list[Blocker] = []
    state = ExecutionState()
    definitions = {}
    previous: VersionHistory | None = None
    last_recorded_at = None
    seen_events = set()

    def conflict(code: str, message: str, *ids: str) -> None:
        conflicts.append(Blocker(code=code, message=message, target_ids=ids))

    for history in lineage:
        plan = history.plan
        operations = {op.id: op for op in plan.operations}
        if previous is None:
            if (
                plan.parent_version_id is not None
                or history.carried_operation_ids
                or history.base_last_event_id is not None
            ):
                conflict(
                    "stale_version",
                    "The plan history does not start at its original version.",
                    plan.version_id,
                )
        else:
            if plan.parent_version_id != previous.plan.version_id:
                conflict(
                    "stale_version",
                    "This version does not continue the previous plan version.",
                    plan.version_id,
                )
            approved_on = previous.events[-1].id if previous.events else None
            if history.base_last_event_id != approved_on:
                conflict(
                    "stale_version",
                    "The revision was approved against a different physical history.",
                    plan.version_id,
                )
            for op_id in history.carried_operation_ids:
                if op_id not in operations:
                    conflict(
                        "invalid_reference",
                        "Carried work is missing from the revised plan.",
                        op_id,
                    )
                elif op_id not in state.completed:
                    conflict(
                        "irreversible_conflict",
                        "The revision carries work that was never confirmed.",
                        op_id,
                    )
                elif operations[op_id] != definitions[op_id]:
                    conflict(
                        "irreversible_conflict",
                        "Completed work cannot change after it was recorded.",
                        op_id,
                    )
            carried = set(history.carried_operation_ids)
            state.completed = {
                op_id: version_id
                for op_id, version_id in state.completed.items()
                if op_id in carried
            }
            # An approved revision resolves the failed checks it was based on.
            # Damaged parts stay damaged; the revision does not repair them.
            state.failed = set()

        evidence = {item.id: item for item in history.evidence}
        if len(evidence) != len(history.evidence):
            conflict(
                "invalid_reference", "Evidence IDs must be distinct.", plan.version_id
            )
        for item in history.evidence:
            if (
                item.project_id != plan.project_id
                or item.version_id != plan.version_id
                or not (
                    set(item.part_ids) <= {p.id for p in plan.parts}
                    and set(item.operation_ids) <= operations.keys()
                    and set(item.checkpoint_ids) <= {c.id for c in plan.checkpoints}
                )
            ):
                conflict(
                    "invalid_reference",
                    "Historical evidence references foreign objects.",
                    item.id,
                )
        for event in history.events:
            if event.id in seen_events:
                conflict(
                    "invalid_order", "Physical event IDs must be distinct.", event.id
                )
                continue
            seen_events.add(event.id)
            if (
                event.project_id != plan.project_id
                or event.version_id != plan.version_id
            ):
                conflict(
                    "stale_version",
                    "A report belongs to another project or plan version.",
                    event.id,
                )
                continue
            if last_recorded_at is not None and event.recorded_at < last_recorded_at:
                conflict(
                    "invalid_order",
                    "Physical reports are out of chronological order.",
                    event.id,
                )
            last_recorded_at = event.recorded_at
            if event.operation_id is not None and event.operation_id not in operations:
                conflict(
                    "invalid_reference",
                    "Physical report references an unknown operation.",
                    event.id,
                )
                continue
            linked = [evidence.get(eid) for eid in event.evidence_ids]
            if any(
                item is None
                or item.project_id != plan.project_id
                or item.version_id != plan.version_id
                or item.recorded_at > event.recorded_at
                or (
                    event.operation_id is not None
                    and event.operation_id not in item.operation_ids
                )
                for item in linked
            ):
                conflict(
                    "invalid_reference",
                    "Linked evidence must match the report scope and step.",
                    event.id,
                )
                continue
            if event.kind in {"operation_confirmed", "damage"} and (
                event.actor != "user"
                or event.verification_state != "user_confirmed"
                or (event.kind == "damage" and not linked)
                or any(
                    item.provenance != "user"
                    or item.verification_state != "user_confirmed"
                    for item in linked
                )
            ):
                conflict(
                    "needs_confirmation",
                    "Physical work requires explicit user confirmation and scoped evidence.",
                    event.id,
                )
                continue
            if event.kind == "damage":
                parts = {
                    part_id
                    for evidence_id in event.evidence_ids
                    if evidence_id in evidence
                    for part_id in evidence[evidence_id].part_ids
                }
                if event.operation_id is None or not parts:
                    conflict(
                        "invalid_reference",
                        "Reported damage must name its step and damaged parts.",
                        event.id,
                    )
                    continue
                state.damaged.update(parts)
                state.failed.add(event.operation_id)
                continue
            if event.verification_state == "failed" and event.operation_id:
                state.failed.add(event.operation_id)
            if event.kind != "operation_confirmed":
                continue
            operation = operations.get(event.operation_id)
            if operation is None:
                conflict(
                    "invalid_reference",
                    "A confirmed step is not part of its plan version.",
                    event.id,
                )
                continue
            if operation.id in state.completed:
                conflict("invalid_order", "A step was confirmed twice.", operation.id)
                continue
            if not set(operation.depends_on) <= state.completed.keys():
                conflict(
                    "invalid_order",
                    "A step was confirmed before the steps it depends on.",
                    operation.id,
                )
            if state.failed:
                conflict(
                    "invalid_order",
                    "A step was confirmed while a failed check was unresolved.",
                    operation.id,
                )
            error = joint_effect_error(state, operation)
            if error is not None:
                conflict("irreversible_conflict", error, operation.id)
                continue
            apply_operation(state, operation, plan.version_id)
            definitions[operation.id] = operation
        previous = history
    return state, tuple(conflicts)
