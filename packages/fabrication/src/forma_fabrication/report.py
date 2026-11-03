"""Pure fabrication report: what can be attempted next, and why not the rest."""

import hashlib
import heapq
import json
from dataclasses import dataclass

from forma_compiler import CutProcess, validate_plan

from forma_domain.fabrication_contracts import (
    FABRICATION_RULES_VERSION,
    FabricationInput,
    FabricationReport,
    FabricationSnapshot,
    OperationReadiness,
    OrderStep,
)
from forma_domain.models import Blocker, BuildPlan, Stock

from .replay import (
    ExecutionState,
    apply_operation,
    joint_effect_error,
    replay,
    state_id,
)
from .rules import (
    FAMILY_OPERATION_TYPES,
    JOIN_TYPES,
    PREPARATION_TYPES,
    tool_checks,
    tool_confirmations,
)

EPS = 1e-7


def _sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass
class Ledger:
    """Remaining material as the existing progress ledger reports it."""

    stocks: dict[str, Stock]
    regions: dict[str, set[str]]
    lengths: dict[str, float | None]

    @classmethod
    def from_stock(cls, stocks: tuple[Stock, ...]) -> "Ledger":
        return cls(
            {s.id: s for s in stocks},
            {s.id: {r.id for r in s.usable_regions} for s in stocks},
            {s.id: s.remaining_length_mm.value for s in stocks},
        )

    def copy(self) -> "Ledger":
        return Ledger(
            self.stocks,
            {k: set(v) for k, v in self.regions.items()},
            dict(self.lengths),
        )

    def spend(self, operation) -> None:
        if operation.type == "cut_rect":
            regions = self.regions[operation.args.stock_id]
            regions.discard(operation.args.source_region_id)
            regions.update(r.id for r in operation.effects.created_offcuts)
        elif operation.type in ("tape_joint", "tie_joint"):
            sid = operation.args.stock_id
            if self.lengths[sid] is not None:
                self.lengths[sid] -= operation.args.length_mm


@dataclass
class Check:
    blockers: list[Blocker]
    waiting_on: list[str]


