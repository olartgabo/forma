"""Replay explicit allocations without network, persistence or physical claims."""

from dataclasses import dataclass

from pydantic import ValidationError

from forma_domain.models import (
    Blocker,
    BuildPlan,
    CompilerResult,
    Rect,
)

from .process import CutProcess

EPS = 1e-7


def contains(outer: Rect, inner: Rect, margin: float = 0) -> bool:
    return (
        inner.x >= outer.x + margin - EPS
        and inner.y >= outer.y + margin - EPS
        and inner.x + inner.width <= outer.x + outer.width - margin + EPS
        and inner.y + inner.height <= outer.y + outer.height - margin + EPS
    )


def overlaps(a: Rect, b: Rect, gap: float = 0) -> bool:
    return (
        a.x < b.x + b.width + gap - EPS
        and b.x < a.x + a.width + gap - EPS
        and a.y < b.y + b.height + gap - EPS
        and b.y < a.y + a.height + gap - EPS
    )


@dataclass(frozen=True)
class Allocation:
    stock_id: str
    geometry: Rect
    producer: str | None


def validate_plan(
    plan: BuildPlan, *, process: CutProcess | None = None, allow_synthetic: bool = False
) -> CompilerResult:
    """Validate a complete typed plan by replaying its proposed resource effects.

    Cut coordinates are absolute in the original stock frame. Width/height are
    the occupied footprint after rotation; rotation is metadata, never a second
    implicit transform. Unallocated cut area is waste, never reusable stock.
    """
    try:
        plan = BuildPlan.model_validate_json(plan.model_dump_json())
        if process is not None:
            process = CutProcess.model_validate_json(process.model_dump_json())
    except (ValidationError, AttributeError, TypeError, ValueError):
        return CompilerResult(
            status="blocked",
            plan=None,
            blockers=(
                Blocker(
                    code="invalid_reference",
                    message="Revalidate the plan and process contracts before compilation.",
                ),
            ),
        )
    blockers: list[Blocker] = []
    stocks = {s.id: s for s in plan.stocks}
    parts = {p.id: p for p in plan.parts}
    profiles = {p.id: p for p in plan.joint_profiles}
    joints = {j.id: j for j in plan.joints}
    features = {f.id: (p, f) for p in plan.parts for f in p.features}
    regions: dict[str, Allocation] = {}
    lengths: dict[str, float] = {}
    available_parts: dict[str, str] = {}
    attached: set[str] = set()
    joint_producers: dict[str, str] = {}
    measurement_producers = {
        o.args.measurement_id: o.id for o in plan.operations if o.type == "measure"
    }
    produced_features: dict[str, str] = {}
    ancestors: dict[str, set[str]] = {}

    def fail(code: str, message: str, *ids: str):
        blockers.append(Blocker(code=code, message=message, target_ids=ids))

    def measured(m, target: str, label: str) -> bool:
        if m.value is None or not m.confirmed:
            fail(
                "missing_measurement",
                f"Confirm {label} before irreversible work.",
                target,
            )
            return False
        return True

    if any(o.type in ("cut_rect", "cut_slot") for o in plan.operations) and (
        process is None or not process.verified(allow_synthetic=allow_synthetic)
    ):
        fail(
            "unsupported_profile",
            "Cutting requires measured process evidence; synthetic fixtures require explicit opt-in.",
        )
    if process is not None and any(
        e.project_id != plan.project_id for e in process.evidence
    ):
        fail("invalid_reference", "Cut process evidence belongs to another project.")

    for stock in plan.stocks:
        if stock.kind in ("tape", "cord"):
            if measured(
                stock.remaining_length_mm, stock.id, "remaining connector length"
            ):
                lengths[stock.id] = stock.remaining_length_mm.value
            if stock.usable_regions:
                fail(
                    "geometry_invalid",
                    "Linear connector stock cannot contain sheet regions.",
                    stock.id,
                )
            continue
        dimensions = [
            measured(getattr(stock, name), stock.id, name)
            for name in ("width_mm", "height_mm", "thickness_mm")
        ]
        if not all(dimensions):
            continue
        bounds = Rect(
            x=0, y=0, width=stock.width_mm.value, height=stock.height_mm.value
        )
        prior: list[Rect] = []
        for region in stock.usable_regions:
            if not contains(bounds, region.geometry) or any(
                overlaps(region.geometry, r) for r in prior
            ):
                fail(
                    "geometry_invalid",
                    "Usable regions must be disjoint and inside measured stock.",
                    stock.id,
                    region.id,
                )
            prior.append(region.geometry)
            if stock.condition == "usable":
                regions[region.id] = Allocation(stock.id, region.geometry, None)

    def need_part(pid: str, op_id: str):
        producer = available_parts.get(pid)
        if producer is None:
            fail(
                "invalid_order", "Part must be produced by a preceding cut.", op_id, pid
            )
        elif producer not in ancestors[op_id]:
            fail(
                "invalid_order",
                "Operation must depend on its part producer.",
                op_id,
                pid,
            )
        if parts[pid].condition != "usable":
            fail(
                "needs_confirmation",
                "Damaged or uncertain part cannot be used.",
                op_id,
                pid,
            )

    def joint_profile(jid: str, op_id: str, strategies: tuple[str, ...]):
        joint = joints[jid]
        profile = profiles[joint.profile_id]
        if profile.status != "tested" or profile.strategy not in strategies:
            fail(
                "unsupported_profile",
                "Joint requires a tested profile for this operation.",
                op_id,
                profile.id,
            )
        if profile.id not in plan.constraints.allowed_profile_ids:
            fail(
                "unsupported_profile",
                "Joint profile is not allowed by project constraints.",
                op_id,
                profile.id,
            )
        if joint.confirmed_accessible is not True:
            fail("needs_confirmation", "Confirm actual joint access.", op_id, jid)
        for pid in joint.part_ids:
            need_part(pid, op_id)
            stock = stocks[parts[pid].source_stock_id]
            m = stock.thickness_mm
            if (
                profile.material != stock.material
                or m.value is None
                or not m.confirmed
                or profile.thickness_min_mm is None
                or profile.thickness_max_mm is None
                or not profile.thickness_min_mm <= m.value <= profile.thickness_max_mm
            ):
                fail(
                    "unsupported_profile",
                    "Material/thickness is outside measured profile limits.",
                    pid,
                    profile.id,
                )
        return joint, profile

    for op in plan.operations:
        ancestors[op.id] = set(op.depends_on)
        for dep in op.depends_on:
            ancestors[op.id].update(ancestors[dep])
        a, e = op.args, op.effects
        if op.type in ("cut_slot", "fold") and e.changed_part_ids != (a.part_id,):
            fail(
                "invalid_reference",
                "Physical feature changes must name exactly the affected part.",
                op.id,
            )
        if op.type in ("cut_rect", "cut_slot") and process is not None:
            if (
                a.kerf_mm < process.kerf_min_mm
                or a.edge_margin_mm < process.edge_margin_min_mm
            ):
                fail(
                    "geometry_invalid",
                    "Cut violates measured kerf or edge-margin limits.",
                    op.id,
                )
        if (
            op.type in ("cut_rect", "cut_slot")
            and not op.preconditions.safe_tools_confirmed
        ):
            fail("needs_confirmation", "Confirm suitable tools before cutting.", op.id)
        for mid in op.preconditions.confirmed_measurement_ids:
            if measurement_producers[mid] not in ancestors[op.id]:
                fail(
                    "invalid_order",
                    "Measurement prerequisite must precede the action through its dependency graph.",
                    op.id,
                    mid,
                )
        if op.type == "measure" and a.target_id in parts:
            need_part(a.target_id, op.id)
        for jid in op.preconditions.required_joint_ids:
            if jid not in attached or joint_producers.get(jid) not in ancestors[op.id]:
                fail("invalid_order", "Required joint is not attached.", op.id, jid)
        if op.type == "cut_rect":
            source = regions.pop(a.source_region_id, None)
            if source is None:
                fail(
                    "stock_exhausted",
                    "Source region is unavailable or already consumed.",
                    op.id,
                    a.source_region_id,
                )
                continue
            if source.stock_id != a.stock_id:
                fail(
                    "invalid_reference",
                    "Region belongs to another physical stock.",
                    op.id,
                    a.stock_id,
                )
            if source.producer and source.producer not in ancestors[op.id]:
                fail(
                    "invalid_order",
                    "Offcut use requires dependency on its producing cut.",
                    op.id,
                )
            if set(e.created_part_ids) != set(
                a.child_part_ids
            ) or e.consumed_region_ids != (a.source_region_id,):
                fail(
                    "invalid_reference",
                    "Cut effects must exactly match child parts and consumed source.",
                    op.id,
                )
            geometries: list[Rect] = []
            for pid in a.child_part_ids:
                part = parts[pid]
                if pid in available_parts:
                    fail(
                        "stock_exhausted",
                        "A physical part can be created only once.",
                        pid,
                    )
                if (
                    part.source_stock_id != a.stock_id
                    or part.source_region_id != a.source_region_id
                ):
                    fail(
                        "invalid_reference",
                        "Child must retain stock and region provenance.",
                        pid,
                    )
                allowed = getattr(stocks[a.stock_id], "allowed_rotations_deg", (0, 90))
                if part.geometry.rotation_deg not in allowed:
                    fail(
                        "geometry_invalid",
                        "Part orientation violates stock restrictions.",
                        pid,
                    )
                if not contains(source.geometry, part.geometry, a.edge_margin_mm):
                    fail(
                        "geometry_invalid",
                        "Child cut exceeds source or edge margin.",
                        op.id,
                        pid,
                    )
                if any(overlaps(part.geometry, g, a.kerf_mm) for g in geometries):
                    fail(
                        "geometry_invalid",
                        "Child cuts overlap or violate kerf separation.",
                        op.id,
                        pid,
                    )
                geometries.append(part.geometry)
                available_parts[pid] = op.id
                for feature in part.features:
                    local = Rect(
                        x=0, y=0, width=part.geometry.width, height=part.geometry.height
                    )
                    if not contains(local, feature.geometry):
                        fail(
                            "geometry_invalid",
                            "Feature exceeds its owning part.",
                            pid,
                            feature.id,
                        )
                    if feature.kind == "tab":
                        produced_features[feature.id] = op.id
            for offcut in e.created_offcuts:
                if not contains(source.geometry, offcut.geometry) or any(
                    overlaps(offcut.geometry, g, a.kerf_mm) for g in geometries
                ):
                    fail(
                        "geometry_invalid",
                        "Offcut overlaps allocated material or exceeds its source.",
                        op.id,
                        offcut.id,
                    )
                geometries.append(offcut.geometry)
                regions[offcut.id] = Allocation(source.stock_id, offcut.geometry, op.id)
        else:
            for pid in op.part_ids:
                need_part(pid, op.id)
            if e.created_part_ids or e.consumed_region_ids or e.created_offcuts:
                fail(
                    "unsupported",
                    "Only cut_rect may create parts or transform sheet regions.",
                    op.id,
                )
            if op.type in ("mark", "cut_slot"):
                part = parts[a.part_id]
                need_part(part.id, op.id)
                local = Rect(
                    x=0, y=0, width=part.geometry.width, height=part.geometry.height
                )
                margin = a.edge_margin_mm if op.type == "cut_slot" else 0
                if not contains(local, a.geometry, margin):
                    fail(
                        "geometry_invalid",
                        "Feature is outside part bounds or margin.",
                        op.id,
                        part.id,
                    )
                feature = features[a.feature_id][1]
                if (
                    features[a.feature_id][0].id != part.id
                    or feature.geometry != a.geometry
                ):
                    fail(
                        "invalid_reference",
                        "Feature must match its owning part and operation geometry.",
                        op.id,
                    )
                required_kind = "slot" if op.type == "cut_slot" else "mark"
                if feature.kind != required_kind:
                    fail(
                        "invalid_reference",
                        "Feature kind does not match the physical operation.",
                        op.id,
                    )
                if op.type == "cut_slot":
                    profile = profiles[a.profile_id]
                    stock = stocks[part.source_stock_id]
                    if (
                        profile.status != "tested"
                        or profile.strategy != "tab_slot"
                        or profile.id not in plan.constraints.allowed_profile_ids
                        or profile.material != stock.material
                        or stock.thickness_mm.value is None
                        or profile.thickness_min_mm is None
                        or profile.thickness_max_mm is None
                        or not profile.thickness_min_mm
                        <= stock.thickness_mm.value
                        <= profile.thickness_max_mm
                    ):
                        fail(
                            "unsupported_profile",
                            "Slot requires an allowed measured material-compatible tab/slot profile.",
                            op.id,
                        )
                produced_features[a.feature_id] = op.id
            elif op.type == "fold":
                need_part(a.part_id, op.id)
                p = parts[a.part_id]
                if (
                    a.start_x_mm == a.end_x_mm
                    and a.start_y_mm == a.end_y_mm
                    or max(a.start_x_mm, a.end_x_mm) > p.geometry.width
                    or max(a.start_y_mm, a.end_y_mm) > p.geometry.height
                ):
                    fail(
                        "geometry_invalid",
                        "Fold line must be nonzero and inside its part.",
                        op.id,
                    )
                candidates = [
                    profile
                    for profile in plan.joint_profiles
                    if profile.strategy == "fold_brace"
                    and profile.status == "tested"
                    and profile.id in plan.constraints.allowed_profile_ids
                ]
                stock = stocks[p.source_stock_id]
                candidates = [
                    f
                    for f in candidates
                    if f.material == stock.material
                    and f.thickness_min_mm is not None
                    and f.thickness_max_mm is not None
                    and stock.thickness_mm.value is not None
                    and f.thickness_min_mm
                    <= stock.thickness_mm.value
                    <= f.thickness_max_mm
                ]
                owner, feature = features[a.feature_id]
                if owner.id != p.id or feature.kind != "fold":
                    fail(
                        "invalid_reference",
                        "Fold must reference its own fold feature.",
                        op.id,
                    )
                if not candidates:
                    fail(
                        "unsupported_profile",
                        "Folding requires an allowed material-compatible tested fold profile.",
                        op.id,
                    )
                produced_features[a.feature_id] = op.id
            elif op.type in ("insert_tab", "tape_joint", "tie_joint", "attach_brace"):
                strategies = {
                    "insert_tab": ("tab_slot",),
                    "tape_joint": ("tape",),
                    "tie_joint": ("tie",),
                    "attach_brace": ("fold_brace", "tape", "tie", "tab_slot"),
                }[op.type]
                joint, profile = joint_profile(a.joint_id, op.id, strategies)
                if a.joint_id in attached:
                    fail(
                        "invalid_order", "Joint is already attached.", op.id, a.joint_id
                    )
                if e.attached_joint_ids != (a.joint_id,):
                    fail(
                        "invalid_reference",
                        "Join effects must name exactly the attached joint.",
                        op.id,
                    )
                if op.type == "insert_tab":
                    tabp, tab = features[a.tab_feature_id]
                    slotp, slot = features[a.slot_feature_id]
                    for fid in (a.tab_feature_id, a.slot_feature_id):
                        if produced_features.get(fid) not in ancestors[op.id]:
                            fail(
                                "invalid_order",
                                "Joint feature must be physically produced by an operation dependency.",
                                op.id,
                                fid,
                            )
                    slot_ops = [
                        s
                        for s in plan.operations
                        if s.type == "cut_slot"
                        and s.args.feature_id == a.slot_feature_id
                    ]
                    if not slot_ops or any(
                        s.args.profile_id != profile.id for s in slot_ops
                    ):
                        fail(
                            "unsupported_profile",
                            "Slot and insertion must use the same measured profile.",
                            op.id,
                        )
                    tolerance = profile.tolerated_error_mm
                    if (
                        tab.kind != "tab"
                        or slot.kind != "slot"
                        or tabp.id not in joint.part_ids
                        or slotp.id not in joint.part_ids
                        or tabp.id == slotp.id
                        or tolerance is None
                        or abs(tab.geometry.width - slot.geometry.width) > tolerance
                        or (
                            stocks[tabp.source_stock_id].thickness_mm.value is None
                            or abs(
                                stocks[tabp.source_stock_id].thickness_mm.value
                                - slot.geometry.height
                            )
                            > tolerance
                        )
                    ):
                        fail(
                            "geometry_invalid",
                            "Tab/slot dimensions do not match the measured profile.",
                            op.id,
                        )
                if op.type in ("tape_joint", "tie_joint"):
                    expected = "tape" if op.type == "tape_joint" else "cord"
                    if (
                        stocks[a.stock_id].kind != expected
                        or stocks[a.stock_id].condition != "usable"
                    ):
                        fail(
                            "stock_exhausted",
                            "Compatible usable connector stock is required.",
                            op.id,
                        )
                    balance = lengths.get(a.stock_id, 0) - a.length_mm
                    if balance < -EPS:
                        fail(
                            "stock_exhausted",
                            "Connector length is oversubscribed.",
                            op.id,
                            a.stock_id,
                        )
                    lengths[a.stock_id] = balance
                if op.type == "attach_brace":
                    need_part(a.brace_part_id, op.id)
                    connected = {a.brace_part_id}
                    for _ in a.underlying_joint_ids:
                        for jid in a.underlying_joint_ids:
                            members = set(joints[jid].part_ids)
                            if members & connected:
                                connected.update(members)
                    if not set(joint.part_ids) <= connected:
                        fail(
                            "invalid_reference",
                            "Underlying joints must physically connect every claimed brace attachment.",
                            op.id,
                        )
                    if a.brace_part_id not in joint.part_ids or (
                        not set(a.underlying_joint_ids) <= attached
                        or any(
                            joint_producers.get(jid) not in ancestors[op.id]
                            for jid in a.underlying_joint_ids
                        )
                    ):
                        fail(
                            "invalid_order",
                            "Brace requires its physical supporting joints.",
                            op.id,
                        )
                attached.add(a.joint_id)
                joint_producers[a.joint_id] = op.id
            elif op.type == "detach":
                strategy = profiles[joints[a.joint_id].profile_id].strategy
                inverses = {
                    "tab_slot": ("remove_tab",),
                    "fold_brace": ("remove_brace",),
                    "tape": ("peel_tape",),
                    "tie": ("untie", "cut_cord"),
                }
                if a.supported_inverse not in inverses[strategy]:
                    fail(
                        "unsupported",
                        "Detach inverse is incompatible with the joint strategy.",
                        op.id,
                    )
                if (
                    a.joint_id not in attached
                    or joint_producers.get(a.joint_id) not in ancestors[op.id]
                ):
                    fail("invalid_order", "Cannot detach an unattached joint.", op.id)
                producer = next(
                    (
                        o
                        for o in plan.operations
                        if o.id == joint_producers.get(a.joint_id)
                    ),
                    None,
                )
                if producer is not None and producer.reversible == "irreversible":
                    fail(
                        "irreversible_conflict",
                        "Irreversible joint cannot be detached by a reversible operation.",
                        op.id,
                    )
                if (
                    a.supported_inverse in ("peel_tape", "cut_cord")
                    and not a.material_loss_stock_ids
                ):
                    fail(
                        "stock_exhausted",
                        "Destructive detach requires explicit connector loss accounting.",
                        op.id,
                    )
                attached.discard(a.joint_id)
                if e.detached_joint_ids != (a.joint_id,):
                    fail(
                        "invalid_reference",
                        "Detach effects must identify the removed joint.",
                        op.id,
                    )
        if (
            op.type not in ("insert_tab", "tape_joint", "tie_joint", "attach_brace")
            and e.attached_joint_ids
        ):
            fail("unsupported", "This operation cannot attach a joint.", op.id)
        if op.type != "detach" and e.detached_joint_ids:
            fail("unsupported", "This operation cannot detach a joint.", op.id)
    for part in plan.parts:
        if part.id not in available_parts:
            fail(
                "invalid_order",
                "Every planned part requires a source cut operation.",
                part.id,
            )
    if blockers:
        status = (
            "needs_measurement"
            if any(b.code == "missing_measurement" for b in blockers)
            else "blocked"
        )
        return CompilerResult(status=status, plan=None, blockers=tuple(blockers))
    return CompilerResult(status="accepted", plan=plan, blockers=())
