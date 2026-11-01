"""Observed connector context for deterministic manual rendering.

A trusted server caller supplies reconciled physical facts: the connectors
remaining after historical work and the historical operations already
completed. This helper only validates that context against the target plan.
It does not replay history, authenticate the caller, rewrite the original
plan stock, or treat completed work as a new operation or a physical test
pass. Historical connector use is therefore never charged again as future
use, and an already spent connector cannot be charged again.
"""

from dataclasses import dataclass

from pydantic import Field

from forma_domain import models as m

_CONNECTOR_KINDS = ("tape", "cord")
_CONNECTOR_OPERATION_TYPES = ("tape_joint", "tie_joint")


class ConnectorContext(m.Record):
    """Reconciled connector facts supplied by a trusted server caller."""

    project_id: m.ID
    plan_version_id: m.ID
    observed_version_id: m.ID
    remaining_connectors: tuple[m.Stock, ...] = Field(max_length=32)
    completed_operation_ids: tuple[m.ID, ...] = Field(max_length=128)


@dataclass(frozen=True)
class _ConnectorState:
    current: dict[str, float | None]
    future_use: dict[str, float]
    completed: frozenset[m.ID]


def _blocker(blockers, seen, code, message, target_ids=()):
    key = (code, tuple(target_ids))
    if key not in seen:
        seen.add(key)
        blockers.append(
            m.Blocker(code=code, message=message, target_ids=tuple(target_ids))
        )