class _Scheduler:
    def __init__(self, plan: BuildPlan):
        self.plan = plan
        self.operations = {op.id: op for op in plan.operations}
        self.index = {op.id: i for i, op in enumerate(plan.operations)}
        self.joints = {j.id: j for j in plan.joints}
        self.supported = FAMILY_OPERATION_TYPES.get(plan.family, frozenset())

    def producers(self, joint_id: str, pending: set[str]) -> list[str]:
        return [
            op_id
            for op_id in pending
            if joint_id in self.operations[op_id].effects.attached_joint_ids
        ]

    def held_by(self, part_id: str, state: ExecutionState) -> list[str]:
        return sorted(j for j in state.attached if part_id in self.joints[j].part_ids)

    def pending_preparation(self, part_ids, pending: set[str]) -> list[str]:
        return sorted(
            (
                op_id
                for op_id in pending
                if self.operations[op_id].type in PREPARATION_TYPES
                and self.operations[op_id].args.part_id in part_ids
            ),
            key=self.index.get,
        )

    def parts_used(self, operation) -> set[str]:
        args = operation.args
        parts = set(operation.part_ids) | set(
            operation.preconditions.accessible_part_ids
        )
        parts.update(
            getattr(args, name)
            for name in ("part_id", "brace_part_id", "target_id")
            if hasattr(args, name)
        )
        parts.update(getattr(args, "target_ids", ()))
        if hasattr(args, "joint_id"):
            parts.update(self.joints[args.joint_id].part_ids)
        return parts

    def structural(
        self, operation, state: ExecutionState, ledger: Ledger, pending: set[str]
    ) -> Check:
        """Dependencies, joints, access and material; tools are separate."""
        check = Check([], [])

        def block(code: str, message: str, *ids: str) -> None:
            check.blockers.append(Blocker(code=code, message=message, target_ids=ids))

        op_id, args = operation.id, operation.args
        if operation.type not in self.supported:
            block(
                "unsupported",
                f"FORMA cannot record a {operation.type} step for this family yet.",
                op_id,
            )
        for dep in operation.depends_on:
            if dep not in state.completed:
                check.waiting_on.append(dep)
        for joint_id in operation.preconditions.required_joint_ids:
            if joint_id in state.attached:
                continue
            producers = self.producers(joint_id, pending - {op_id})
            if producers:
                check.waiting_on.extend(producers)
            else:
                block(
                    "invalid_order",
                    f"{joint_id} must be attached first, and no remaining step attaches it.",
                    op_id,
                    joint_id,
                )
        # Detaching a damaged part is how a repair frees it, so only other
        # steps stop at damage.
        if operation.type != "detach":
            for part_id in sorted(self.parts_used(operation) & state.damaged):
                block(
                    "needs_confirmation",
                    f"{part_id} was reported damaged. Review a repair before using it.",
                    op_id,
                    part_id,
                )
        if operation.type in JOIN_TYPES:
            joint = self.joints[args.joint_id]
            if joint.confirmed_accessible is not True:
                block(
                    "needs_confirmation",
                    f"Access to {joint.id} is unknown. Confirm it can be reached before joining.",
                    op_id,
                    joint.id,
                )
            for prep in self.pending_preparation(joint.part_ids, pending - {op_id}):
                block(
                    "invalid_order",
                    f"Do {prep} first. Joining now would cover "
                    f"{self.operations[prep].args.part_id} before it is shaped.",
                    op_id,
                    prep,
                )
        if operation.type == "detach" and args.joint_id not in state.attached:
            producers = self.producers(args.joint_id, pending - {op_id})
            if producers:
                check.waiting_on.extend(producers)
            else:
                block(
                    "invalid_order",
                    f"{args.joint_id} is not attached, so there is nothing to detach.",
                    op_id,
                    args.joint_id,
                )
        elif not check.waiting_on:
            error = joint_effect_error(state, operation)
            if error is not None:
                block("invalid_order", error, op_id)
        if operation.type in PREPARATION_TYPES:
            for joint_id in self.held_by(args.part_id, state):
                block(
                    "invalid_order",
                    f"{args.part_id} is already held by {joint_id}. Reaching it for "
                    f"this step needs an explicit detach first.",
                    op_id,
                    joint_id,
                )
        if operation.type == "cut_rect":
            stock = ledger.stocks.get(args.stock_id)
            if (
                stock is None
                or stock.condition != "usable"
                or args.source_region_id not in ledger.regions[args.stock_id]
            ):
                block(
                    "stock_exhausted",
                    f"Region {args.source_region_id} is no longer usable stock.",
                    op_id,
                    args.source_region_id,
                )
        if operation.type in ("tape_joint", "tie_joint"):
            stock = ledger.stocks.get(args.stock_id)
            length = ledger.lengths.get(args.stock_id)
            if stock is None or stock.condition != "usable":
                block(
                    "stock_exhausted",
                    f"{args.stock_id} is not usable connector stock.",
                    op_id,
                    args.stock_id,
                )
            elif length is None:
                block(
                    "missing_measurement",
                    f"Measure how much {args.stock_id} is left before this join.",
                    op_id,
                    args.stock_id,
                )
            elif length + EPS < args.length_mm:
                block(
                    "stock_exhausted",
                    f"{args.stock_id} has {length:g} mm left; this join needs "
                    f"{args.length_mm:g} mm.",
                    op_id,
                    args.stock_id,
                )
        check.waiting_on = sorted(set(check.waiting_on), key=self.index.get)
        return check

    def confirmations(self, operation, ledger: Ledger) -> tuple[str, ...]:
        found = list(operation.preconditions.human_checks)
        if operation.reversible == "irreversible":
            found.append(
                "This step cannot be undone. Confirm every measurement it uses before you start."
            )
        if operation.type in ("cut_rect", "cut_slot"):
            found.append("Confirm you can handle your cutting tool safely.")
        if operation.type in ("tape_joint", "tie_joint"):
            stock = ledger.stocks.get(operation.args.stock_id)
            if stock is not None and not stock.remaining_length_mm.confirmed:
                found.append(
                    f"{stock.id} is calculated, not measured. Check at least "
                    f"{operation.args.length_mm:g} mm is left."
                )
        return tuple(found)

    def edges(self, pending: set[str]) -> dict[str, set[str]]:
        """Prerequisites among pending steps, including access ordering."""
        before = {op_id: set() for op_id in pending}
        for op_id in pending:
            operation = self.operations[op_id]
            before[op_id].update(d for d in operation.depends_on if d in pending)
            for joint_id in operation.preconditions.required_joint_ids:
                before[op_id].update(self.producers(joint_id, pending - {op_id}))
            if operation.type == "detach":
                before[op_id].update(
                    self.producers(operation.args.joint_id, pending - {op_id})
                )
            if operation.type in JOIN_TYPES:
                parts = self.joints[operation.args.joint_id].part_ids
                before[op_id].update(self.pending_preparation(parts, pending - {op_id}))
        return before

    def order(
        self,
        state: ExecutionState,
        ledger: Ledger,
        plan_sha256: str,
    ) -> tuple[tuple[OrderStep, ...], str, tuple[Blocker, ...]]:
        pending = {op.id for op in self.plan.operations if op.id not in state.completed}
        before = self.edges(pending)
        remaining = {op_id: len(deps) for op_id, deps in before.items()}
        after: dict[str, list[str]] = {op_id: [] for op_id in pending}
        for op_id, deps in before.items():
            for dep in deps:
                after[dep].append(op_id)
        queue = [(self.index[o], o) for o, count in remaining.items() if count == 0]
        heapq.heapify(queue)
        state, ledger = state.copy(), ledger.copy()
        steps: list[OrderStep] = []
        latest = -1
        while queue:
            _, op_id = heapq.heappop(queue)
            operation = self.operations[op_id]
            check = self.structural(operation, state, ledger, pending)
            if check.blockers or check.waiting_on:
                return (
                    tuple(steps),
                    "blocked",
                    tuple(check.blockers)
                    or (
                        Blocker(
                            code="invalid_order",
                            message=f"{op_id} cannot follow the supported order.",
                            target_ids=(op_id, *check.waiting_on),
                        ),
                    ),
                )
            pending.discard(op_id)
            apply_operation(state, operation, self.plan.version_id)
            ledger.spend(operation)
            steps.append(
                OrderStep(
                    operation_id=op_id,
                    state_id=state_id(plan_sha256, state),
                    reordered=self.index[op_id] < latest,
                )
            )
            latest = max(latest, self.index[op_id])
            for following in after[op_id]:
                remaining[following] -= 1
                if remaining[following] == 0:
                    heapq.heappush(queue, (self.index[following], following))
        if pending:
            # Kahn leaves the cycle plus everything after it; drop steps that
            # nothing left waits on until only steps in a cycle remain.
            stuck = set(pending)
            trimmed = True
            while trimmed:
                trimmed = False
                for op_id in list(stuck):
                    if not any(op_id in before[other] for other in stuck):
                        stuck.discard(op_id)
                        trimmed = True
            cycle = sorted(stuck, key=self.index.get)
            return (
                tuple(steps),
                "cycle",
                (
                    Blocker(
                        code="invalid_order",
                        message="These steps wait on each other: dependencies and "
                        "access rules allow no order that finishes them.",
                        target_ids=tuple(cycle),
                    ),
                ),
            )
        return tuple(steps), "complete", ()


