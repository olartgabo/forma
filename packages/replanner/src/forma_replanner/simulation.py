"""Conservative repair simulation over immutable execution snapshots."""

from hashlib import sha256
from math import cos, hypot, radians, sin
from typing import Callable, Literal

from forma_compiler import CutProcess, validate_plan
from pydantic import ValidationError, model_validator

from forma_domain.models import Blocker, BuildPlan, Record, ReplannerInput


class RepairCost(Record):
    """Known heuristic terms, never a fabricated complete cost estimate."""

    irreversible_completed_actions_lost: int
    required_physical_undos: int
    new_irreversible_actions: int
    known_weighted_cost: int
    estimated_extra_minutes: float | None = None
    material_waste_fraction: float | None = None
    estimated_new_purchase_cost: float | None = None
    complete_estimate: Literal[False] = False


class MaterialDelta(Record):
    """Proposed use/loss, never a claim that material was physically consumed."""

    stock_id: str
    source_region_id: str | None
    operation_id: str | None
    kind: Literal["consume", "waste", "retire_part"]
    quantity: float
    unit: Literal["mm", "mm2"]


class SimulationResult(Record):
    patch_id: str
    base_version_id: str
    status: Literal["feasible", "blocked"]
    plan: BuildPlan | None = None
    preserved_operation_ids: tuple[str, ...] = ()
    required_undo_operation_ids: tuple[str, ...] = ()
    redo_operation_ids: tuple[str, ...] = ()
    newly_required_operation_ids: tuple[str, ...] = ()
    incomplete_operation_ids: tuple[str, ...] = ()
    changed_part_ids: tuple[str, ...] = ()
    invalidated_checkpoint_ids: tuple[str, ...] = ()
    invalidated_evidence_ids: tuple[str, ...] = ()
    lost_region_ids: tuple[str, ...] = ()
    lost_part_ids: tuple[str, ...] = ()
    lost_operation_ids: tuple[str, ...] = ()
    additional_material_stock_ids: tuple[str, ...] = ()
    required_new_stock_ids: tuple[str, ...] = ()
    proposed_material_deltas: tuple[MaterialDelta, ...] = ()
    cost: RepairCost | None = None
    unknown_physical_checks: tuple[str, ...] = ()
    blockers: tuple[Blocker, ...] = ()

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "feasible":
            if self.plan is None or self.cost is None or self.blockers:
                raise ValueError(
                    "feasible simulation requires a validated plan and cost without blockers"
                )
        elif self.plan is not None or self.cost is not None or not self.blockers:
            raise ValueError(
                "blocked simulation requires blockers without an executable plan or score"
            )
        return self


def _area(rect):
    return rect.width * rect.height


def _close(a, b):
    return abs(a - b) <= 1e-7


def _touched_stock_ids(snapshot):
    """Stocks the base work, ledger or requested patch actually relies on."""
    base, patch = snapshot.base_plan, snapshot.patch
    touched = {p.source_stock_id for p in base.parts}
    for op in base.operations:
        touched.update(op.stock_ids)
        stock_id = getattr(op.args, "stock_id", None)
        if stock_id is not None:
            touched.add(stock_id)
    touched.update(tx.source_stock_id for tx in snapshot.material_transactions)
    if patch.replacement_stock_id is not None:
        touched.add(patch.replacement_stock_id)
    return touched


def _affected(base, candidate):
    """Include relevant interfaces and all prerequisites, not operation IDs alone."""
    old_parts = {p.id: p for p in base.parts}
    new_parts = {p.id: p for p in candidate.parts}
    changed_parts = {
        p
        for p in old_parts.keys() | new_parts.keys()
        if old_parts.get(p) != new_parts.get(p)
    }
    old_stocks = {s.id: s for s in base.stocks}
    new_stocks = {s.id: s for s in candidate.stocks}
    changed_parts.update(
        p.id
        for p in base.parts
        if old_stocks.get(p.source_stock_id) != new_stocks.get(p.source_stock_id)
    )
    new_joints = {j.id: j for j in candidate.joints}
    changed_joints = {
        j.id
        for j in base.joints
        if j != new_joints.get(j.id) or set(j.part_ids) & changed_parts
    }
    old_profiles = {p.id: p for p in base.joint_profiles}
    new_profiles = {p.id: p for p in candidate.joint_profiles}
    changed_joints.update(
        j.id
        for j in candidate.joints
        if old_profiles.get(j.profile_id) != new_profiles.get(j.profile_id)
    )
    old_ops = {o.id: o for o in base.operations}
    affected = set()
    for op in candidate.operations:
        args = op.args
        referenced_parts = set(op.part_ids) | set(op.effects.created_part_ids)
        referenced_parts.update(op.preconditions.accessible_part_ids)
        for key in ("part_id", "brace_part_id"):
            if hasattr(args, key):
                referenced_parts.add(getattr(args, key))
        referenced_parts.update(getattr(args, "child_part_ids", ()))
        referenced_joints = set(op.preconditions.required_joint_ids)
        referenced_joints.update(op.effects.attached_joint_ids)
        referenced_joints.update(op.effects.detached_joint_ids)
        if hasattr(args, "joint_id"):
            referenced_joints.add(args.joint_id)
        referenced_joints.update(getattr(args, "underlying_joint_ids", ()))
        targets = set(getattr(args, "target_ids", ()))
        if hasattr(args, "target_id"):
            targets.add(args.target_id)
        if (
            op != old_ops.get(op.id)
            or referenced_parts & changed_parts
            or referenced_joints & changed_joints
            or targets & (changed_parts | changed_joints)
            or set(op.depends_on) & affected
        ):
            affected.add(op.id)
    return affected, changed_parts


_STAND_PART_IDS = ("stand-support", "stand-base", "stand-brace")
_STAND_CORE_TYPES = (
    "cut_rect",
    "inspect",
    "fold",
    "tape_joint",
    "tape_joint",
    "tape_joint",
    "inspect",
    "functional_test",
)