def validated_connectors(
    plan: m.BuildPlan, context: ConnectorContext
) -> tuple[_ConnectorState | None, tuple[m.Blocker, ...]]:
    """Validate observed connector context against ``plan``.

    Returns ``(state, ())`` on success and ``(None, blockers)`` otherwise.
    Nothing in the plan or context is mutated.
    """
    blockers: list[m.Blocker] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    def add(code, message, target_ids=()):
        _blocker(blockers, seen, code, message, target_ids)

    # model_copy can bypass validators, so rebuild strictly from JSON.
    try:
        rebuilt = ConnectorContext.model_validate_json(
            context.model_dump_json(warnings=False), strict=True
        )
    except (AttributeError, TypeError, ValueError):
        return None, (
            m.Blocker(
                code="invalid_reference",
                message="Connector context failed validation.",
                target_ids=(),
            ),
        )
    context = rebuilt

    # --- Scope: project and target plan version must be exact, and the
    # observation must be of this plan version or its parent version. ---
    if context.project_id != plan.project_id:
        add(
            "invalid_reference",
            "Connector context project does not match the plan project.",
            (context.project_id,),
        )
    if context.plan_version_id != plan.version_id:
        add(
            "invalid_reference",
            "Connector context plan version does not match the plan version.",
            (context.plan_version_id,),
        )
    observed_versions = {plan.version_id}
    if plan.parent_version_id is not None:
        observed_versions.add(plan.parent_version_id)
    if context.observed_version_id not in observed_versions:
        add(
            "invalid_reference",
            "Connector context observed version is neither the plan version "
            "nor its parent version.",
            (context.observed_version_id,),
        )
    if blockers:
        return None, tuple(blockers)

    operations_by_id = {operation.id: operation for operation in plan.operations}

    # --- Completed operations: unique, known and dependency-closed. These
    # are actual historical operations, including lost work still defined in
    # the plan; they are not new work, redo work or physical test passes. ---
    completed_ids = context.completed_operation_ids
    completed_set = set(completed_ids)
    if len(completed_set) != len(completed_ids):
        duplicates = tuple(
            dict.fromkeys(
                operation_id
                for operation_id in completed_ids
                if completed_ids.count(operation_id) > 1
            )
        )
        for operation_id in duplicates:
            add(
                "invalid_reference",
                "Completed operation IDs must be unique.",
                (operation_id,),
            )
    for operation_id in completed_ids:
        if operation_id not in operations_by_id:
            add(
                "invalid_reference",
                "Completed operation is not defined in the plan.",
                (operation_id,),
            )
    for operation_id in completed_ids:
        operation = operations_by_id.get(operation_id)
        if operation is None:
            continue
        for dependency_id in operation.depends_on:
            if dependency_id not in completed_set:
                add(
                    "invalid_order",
                    "Completed operation depends on an operation that is not "
                    "completed.",
                    (operation_id, dependency_id),
                )
    if blockers:
        return None, tuple(blockers)

    # --- Connector identity: exactly the plan tape/cord stocks. ---
    baseline_connectors = tuple(
        stock for stock in plan.stocks if stock.kind in _CONNECTOR_KINDS
    )
    baseline_by_id = {stock.id: stock for stock in baseline_connectors}
    remaining_by_id: dict[str, m.Stock] = {}
    for stock in context.remaining_connectors:
        if stock.id in remaining_by_id:
            add(
                "invalid_reference",
                "Remaining connector IDs must be unique.",
                (stock.id,),
            )
        else:
            remaining_by_id[stock.id] = stock
    for stock in baseline_connectors:
        if stock.id not in remaining_by_id:
            add(
                "invalid_reference",
                "Remaining connectors are missing a plan connector.",
                (stock.id,),
            )
    for stock in context.remaining_connectors:
        if stock.id not in baseline_by_id:
            add(
                "invalid_reference",
                "Remaining connectors include a stock that is not a plan "
                "tape or cord connector.",
                (stock.id,),
            )

    # Source identity must match the baseline; only the remaining length
    # and condition are observed facts that may differ.
    for stock in baseline_connectors:
        remaining = remaining_by_id.get(stock.id)
        if remaining is None:
            continue
        if (
            remaining.kind != stock.kind
            or remaining.material != stock.material
            or remaining.width_mm != stock.width_mm
            or remaining.height_mm != stock.height_mm
            or remaining.thickness_mm != stock.thickness_mm
            or remaining.allowed_rotations_deg != stock.allowed_rotations_deg
            or remaining.usable_regions != stock.usable_regions
        ):
            add(
                "invalid_reference",
                "Remaining connector source does not match the plan "
                "connector baseline.",
                (stock.id,),
            )
    if blockers:
        return None, tuple(blockers)

    # --- Connector use: completed use is already spent and is excluded
    # from future use; future use is summed over tape/tie operations that
    # are not completed. ---
    completed_use = {stock.id: 0.0 for stock in baseline_connectors}
    future_use = {stock.id: 0.0 for stock in baseline_connectors}
    for operation in plan.operations:
        if operation.type not in _CONNECTOR_OPERATION_TYPES:
            continue
        stock_id = operation.args.stock_id
        if stock_id not in future_use:
            continue
        if operation.id in completed_set:
            completed_use[stock_id] += operation.args.length_mm
        else:
            future_use[stock_id] += operation.args.length_mm

    # --- Remaining length against baseline, completed use and future use.
    # Strict caps only; lengths are never clamped or rewritten. ---
    for stock in baseline_connectors:
        remaining = remaining_by_id[stock.id]
        measurement = remaining.remaining_length_mm
        current_value = measurement.value if measurement.confirmed else None
        future = future_use[stock.id]
        used = future > 0

        if used and remaining.condition != "usable":
            add(
                "needs_confirmation",
                "Connector used by a future operation must be confirmed usable.",
                (stock.id,),
            )

        baseline = stock.remaining_length_mm
        baseline_confirmed = baseline.value is not None and baseline.confirmed
        if used and (
            current_value is None or not measurement.confirmed or not baseline_confirmed
        ):
            add(
                "missing_measurement",
                "Connector used by a future operation requires a known, "
                "confirmed current length and a known, confirmed baseline "
                "length.",
                (stock.id,),
            )

        if current_value is not None and current_value < 0:
            add(
                "stock_exhausted",
                "Remaining connector length cannot be negative.",
                (stock.id,),
            )
        if baseline_confirmed and current_value is not None:
            available_after_completed = baseline.value - completed_use[stock.id]
            if current_value > available_after_completed:
                add(
                    "stock_exhausted",
                    "Remaining connector length exceeds the confirmed "
                    "baseline minus completed connector use; connectors "
                    "cannot be replenished.",
                    (stock.id,),
                )
        if used and current_value is not None and future > current_value:
            add(
                "stock_exhausted",
                "Future connector use exceeds the remaining connector length.",
                (stock.id,),
            )
    if blockers:
        return None, tuple(blockers)

    state = _ConnectorState(
        current={
            stock.id: (
                remaining_by_id[stock.id].remaining_length_mm.value
                if remaining_by_id[stock.id].remaining_length_mm.confirmed
                else None
            )
            for stock in baseline_connectors
        },
        future_use=future_use,
        completed=frozenset(completed_set),
    )
    return state, ()


__all__ = ["ConnectorContext", "validated_connectors"]