def fabrication_report(
    data: FabricationInput, *, process: CutProcess, allow_synthetic: bool = False
) -> FabricationReport:
    # model_copy can bypass validators; rebuild so only valid lineage is replayed.
    data = FabricationInput.model_validate_json(data.model_dump_json())
    target = data.lineage[-1]
    plan = target.plan
    plan_sha256 = _sha256(plan.model_dump(mode="json"))
    snapshot = FabricationSnapshot(
        project_id=data.project_id,
        version_id=plan.version_id,
        inventory_revision_id=data.inventory_revision_id,
        last_event_id=target.events[-1].id if target.events else None,
        plan_sha256=plan_sha256,
        history_sha256=_sha256(
            {
                "lineage": [
                    {
                        "version_id": h.plan.version_id,
                        "plan": _sha256(h.plan.model_dump(mode="json")),
                        "events": [e.model_dump(mode="json") for e in h.events],
                        "evidence": [e.model_dump(mode="json") for e in h.evidence],
                        "carried": list(h.carried_operation_ids),
                        "base_last_event_id": h.base_last_event_id,
                    }
                    for h in data.lineage
                ],
                "remaining_stock": [
                    s.model_dump(mode="json") for s in data.remaining_stock
                ],
                "declared_tools": data.declared_tools,
                "context_blockers": [
                    b.model_dump(mode="json") for b in data.context_blockers
                ],
            }
        ),
        process_sha256=_sha256(process.model_dump(mode="json")),
        rules_version=FABRICATION_RULES_VERSION,
        compiler_version=plan.compiler_version,
    )
    state, conflicts = replay(data.lineage)
    blockers = list(conflicts)
    blockers.extend(data.context_blockers)
    if plan.family not in FAMILY_OPERATION_TYPES:
        blockers.append(
            Blocker(
                code="unsupported",
                message="No fabrication rules are declared for this design family.",
            )
        )
    compiled = validate_plan(plan, process=process, allow_synthetic=allow_synthetic)
    blockers.extend(compiled.blockers)
    if state.failed:
        blockers.append(
            Blocker(
                code="needs_confirmation",
                message="Review the failed check or reported damage before continuing.",
                target_ids=tuple(sorted(state.failed)),
            )
        )
    scheduler = _Scheduler(plan)
    ledger = Ledger.from_stock(data.remaining_stock)
    pending = {op.id for op in plan.operations if op.id not in state.completed}
    current = state_id(plan_sha256, state)

    if conflicts or compiled.status != "accepted":
        steps, order_status, order_blockers = (
            (),
            "blocked",
            (
                Blocker(
                    code="invalid_order",
                    message="No order is supported until the report-wide blockers are resolved.",
                ),
            ),
        )
    else:
        steps, order_status, order_blockers = scheduler.order(
            state, ledger, plan_sha256
        )

    operations = []
    for operation in plan.operations:
        if operation.id in state.completed:
            operations.append(
                OperationReadiness(
                    operation_id=operation.id,
                    operation_type=operation.type,
                    status="completed",
                    completed_in_version_id=state.completed[operation.id],
                    waiting_on_operation_ids=(),
                    blockers=(),
                    tools=(),
                    required_confirmations=(),
                    next_state_id=None,
                )
            )
            continue
        check = scheduler.structural(operation, state, ledger, pending)
        tools = tool_checks(operation, data.declared_tools)
        own = list(check.blockers)
        status = "blocked" if own else "waiting" if check.waiting_on else None
        if status is None:
            if blockers:
                own.append(
                    Blocker(
                        code="needs_confirmation",
                        message="Resolve the blockers for the whole build first.",
                        target_ids=(operation.id,),
                    )
                )
            status = "blocked" if own else "ready"
        next_state = None
        if status == "ready":
            after = state.copy()
            apply_operation(after, operation, plan.version_id)
            next_state = state_id(plan_sha256, after)
        operations.append(
            OperationReadiness(
                operation_id=operation.id,
                operation_type=operation.type,
                status=status,
                completed_in_version_id=None,
                waiting_on_operation_ids=tuple(check.waiting_on),
                blockers=tuple(own),
                tools=tools,
                required_confirmations=scheduler.confirmations(operation, ledger)
                + tool_confirmations(tools),
                next_state_id=next_state,
            )
        )
    ready = {o.operation_id for o in operations if o.status == "ready"}
    next_operation = next(
        (s.operation_id for s in steps if s.operation_id in ready), None
    )
    if conflicts:
        status = "history_conflict"
    elif not pending:
        status = "complete"
    else:
        status = "ready" if ready else "blocked"
    return FabricationReport(
        snapshot=snapshot,
        status=status,
        current_state_id=current,
        attached_joint_ids=tuple(sorted(state.attached)),
        damaged_part_ids=tuple(sorted(state.damaged)),
        failed_operation_ids=tuple(sorted(state.failed)),
        next_operation_id=next_operation,
        operations=tuple(operations),
        supported_order=steps,
        order_status=order_status,
        order_blockers=order_blockers,
        blockers=tuple(blockers),
        access_basis="declared_rules",
        observed_usability="not_assessed",
    )