def _stand_base_resize(base, patch, completed, regions):
    """Return regenerated stand geometries, or a specific stand blocker.

    Only an unfinished, canonical triangular tape stand may extend its base
    depth. Unsupported stand variants return blockers; only non-stand plans
    fall through to the unchanged generic resize path.
    """
    if base.compiler_version != "triangular-tape-stand-v1":
        return False, None, None

    def unsupported(message, *ids):
        return True, Blocker(code="unsupported", message=message, target_ids=ids), None

    def invalid(message, *ids):
        return (
            True,
            Blocker(code="geometry_invalid", message=message, target_ids=ids),
            None,
        )

    if patch.target_id != "stand-base":
        return unsupported(
            "Stand resize only supports extending stand-base; other stand parts cannot be resized.",
            patch.target_id,
        )
    parts = {part.id: part for part in base.parts}
    if set(parts) != set(_STAND_PART_IDS) or len(base.parts) != len(_STAND_PART_IDS):
        return unsupported(
            "Stand base extension requires exactly the original stand-support, stand-base and stand-brace parts.",
            *_STAND_PART_IDS,
        )
    if tuple(operation.type for operation in base.operations) != _STAND_CORE_TYPES:
        return unsupported(
            "Stand base extension requires exactly the eight original stand operations with no supplemental cuts.",
            *(operation.id for operation in base.operations),
        )
    cuts = [operation for operation in base.operations if operation.type == "cut_rect"]
    if (
        len(cuts) != 1
        or cuts[0].id != "stand-cut-panels"
        or tuple(cuts[0].args.child_part_ids) != _STAND_PART_IDS
    ):
        return unsupported(
            "Stand base extension requires the original stand-cut-panels cut producing stand-support, stand-base and stand-brace.",
            *(operation.id for operation in cuts),
        )
    cut = cuts[0]
    if cut.effects.created_offcuts:
        return unsupported(
            "Stand base extension does not support plans with declared offcuts.",
            cut.id,
        )
    if cut.id in completed:
        return unsupported(
            "Stand base extension requires the original stand-cut-panels cut to be unfinished; completed cuts cannot be resized.",
            cut.id,
        )

    support_part = parts["stand-support"]
    base_part = parts["stand-base"]
    brace_part = parts["stand-brace"]
    ordered_parts = (support_part, base_part, brace_part)
    stock_id = support_part.source_stock_id
    region_id = support_part.source_region_id
    if any(
        part.source_stock_id != stock_id
        or part.source_region_id != region_id
        or part.geometry.rotation_deg != 0
        for part in ordered_parts
    ):
        return unsupported(
            "Stand base extension requires all original parts to share one unrotated original source region.",
            *_STAND_PART_IDS,
        )
    stock = next((item for item in base.stocks if item.id == stock_id), None)
    source_region = (
        next(
            (region for region in stock.usable_regions if region.id == region_id),
            None,
        )
        if stock is not None
        else None
    )
    if source_region is None or regions.get(region_id) != (
        stock_id,
        source_region.geometry,
    ):
        return unsupported(
            "Stand base extension requires the original source region to remain in reconciled remaining stock.",
            region_id,
        )
    if patch.width_mm != base_part.geometry.width:
        return unsupported(
            "Stand base extension requires the requested width to equal the current stand base width.",
            base_part.id,
        )
    if patch.height_mm <= base_part.geometry.height:
        return unsupported(
            "Stand base extension only supports increasing the stand base depth.",
            base_part.id,
        )
    footprint = base.constraints.max_footprint_height_mm
    if footprint.value is None or not footprint.confirmed:
        return (
            True,
            Blocker(
                code="missing_measurement",
                message="Stand base extension requires a confirmed max footprint height.",
                target_ids=(base_part.id,),
            ),
            None,
        )
    if patch.height_mm > footprint.value:
        return invalid(
            "Requested stand base depth exceeds the confirmed max footprint height.",
            base_part.id,
        )
    angle = base.constraints.support_angle_deg
    if angle.value is None or not angle.confirmed or not 0 < angle.value < 90:
        return invalid(
            "Stand base extension requires a confirmed support angle strictly between 0 and 90 degrees.",
            support_part.id,
        )
    if len(support_part.features) != 1 or support_part.features[0].kind != "fold":
        return unsupported(
            "Stand base extension requires the support to have exactly one fold feature.",
            support_part.id,
        )
    support_length = support_part.features[0].geometry.y
    if support_length <= 0 or support_length >= support_part.geometry.height:
        return invalid(
            "Stand support fold must leave positive support and lip heights.",
            support_part.id,
        )
    theta = radians(angle.value)
    reach = support_length * cos(theta)
    rise = support_length * sin(theta)
    if patch.height_mm <= reach:
        return invalid(
            "Requested stand base depth must exceed the horizontal reach of the support.",
            base_part.id,
            support_part.id,
        )
    heights = {
        "stand-support": support_part.geometry.height,
        "stand-base": patch.height_mm,
        "stand-brace": hypot(patch.height_mm - reach, rise),
    }
    source = source_region.geometry
    margin = cut.args.edge_margin_mm
    kerf = cut.args.kerf_mm
    x = source.x + margin
    y = source.y + margin
    geometries = {}
    for part_id in _STAND_PART_IDS:
        part = parts[part_id]
        geometries[part_id] = {
            "x": x,
            "y": y,
            "width": patch.width_mm if part_id == "stand-base" else part.geometry.width,
            "height": heights[part_id],
            "rotation_deg": 0,
        }
        y += heights[part_id] + kerf
    return True, None, geometries


def _safe_result_id(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _blocked_snapshot(
    patch_id: str, base_version_id: str, code: str, message: str
) -> SimulationResult:
    return SimulationResult(
        patch_id=patch_id,
        base_version_id=base_version_id,
        status="blocked",
        blockers=(Blocker(code=code, message=message),),
    )


def simulate_patch(
    snapshot: ReplannerInput,
    *,
    process: CutProcess | None = None,
    allow_synthetic: bool = False,
    historical_plans: tuple[BuildPlan, ...] = (),
    family_validator: Callable[[BuildPlan], tuple[Blocker, ...]] | None = None,
) -> SimulationResult:
    """Preview edits to unfinished work; unsupported physical rerouting blocks.

    The supplied process and joint catalogue must be server-reviewed inputs.
    Existing operations are replayed once from original stock; remaining stock
    independently reconciles the user's chronological execution ledger. No
    transactions, events, passes or salvage claims are generated here.
    """
    raw_patch = getattr(snapshot, "patch", None)
    raw_base_plan = getattr(snapshot, "base_plan", None)
    result_patch_id = _safe_result_id(getattr(raw_patch, "id", None), "unknown_patch")
    result_base_version_id = _safe_result_id(
        getattr(raw_base_plan, "version_id", None), "unknown_version"
    )
    patch_base_version_id = getattr(raw_patch, "base_version_id", None)
    base_version_id = getattr(raw_base_plan, "version_id", None)
    if (
        isinstance(patch_base_version_id, str)
        and isinstance(base_version_id, str)
        and patch_base_version_id != base_version_id
    ):
        return _blocked_snapshot(
            result_patch_id,
            result_base_version_id,
            "stale_version",
            "Patch base version does not match the supplied base plan version.",
        )
    # model_copy bypasses validators, so rebuild from dumped data to rerun
    # nested record, reference, scope, uniqueness and chronology checks.
    try:
        snapshot = ReplannerInput.model_validate(
            snapshot.model_dump(mode="python", warnings=False)
        )
    except (AttributeError, TypeError, ValueError):
        return _blocked_snapshot(
            result_patch_id,
            result_base_version_id,
            "invalid_reference",
            "Supplied repair snapshot failed validation; no repair was simulated.",
        )
    try:
        historical_plans = tuple(
            BuildPlan.model_validate(plan.model_dump(mode="python", warnings=False))
            for plan in historical_plans
        )
    except (AttributeError, TypeError, ValueError):
        return _blocked_snapshot(
            snapshot.patch.id,
            snapshot.base_plan.version_id,
            "invalid_reference",
            "Supplied historical plan failed validation; no repair was simulated.",
        )
    base, patch = snapshot.base_plan, snapshot.patch
    blockers = []

    def fail(code, message, *ids):
        blockers.append(Blocker(code=code, message=message, target_ids=ids))

    def blocked(**fields):
        return SimulationResult(
            patch_id=patch.id,
            base_version_id=base.version_id,
            status="blocked",
            blockers=tuple(blockers),
            **fields,
        )

    operations = {o.id: o for o in base.operations}
    stocks = {s.id: s for s in base.stocks}
    evidence = {e.id: e for e in snapshot.evidence}
    events = {e.id: e for e in snapshot.events}
    completed = set()
    lineage = {base.version_id: base}
    supplied = {p.version_id: p for p in historical_plans}
    if len(supplied) != len(historical_plans):
        fail("invalid_reference", "Historical plan versions must be unique.")
    current = base
    while (
        current.parent_version_id is not None and current.parent_version_id in supplied
    ):
        parent = supplied[current.parent_version_id]
        if parent.project_id != base.project_id or parent.version_id in lineage:
            fail(
                "invalid_reference",
                "Historical plans must form one acyclic project lineage.",
            )
            break
        lineage[parent.version_id] = parent
        current = parent
    if set(supplied) - set(lineage):
        fail(
            "stale_version", "Historical plans must belong to the actual base ancestry."
        )
    if supplied and current.parent_version_id is not None:
        fail(
            "stale_version",
            "Supply the complete historical ancestry through its original root plan.",
        )
    historical_changes = {vid: _affected(plan, base) for vid, plan in lineage.items()}
    patch_parts = {patch.target_id}
    if patch.kind == "replace_joint_profile":
        patch_parts = next(
            (set(j.part_ids) for j in base.joints if j.id == patch.target_id), set()
        )
    for record in (
        *snapshot.events,
        *snapshot.evidence,
        *snapshot.material_transactions,
    ):
        if record.version_id not in lineage:
            fail(
                "stale_version",
                "Supply the original ancestor plan for historical records; IDs alone do not prove compatibility.",
                record.id,
            )
    for item in snapshot.evidence:
        if (
            not set(item.part_ids) <= {p.id for p in base.parts}
            or not set(item.operation_ids) <= set(operations)
            or not set(item.checkpoint_ids) <= {c.id for c in base.checkpoints}
        ):
            fail(
                "invalid_reference",
                "Evidence refers to an unknown plan object.",
                item.id,
            )
        if item.version_id in historical_changes:
            changed_ops, changed_parts = historical_changes[item.version_id]
            source_plan = lineage[item.version_id]
            source_checks = {c.id: c for c in source_plan.checkpoints}
            current_checks = {c.id: c for c in base.checkpoints}
            if (
                not set(item.part_ids) <= {p.id for p in source_plan.parts}
                or not set(item.operation_ids) <= {o.id for o in source_plan.operations}
                or not set(item.checkpoint_ids) <= set(source_checks)
            ):
                fail(
                    "invalid_reference",
                    "Evidence IDs were not present in the original source version.",
                    item.id,
                )
            if (
                set(item.operation_ids) & changed_ops
                or set(item.part_ids) & changed_parts
                or any(
                    source_checks.get(cid) != current_checks.get(cid)
                    or source_checks[cid].after_operation_id in changed_ops
                    for cid in item.checkpoint_ids
                    if cid in source_checks
                )
            ):
                fail(
                    "needs_confirmation",
                    "Historical evidence depends on changed physical definitions.",
                    item.id,
                )
    for event in snapshot.events:
        if event.operation_id is not None and event.operation_id not in operations:
            fail(
                "invalid_reference",
                "Execution refers to an unknown operation.",
                event.id,
            )
        if not set(event.evidence_ids) <= set(evidence):
            fail("invalid_reference", "Execution evidence is missing.", event.id)
        targets = {
            pid
            for eid in event.evidence_ids
            if eid in evidence
            for pid in evidence[eid].part_ids
        }
        relevant = not targets or bool(targets & patch_parts)
        if event.kind == "damage":
            if not (
                patch.kind == "replace_part"
                and patch.target_id in targets
                and event.actor == "user"
                and event.verification_state == "user_confirmed"
                and event.evidence_ids
                and all(
                    eid in evidence
                    and evidence[eid].provenance == "user"
                    and evidence[eid].verification_state == "user_confirmed"
                    for eid in event.evidence_ids
                )
            ):
                fail(
                    "needs_confirmation",
                    "Damage requires a confirmed scoped replacement or explicit physical repair plan.",
                    event.id,
                )
        elif event.verification_state in ("failed", "unknown", "invalidated") and (
            relevant or event.kind == "operation_confirmed"
        ):
            fail(
                "needs_confirmation",
                "Resolve uncertainty relevant to this repair before simulation.",
                event.id,
            )
        if event.kind != "operation_confirmed":
            continue
        op = operations.get(event.operation_id)
        if (
            event.version_id in historical_changes
            and event.operation_id in historical_changes[event.version_id][0]
        ):
            fail(
                "irreversible_conflict",
                "Historical completion differs from the current physical definition.",
                event.id,
            )
        if event.verification_state != "user_confirmed":
            fail(
                "needs_confirmation",
                "Completion requires an explicit user-confirmed state.",
                event.id,
            )
        if event.operation_id in completed:
            fail(
                "invalid_order",
                "An operation cannot complete twice.",
                event.operation_id,
            )
        if op and not set(op.depends_on) <= completed:
            fail(
                "invalid_order",
                "Completion precedes its physical prerequisites.",
                op.id,
            )
        for eid in event.evidence_ids:
            item = evidence.get(eid)
            if item and (
                item.provenance != "user"
                or item.verification_state != "user_confirmed"
                or item.recorded_at > event.recorded_at
            ):
                fail(
                    "needs_confirmation",
                    "Completion evidence is not current user evidence.",
                    eid,
                )
        if op:
            completed.add(op.id)

    # Project the material state using only confirmed physical actions.
    regions = {r.id: (s.id, r.geometry) for s in base.stocks for r in s.usable_regions}
    known_regions = dict(regions)
    retired = {}
    lengths = {
        s.id: s.remaining_length_mm.value
        for s in base.stocks
        if s.kind in ("tape", "cord")
    }
    for op in base.operations:
        if op.id not in completed:
            continue
        if op.type == "cut_rect":
            source = regions.pop(op.args.source_region_id, None)
            if source is None:
                fail(
                    "stock_exhausted",
                    "Completed cuts double-spend or reference missing stock.",
                    op.id,
                )
            else:
                retired[op.args.source_region_id] = "consume"
            for region in op.effects.created_offcuts:
                value = (op.args.stock_id, region.geometry)
                regions[region.id] = value
                known_regions[region.id] = value
        elif op.type in ("tape_joint", "tie_joint"):
            sid = op.args.stock_id
            if lengths.get(sid) is None:
                fail("missing_measurement", "Confirm consumed connector length.", sid)
            else:
                lengths[sid] -= op.args.length_mm
                if lengths[sid] < -1e-7:
                    fail(
                        "stock_exhausted",
                        "Completed joins overspend connector stock.",
                        sid,
                    )

    seen_transactions = set()
    seen_connector_losses = set()
    lost = []
    if (
        tuple(sorted(snapshot.material_transactions, key=lambda t: t.recorded_at))
        != snapshot.material_transactions
    ):
        fail("invalid_order", "Material transactions must be chronological.")
    for tx in snapshot.material_transactions:
        event = events.get(tx.physical_event_id)
        op = operations.get(tx.operation_id)
        if (
            event is None
            or event.actor != "user"
            or event.verification_state != "user_confirmed"
            or op is None
            or tx.source_stock_id not in stocks
            or event.recorded_at > tx.recorded_at
        ):
            fail(
                "invalid_reference",
                "Material transaction lacks a matching confirmed physical event.",
                tx.id,
            )
            continue
        # Loss and salvage reconcile against the live region ledger, so a region
        # may be lost, recovered and lost again. Cut outputs are keyed by output
        # region so one cut can record each of its offcuts.
        if tx.kind in ("consume", "offcut"):
            key = (
                tx.operation_id,
                tx.kind,
                tx.source_stock_id,
                tx.source_region_id,
                tx.output_region.id if tx.output_region else None,
            )
            if key in seen_transactions:
                fail(
                    "stock_exhausted", "Duplicate physical material accounting.", tx.id
                )
            seen_transactions.add(key)
        if tx.kind == "consume":
            if (
                tx.operation_id not in completed
                or event.operation_id != tx.operation_id
            ):
                fail(
                    "invalid_reference",
                    "Consumption must match a completed operation.",
                    tx.id,
                )
            if op.type == "cut_rect":
                source = known_regions.get(op.args.source_region_id)
                if (
                    tx.source_region_id != op.args.source_region_id
                    or tx.source_stock_id != op.args.stock_id
                    or tx.unit != "mm2"
                    or source is None
                    or not _close(tx.quantity, _area(source[1]))
                ):
                    fail(
                        "invalid_reference",
                        "Consumption differs from the completed cut's parent region.",
                        tx.id,
                    )
            elif op.type in ("tape_joint", "tie_joint"):
                if (
                    tx.unit != "mm"
                    or tx.source_stock_id != op.args.stock_id
                    or not _close(tx.quantity, op.args.length_mm)
                ):
                    fail(
                        "invalid_reference",
                        "Consumption differs from completed connector use.",
                        tx.id,
                    )
            else:
                fail("unsupported", "Unsupported consumption transaction.", tx.id)
        elif tx.kind == "offcut":
            outputs = {r.id: r for r in op.effects.created_offcuts}
            out = tx.output_region
            if (
                op.id not in completed
                or event.operation_id != op.id
                or out is None
                or outputs.get(out.id) != out
                or tx.source_stock_id != getattr(op.args, "stock_id", None)
                or tx.unit != "mm2"
                or not _close(tx.quantity, _area(out.geometry))
            ):
                fail(
                    "invalid_reference",
                    "Offcut transaction must match a completed cut output.",
                    tx.id,
                )
        elif tx.kind in ("waste", "damage") and stocks[tx.source_stock_id].kind in (
            "tape",
            "cord",
        ):
            loss_key = (tx.physical_event_id, tx.source_stock_id)
            if loss_key in seen_connector_losses:
                fail(
                    "stock_exhausted", "Duplicate physical material accounting.", tx.id
                )
            else:
                seen_connector_losses.add(loss_key)
                stock = stocks[tx.source_stock_id]
                measurement = stock.remaining_length_mm
                if (
                    tx.unit != "mm"
                    or tx.source_region_id is not None
                    or tx.output_region is not None
                    or op.type not in ("tape_joint", "tie_joint")
                    or getattr(op.args, "stock_id", None) != tx.source_stock_id
                    or tx.source_stock_id not in op.stock_ids
                    or event.operation_id != tx.operation_id
                    or tx.version_id != event.version_id
                ):
                    fail(
                        "invalid_reference",
                        "Connector loss must match the connector operation and physical event.",
                        tx.id,
                    )
                elif measurement.value is None:
                    fail(
                        "missing_measurement",
                        "Confirm the original connector length before recording loss.",
                        tx.id,
                    )
                elif not measurement.confirmed:
                    fail(
                        "needs_confirmation",
                        "Confirm the original connector length before recording loss.",
                        tx.id,
                    )
                elif not event.evidence_ids:
                    fail(
                        "needs_confirmation",
                        "Connector loss requires user evidence.",
                        tx.id,
                    )
                else:
                    bad_evidence = None
                    for eid in event.evidence_ids:
                        item = evidence.get(eid)
                        if item is None or item.version_id != event.version_id:
                            bad_evidence = "invalid_reference"
                            break
                        if (
                            item.provenance != "user"
                            or item.verification_state != "user_confirmed"
                            or item.recorded_at > event.recorded_at
                        ):
                            bad_evidence = "needs_confirmation"
                            break
                    current = lengths.get(tx.source_stock_id)
                    if bad_evidence == "invalid_reference":
                        fail(
                            "invalid_reference",
                            "Connector loss evidence must match the physical event version.",
                            tx.id,
                        )
                    elif bad_evidence is not None:
                        fail(
                            "needs_confirmation",
                            "Connector loss evidence is not current user evidence.",
                            tx.id,
                        )
                    elif current is None:
                        fail(
                            "missing_measurement",
                            "Confirm the original connector length before recording loss.",
                            tx.id,
                        )
                    elif tx.quantity > current:
                        fail(
                            "stock_exhausted",
                            "Connector loss exceeds the known remaining length.",
                            tx.id,
                        )
                    else:
                        lengths[tx.source_stock_id] = current - tx.quantity
        elif tx.kind in ("waste", "damage"):
            value = regions.get(tx.source_region_id)
            if (
                value is None
                or value[0] != tx.source_stock_id
                or tx.unit != "mm2"
                or not _close(tx.quantity, _area(value[1]))
            ):
                fail(
                    "unsupported",
                    "Loss must identify an entire current region; partial damage requires a measured split.",
                    tx.id,
                )
            else:
                regions.pop(tx.source_region_id)
                retired[tx.source_region_id] = tx.kind
                lost.append(tx.source_region_id)
        elif tx.kind == "salvage":
            out = tx.output_region
            value = known_regions.get(out.id) if out else None
            if (
                out is None
                or value is None
                or retired.get(out.id) not in ("waste", "damage")
                or out.id in regions
                or value != (tx.source_stock_id, out.geometry)
                or tx.unit != "mm2"
                or not _close(tx.quantity, _area(out.geometry))
            ):
                fail(
                    "unsupported",
                    "Salvage requires a confirmed exact previously lost offcut; consumed parents cannot return.",
                    tx.id,
                )
            else:
                regions[out.id] = value
                retired.pop(out.id)
                lost = [rid for rid in lost if rid != out.id]

    remaining = {s.id: s for s in snapshot.remaining_stock}
    if len(remaining) != len(snapshot.remaining_stock):
        fail("invalid_reference", "Remaining stock IDs must be unique.")
    if set(remaining) != set(stocks):
        fail(
            "invalid_reference",
            "Remaining inventory must contain exactly the known physical sources.",
        )
    touched_stock_ids = _touched_stock_ids(snapshot)
    actual_regions = {}
    for stock in snapshot.remaining_stock:
        original = stocks.get(stock.id)
        if original is None:
            continue
        if stock.id not in touched_stock_ids:
            # Untouched unused inventory may stay exactly as unknown and
            # uncertain as originally recorded: it supports no part, operation
            # or patch, so it neither blocks the repair nor becomes usable
            # availability. Any change to it is a conflict, not confirmation.
            # Regions are still collected below so structural reconciliation,
            # including duplicate detection, applies unchanged.
            if stock != original:
                fail(
                    "needs_confirmation",
                    "Unused inventory changed from its original unknown state; confirm the new identity, measurements or condition explicitly.",
                    stock.id,
                )
        else:
            if (
                stock.kind != original.kind
                or stock.material != original.material
                or stock.width_mm != original.width_mm
                or stock.height_mm != original.height_mm
                or stock.thickness_mm != original.thickness_mm
                or stock.condition != "usable"
            ):
                fail(
                    "needs_confirmation",
                    "Inventory identity, measurements or condition conflict with physical history.",
                    stock.id,
                )
            if stock.kind in ("tape", "cord"):
                expected = lengths.get(stock.id)
                value = stock.remaining_length_mm
                if (
                    expected is None
                    or value.value is None
                    or not value.confirmed
                    or not _close(expected, value.value)
                ):
                    fail(
                        "stock_exhausted",
                        "Remaining connector length conflicts with confirmed consumption.",
                        stock.id,
                    )
        for region in stock.usable_regions:
            if region.id in actual_regions:
                fail("stock_exhausted", "A remaining region appears twice.", region.id)
            actual_regions[region.id] = (stock.id, region.geometry)
    if actual_regions != regions:
        fail(
            "stock_exhausted",
            "Remaining regions conflict with confirmed cuts, loss or salvage.",
        )
    if blockers:
        return blocked(lost_region_ids=tuple(lost))

    data = base.model_dump(mode="python")
    if patch.kind == "resize_part":
        target = next((p for p in data["parts"] if p["id"] == patch.target_id), None)
        if target is None:
            fail(
                "invalid_reference",
                "Resize target must be an existing part.",
                patch.target_id,
            )
        else:
            stand_handled, stand_blocker, stand_geometries = _stand_base_resize(
                base, patch, completed, regions
            )
            if stand_blocker is not None:
                blockers.append(stand_blocker)
            elif stand_handled:
                for part in data["parts"]:
                    geometry = stand_geometries.get(part["id"])
                    if geometry is not None:
                        part["geometry"].update(geometry)
            else:
                target["geometry"].update(width=patch.width_mm, height=patch.height_mm)
    elif patch.kind == "replace_joint_profile":
        target = next((j for j in data["joints"] if j["id"] == patch.target_id), None)
        catalogue = {p.id: p for p in base.joint_profiles}
        replacement = catalogue.get(patch.replacement_profile_id)
        if target is None or replacement is None:
            fail(
                "invalid_reference",
                "Profile replacement requires an existing joint and catalogue profile.",
                patch.target_id,
            )
        elif catalogue[target["profile_id"]].strategy != replacement.strategy:
            fail(
                "unsupported",
                "Changing joint strategy needs explicit connector routing and a new operation plan.",
                patch.target_id,
            )
        else:
            previous = target["profile_id"]
            target["profile_id"] = replacement.id
            # Slot machining must use the same profile as its insertion.
            feature_ids = set(target["interface_feature_ids"])
            for op in data["operations"]:
                if (
                    op["type"] == "cut_slot"
                    and op["args"]["feature_id"] in feature_ids
                    and op["args"]["profile_id"] == previous
                ):
                    op["args"]["profile_id"] = replacement.id
    elif patch.kind == "change_angle":
        if patch.target_id != base.version_id:
            fail(
                "invalid_reference",
                "Angle target must be the base plan version.",
                patch.target_id,
            )
        else:
            fail(
                "unsupported",
                "Angle changes require family geometry regeneration; changing the constraint alone is not a repair.",
                patch.target_id,
            )
    else:
        if (
            patch.target_id not in {p.id for p in base.parts}
            or patch.replacement_stock_id not in remaining
        ):
            fail(
                "invalid_reference",
                "Replacement requires a known part and actual remaining source.",
                patch.target_id,
            )
        else:
            original = next(p for p in base.parts if p.id == patch.target_id)
            creator = next(
                (
                    o
                    for o in base.operations
                    if original.id in o.effects.created_part_ids
                ),
                None,
            )
            if creator is None or creator.id not in completed:
                fail(
                    "unsupported",
                    "Part replacement currently requires an existing physically cut part; resize unfinished parts instead.",
                    original.id,
                )
            elif process is None:
                fail(
                    "unsupported_profile",
                    "Replacement cut requires a measured cutting process.",
                )
            else:
                margin = max(process.edge_margin_min_mm, creator.args.edge_margin_mm)
                kerf = max(process.kerf_min_mm, creator.args.kerf_mm)
                source = next(
                    (
                        r
                        for r in remaining[patch.replacement_stock_id].usable_regions
                        if r.geometry.width >= original.geometry.width + 2 * margin
                        and r.geometry.height >= original.geometry.height + 2 * margin
                    ),
                    None,
                )
                if source is None:
                    fail(
                        "stock_exhausted",
                        "No actual remaining region fits the replacement and measured margins.",
                        patch.replacement_stock_id,
                    )
                else:
                    token = sha256(patch.model_dump_json().encode()).hexdigest()[:10]
                    new_pid, new_cut = (
                        f"replacement_{token}",
                        f"replacement_cut_{token}",
                    )
                    feature_map = {
                        f.id: f"replacement_feature_{token}_{i}"
                        for i, f in enumerate(original.features)
                    }
                    newpart = original.model_dump(mode="python")
                    newpart.update(
                        id=new_pid,
                        source_stock_id=patch.replacement_stock_id,
                        source_region_id=source.id,
                        condition="usable",
                    )
                    newpart["geometry"].update(
                        x=source.geometry.x + margin, y=source.geometry.y + margin
                    )
                    for feature in newpart["features"]:
                        feature["id"] = feature_map[feature["id"]]
                    data["parts"] = (*data["parts"], newpart)
                    replacement_joints = {
                        j.id for j in base.joints if original.id in j.part_ids
                    }
                    for oldop in base.operations:
                        if (
                            oldop.id in completed
                            and oldop.type
                            not in ("cut_rect", "inspect", "functional_test", "measure")
                            and (
                                original.id in oldop.part_ids
                                or getattr(oldop.args, "part_id", None) == original.id
                                or getattr(oldop.args, "joint_id", None)
                                in replacement_joints
                            )
                        ):
                            fail(
                                "unsupported",
                                "Replacing an attached or modified part requires explicit physical undo.",
                                oldop.id,
                            )
                    for joint in data["joints"]:
                        joint["part_ids"] = tuple(
                            new_pid if p == original.id else p
                            for p in joint["part_ids"]
                        )
                        joint["interface_feature_ids"] = tuple(
                            feature_map.get(f, f)
                            for f in joint["interface_feature_ids"]
                        )
                    for op in data["operations"]:
                        if op["type"] == "cut_rect":
                            continue
                        refs_old = original.id in op["part_ids"]
                        refs_old |= original.id in op["preconditions"].get(
                            "accessible_part_ids", ()
                        )
                        op["part_ids"] = tuple(
                            new_pid if p == original.id else p for p in op["part_ids"]
                        )
                        op["preconditions"]["accessible_part_ids"] = tuple(
                            new_pid if p == original.id else p
                            for p in op["preconditions"].get("accessible_part_ids", ())
                        )
                        for name in ("part_id", "brace_part_id", "target_id"):
                            if op["args"].get(name) == original.id:
                                op["args"][name] = new_pid
                                refs_old = True
                        if "target_ids" in op["args"]:
                            refs_old |= original.id in op["args"]["target_ids"]
                            op["args"]["target_ids"] = tuple(
                                new_pid if p == original.id else p
                                for p in op["args"]["target_ids"]
                            )
                        for name in ("feature_id", "tab_feature_id", "slot_feature_id"):
                            if op["args"].get(name) in feature_map:
                                op["args"][name] = feature_map[op["args"][name]]
                                refs_old = True
                        op["effects"]["changed_part_ids"] = tuple(
                            new_pid if p == original.id else p
                            for p in op["effects"]["changed_part_ids"]
                        )
                        if refs_old or op["args"].get("joint_id") in replacement_joints:
                            op["depends_on"] = tuple(
                                dict.fromkeys((*op["depends_on"], new_cut))
                            )
                    source_producer = next(
                        (
                            o.id
                            for o in base.operations
                            if any(r.id == source.id for r in o.effects.created_offcuts)
                        ),
                        None,
                    )
                    cut = dict(
                        id=new_cut,
                        type="cut_rect",
                        stock_ids=[patch.replacement_stock_id],
                        depends_on=[source_producer] if source_producer else [],
                        expected_state_id=f"replacement_state_{token}",
                        preconditions=dict(
                            safe_tools_confirmed=creator.preconditions.safe_tools_confirmed,
                            human_checks=[
                                "Confirm replacement dimensions and cutting tools before the new cut."
                            ],
                        ),
                        effects=dict(
                            created_part_ids=[new_pid], consumed_region_ids=[source.id]
                        ),
                        args=dict(
                            stock_id=patch.replacement_stock_id,
                            source_region_id=source.id,
                            child_part_ids=[new_pid],
                            kerf_mm=kerf,
                            edge_margin_mm=margin,
                        ),
                    )
                    insert_at = next(
                        (
                            i + 1
                            for i, o in enumerate(data["operations"])
                            if o["id"] == source_producer
                        ),
                        0,
                    )
                    updated = list(data["operations"])
                    updated.insert(insert_at, cut)
                    data["operations"] = updated
    if blockers:
        return blocked(lost_region_ids=tuple(lost))
    try:
        candidate = BuildPlan.model_validate(data)
    except ValidationError:
        fail(
            "invalid_reference", "Patch does not produce a valid typed plan.", patch.id
        )
        return blocked()
    affected, changed_parts = _affected(base, candidate)
    if not affected:
        fail(
            "no_feasible_repair",
            "Patch leaves all operation definitions and relevant geometry unchanged.",
            patch.id,
        )
        return blocked()
    verification_ops = {
        o.id
        for o in base.operations
        if o.type in ("inspect", "functional_test", "measure")
    }
    incompatible = completed & affected - verification_ops
    undo = tuple(
        o.id
        for o in base.operations
        if o.id in incompatible and o.reversible in ("reversible", "lossy")
    )
    for oid in incompatible:
        op = operations[oid]
        code = (
            "irreversible_conflict"
            if op.reversible == "irreversible"
            else "unsupported"
        )
        fail(
            code,
            "Completed physical work changes; an explicit replacement/undo continuation is required.",
            oid,
        )
    invalid_checks = tuple(
        c.id
        for c in base.checkpoints
        if c.after_operation_id in affected or set(c.invalidated_by) & affected
    )
    invalid_evidence = tuple(
        e.id
        for e in snapshot.evidence
        if set(e.operation_ids) & affected
        or set(e.part_ids) & changed_parts
        or set(e.checkpoint_ids) & set(invalid_checks)
    )
    lost_parts = (patch.target_id,) if patch.kind == "replace_part" else ()
    lost_operations = tuple(
        o.id
        for o in base.operations
        if o.id in completed
        and o.type == "cut_rect"
        and set(o.effects.created_part_ids) <= set(lost_parts)
    )
    # Retained legacy cuts remain historically complete, but discarded work is
    # not advertised as usable preservation.
    kept = tuple(
        o.id
        for o in base.operations
        if o.id in completed and o.id not in affected and o.id not in lost_operations
    )
    changed_parts.update(lost_parts)
    invalid_checks = tuple(
        dict.fromkeys(
            (
                *invalid_checks,
                *(
                    c.id
                    for c in base.checkpoints
                    if c.after_operation_id in lost_operations
                ),
            )
        )
    )
    invalid_evidence = tuple(
        e.id
        for e in snapshot.evidence
        if set(e.operation_ids) & (affected | set(lost_operations))
        or set(e.part_ids) & changed_parts
        or set(e.checkpoint_ids) & set(invalid_checks)
    )
    if blockers:
        return blocked(
            preserved_operation_ids=kept,
            required_undo_operation_ids=undo,
            changed_part_ids=tuple(sorted(changed_parts)),
            invalidated_checkpoint_ids=invalid_checks,
            invalidated_evidence_ids=invalid_evidence,
            lost_region_ids=tuple(lost),
        )
    suffix = sha256(patch.model_dump_json().encode()).hexdigest()[:10]
    renamed = {
        oid: f"repair_{suffix}_{i}"
        for i, oid in enumerate(o.id for o in base.operations if o.id in affected)
    }
    data = candidate.model_dump(mode="python")
    data.update(
        version_id=f"revision_{suffix}",
        parent_version_id=base.version_id,
        status="draft",
    )
    existing_ids = {
        r.id
        for group in (
            base.stocks,
            base.parts,
            base.joints,
            base.operations,
            base.checkpoints,
            base.joint_profiles,
        )
        for r in group
    }
    if data["version_id"] == base.version_id or set(renamed.values()) & existing_ids:
        fail(
            "invalid_reference",
            "Derived revision identity collides with existing physical identities.",
        )
        return blocked()
    for op in data["operations"]:
        old_id = op["id"]
        op["id"] = renamed.get(old_id, old_id)
        op["depends_on"] = tuple(renamed.get(d, d) for d in op["depends_on"])
        if old_id in renamed:
            op["expected_state_id"] = f"state_{op['id']}"
    for checkpoint in data["checkpoints"]:
        checkpoint["after_operation_id"] = renamed.get(
            checkpoint["after_operation_id"], checkpoint["after_operation_id"]
        )
        checkpoint["invalidated_by"] = tuple(
            renamed.get(d, d) for d in checkpoint["invalidated_by"]
        )
    try:
        candidate = BuildPlan.model_validate(data)
    except ValidationError:
        fail(
            "invalid_reference",
            "New operation identities conflict with the plan contract.",
        )
        return blocked()
    validation = validate_plan(
        candidate, process=process, allow_synthetic=allow_synthetic
    )
    if validation.blockers:
        blockers.extend(validation.blockers)
        return blocked(
            preserved_operation_ids=kept,
            changed_part_ids=tuple(sorted(changed_parts)),
            invalidated_checkpoint_ids=invalid_checks,
            invalidated_evidence_ids=invalid_evidence,
        )
    if (
        candidate.compiler_version == "triangular-tape-stand-v1"
        and family_validator is None
    ):
        fail(
            "unsupported",
            "This stand requires its geometry/manual continuation validator before repair can be feasible.",
        )
    if family_validator is not None:
        try:
            # Materialize first so a failure during lazy iteration cannot
            # leave partially validated blockers behind. Ordinary callback
            # failures become one stable, safe blocker; the exception text
            # is never exposed. BaseException (e.g. KeyboardInterrupt and
            # SystemExit) is not an Exception subclass and still propagates.
            family_blockers = tuple(
                Blocker.model_validate(b) for b in family_validator(candidate)
            )
        except Exception:
            fail(
                "unsupported",
                "Family continuation validator did not return a valid result.",
            )
        else:
            blockers.extend(family_blockers)
    # Original stock validates historical cuts once. Only future work may spend
    # the reconciled remaining ledger, including real subsequent loss events.
    future_regions = dict(regions)
    future_lengths = dict(lengths)
    material_deltas = []
    for pid in lost_parts:
        part = next(p for p in base.parts if p.id == pid)
        material_deltas.append(
            MaterialDelta(
                stock_id=part.source_stock_id,
                source_region_id=part.source_region_id,
                operation_id=None,
                kind="retire_part",
                quantity=_area(part.geometry),
                unit="mm2",
            )
        )
    candidate_parts = {p.id: p for p in candidate.parts}
    for op in candidate.operations:
        if op.id in completed and op.id not in affected:
            continue
        if op.type == "cut_rect":
            source = future_regions.pop(op.args.source_region_id, None)
            if source is None or source[0] != op.args.stock_id:
                fail(
                    "stock_exhausted",
                    "Future cuts require actual remaining stock, not historical allocations.",
                    op.id,
                )
            else:
                material_deltas.append(
                    MaterialDelta(
                        stock_id=source[0],
                        source_region_id=op.args.source_region_id,
                        operation_id=op.id,
                        kind="consume",
                        quantity=_area(source[1]),
                        unit="mm2",
                    )
                )
                waste = (
                    _area(source[1])
                    - sum(
                        _area(candidate_parts[p].geometry)
                        for p in op.args.child_part_ids
                    )
                    - sum(_area(r.geometry) for r in op.effects.created_offcuts)
                )
                if waste > 1e-7:
                    material_deltas.append(
                        MaterialDelta(
                            stock_id=source[0],
                            source_region_id=op.args.source_region_id,
                            operation_id=op.id,
                            kind="waste",
                            quantity=waste,
                            unit="mm2",
                        )
                    )
            for region in op.effects.created_offcuts:
                future_regions[region.id] = (op.args.stock_id, region.geometry)
        elif op.type in ("tape_joint", "tie_joint"):
            sid = op.args.stock_id
            if future_lengths.get(sid) is None:
                fail(
                    "missing_measurement",
                    "Future join needs measured remaining connector stock.",
                    sid,
                )
            else:
                future_lengths[sid] -= op.args.length_mm
                material_deltas.append(
                    MaterialDelta(
                        stock_id=sid,
                        source_region_id=None,
                        operation_id=op.id,
                        kind="consume",
                        quantity=op.args.length_mm,
                        unit="mm",
                    )
                )
                if future_lengths[sid] < -1e-7:
                    fail(
                        "stock_exhausted",
                        "Future join exceeds actual remaining connector length.",
                        op.id,
                    )
    if blockers:
        return blocked(
            preserved_operation_ids=kept,
            changed_part_ids=tuple(sorted(changed_parts)),
            invalidated_checkpoint_ids=invalid_checks,
            invalidated_evidence_ids=invalid_evidence,
            lost_region_ids=tuple(lost),
        )
    new_ids = tuple(
        o.id
        for o in candidate.operations
        if o.id not in kept and (o.id in renamed.values() or o.id not in operations)
    )
    new_irreversible = sum(
        o.reversible == "irreversible" for o in candidate.operations if o.id in new_ids
    )
    cost = RepairCost(
        irreversible_completed_actions_lost=len(lost_operations),
        required_physical_undos=0,
        new_irreversible_actions=new_irreversible,
        known_weighted_cost=5 * len(lost_operations) + 2 * new_irreversible,
    )
    unknown_checks = tuple(
        dict.fromkeys(
            check
            for o in candidate.operations
            for check in o.preconditions.human_checks
        )
    )
    additional = tuple(
        dict.fromkeys(
            sid for o in candidate.operations if o.id in new_ids for sid in o.stock_ids
        )
    )
    return SimulationResult(
        patch_id=patch.id,
        base_version_id=base.version_id,
        status="feasible",
        plan=candidate,
        preserved_operation_ids=kept,
        redo_operation_ids=tuple(
            renamed[o.id] for o in base.operations if o.id in completed & affected
        ),
        newly_required_operation_ids=new_ids,
        incomplete_operation_ids=tuple(
            o.id
            for o in candidate.operations
            if o.id not in completed or o.id in affected
        ),
        changed_part_ids=tuple(sorted(changed_parts)),
        invalidated_checkpoint_ids=invalid_checks,
        invalidated_evidence_ids=invalid_evidence,
        lost_region_ids=tuple(lost),
        lost_part_ids=lost_parts,
        lost_operation_ids=lost_operations,
        additional_material_stock_ids=additional,
        proposed_material_deltas=tuple(material_deltas),
        cost=cost,
        unknown_physical_checks=unknown_checks,
    )


def rank_feasible(
    results: tuple[SimulationResult, ...],
) -> tuple[SimulationResult, ...]:
    """Rank up to three hard-feasible previews by known terms only.

    Unknown time, waste and purchase estimates remain null; this is explicitly
    a partial heuristic ordering, not the full cost formula or a physical proof.
    """
    if len(results) > 3:
        raise ValueError("at most three repair candidates")
    return tuple(
        sorted(
            (r for r in results if r.status == "feasible" and r.cost is not None),
            key=lambda r: (
                r.cost.known_weighted_cost,
                len(r.unknown_physical_checks),
                r.cost.new_irreversible_actions,
                r.patch_id,
            ),
        )
    )
