"""Pure continuation checks for the stand template with replacement parts.

This validator accepts the original stand plan and plans in which an active
role part has been replaced by a newly cut part, while the retired original
remains in ``plan.parts``. Historical immutability is checked by the replanner;
this single-plan validator checks presence and replacement equivalence only.
It never mutates the plan.
"""

from math import cos, hypot, radians, sin

from forma_domain import models as m

_ORIGINALS = ("stand-support", "stand-base", "stand-brace")
_JOINT_IDS = ("stand-joint-front", "stand-joint-rear", "stand-joint-apex")
_CORE_TYPES = (
    "cut_rect",
    "inspect",
    "fold",
    "tape_joint",
    "tape_joint",
    "tape_joint",
    "inspect",
    "functional_test",
)


def _add(blockers, seen, code, message, target_ids=()):
    key = (code, message, tuple(target_ids))
    if key not in seen:
        seen.add(key)
        blockers.append(
            m.Blocker(code=code, message=message, target_ids=tuple(target_ids))
        )


def stand_continuation_blockers(plan: m.BuildPlan) -> tuple[m.Blocker, ...]:
    """Return blockers for a stand plan that cannot continue the template."""
    blockers: list[m.Blocker] = []
    seen = set()

    def add(code, message, target_ids=()):
        _add(blockers, seen, code, message, target_ids)

    parts = {p.id: p for p in plan.parts}
    joints = {j.id: j for j in plan.joints}

    # --- Resolve active roles from the exact joints. ---
    if set(joints) != set(_JOINT_IDS):
        add(
            "unsupported",
            "Stand continuation requires exactly the joints "
            "stand-joint-front, stand-joint-rear and stand-joint-apex.",
            tuple(sorted(set(joints) ^ set(_JOINT_IDS))),
        )
        return tuple(blockers)
    for joint_id in _JOINT_IDS:
        pair = joints[joint_id].part_ids
        if len(pair) != 2 or pair[0] == pair[1]:
            add(
                "unsupported",
                f"Joint {joint_id} must reference exactly two distinct parts.",
                (joint_id,),
            )
    if blockers:
        return tuple(blockers)

    front = set(joints["stand-joint-front"].part_ids)
    rear = set(joints["stand-joint-rear"].part_ids)
    apex = set(joints["stand-joint-apex"].part_ids)
    intersections = {
        "support": front & apex,
        "base": front & rear,
        "brace": rear & apex,
    }
    if any(len(ids) != 1 for ids in intersections.values()):
        add(
            "unsupported",
            "Stand joints must intersect in singleton support, base and brace roles.",
            _JOINT_IDS,
        )
        return tuple(blockers)
    active_ids = {role: next(iter(ids)) for role, ids in intersections.items()}
    if len(set(active_ids.values())) != 3:
        add(
            "unsupported",
            "Stand support, base and brace roles must be three distinct parts.",
            tuple(active_ids.values()),
        )
        return tuple(blockers)

    ordered_topology = {
        "stand-joint-front": (active_ids["support"], active_ids["base"]),
        "stand-joint-rear": (active_ids["base"], active_ids["brace"]),
        "stand-joint-apex": (active_ids["support"], active_ids["brace"]),
    }
    for joint_id, expected in ordered_topology.items():
        if joints[joint_id].part_ids != expected:
            add(
                "unsupported",
                f"Joint {joint_id} must have ordered part_ids {expected}.",
                (joint_id,),
            )
    for role, part_id in active_ids.items():
        if part_id not in parts:
            add(
                "invalid_reference",
                f"Active {role} part {part_id} is not present in plan parts.",
                (part_id,),
            )
    if blockers:
        return tuple(blockers)

    support_part = parts[active_ids["support"]]
    base_part = parts[active_ids["base"]]
    brace_part = parts[active_ids["brace"]]
    active_ordered = (support_part.id, base_part.id, brace_part.id)
    original_role = {
        "support": "stand-support",
        "base": "stand-base",
        "brace": "stand-brace",
    }
    retired_ids = tuple(
        original_role[role]
        for role in ("support", "base", "brace")
        if active_ids[role] != original_role[role]
    )
    for original_id in _ORIGINALS:
        if original_id not in parts:
            add(
                "invalid_reference",
                f"Historical stand part {original_id} is missing from plan parts.",
                (original_id,),
            )
    if blockers:
        return tuple(blockers)

    # --- Geometry of the active roles. ---
    feature = None
    support = lip = None
    if len(support_part.features) != 1:
        add(
            "unsupported",
            "Active support part must have exactly one fold feature.",
            (support_part.id,),
        )
    else:
        feature = support_part.features[0]
        if feature.kind != "fold":
            add(
                "unsupported",
                "Active support feature must be a fold feature.",
                (feature.id,),
            )
            feature = None
    if feature is not None:
        support = feature.geometry.y
        lip = support_part.geometry.height - support
        if support <= 0 or lip <= 0:
            add(
                "geometry_invalid",
                "Support fold must leave positive support and lip heights.",
                (support_part.id, feature.id),
            )
        if (
            feature.geometry.x != 0
            or feature.geometry.width != support_part.geometry.width
            or abs(feature.geometry.height - lip) > 1e-7
        ):
            add(
                "geometry_invalid",
                "Support fold feature must span the part width at x=0 "
                "with height equal to the lip height.",
                (support_part.id, feature.id),
            )
    for role_part, role in ((base_part, "base"), (brace_part, "brace")):
        if role_part.features:
            add(
                "unsupported",
                f"Active {role} part must have no features.",
                (role_part.id,),
            )
    if any(
        p.geometry.width != support_part.geometry.width for p in (base_part, brace_part)
    ):
        add(
            "geometry_invalid",
            "Stand support, base and brace parts must have equal widths.",
            active_ordered,
        )

    angle_m = plan.constraints.support_angle_deg
    depth = base_part.geometry.height
    if angle_m.value is None or not angle_m.confirmed or not 0 < angle_m.value < 90:
        add(
            "geometry_invalid",
            "Support angle must be confirmed and strictly between 0 and 90 degrees.",
            (support_part.id,),
        )
    elif support is not None:
        angle = radians(angle_m.value)
        reach = support * cos(angle)
        rise = support * sin(angle)
        if depth <= reach:
            add(
                "geometry_invalid",
                "Base depth must exceed the horizontal reach of the support.",
                (base_part.id, support_part.id),
            )
        expected_brace = hypot(depth - reach, rise)
        if abs(brace_part.geometry.height - expected_brace) > 1e-6:
            add(
                "geometry_invalid",
                "Brace height must equal hypot(depth - reach, rise) "
                "for the confirmed support angle.",
                (brace_part.id,),
            )

    # --- Operations: exactly eight core ops plus replacement cuts. ---
    operations = list(plan.operations)
    core_cut_candidates = [
        o
        for o in operations
        if o.type == "cut_rect" and tuple(o.args.child_part_ids) == _ORIGINALS
    ]
    if len(core_cut_candidates) != 1:
        add(
            "unsupported",
            "Stand continuation requires exactly one core cut producing "
            "stand-support, stand-base and stand-brace.",
            tuple(o.id for o in core_cut_candidates),
        )
        core_cut = None
    else:
        core_cut = core_cut_candidates[0]

    if core_cut is not None:
        core_cut_index = next(
            i for i, o in enumerate(operations) if o.id == core_cut.id
        )
    else:
        core_cut_index = None
    supplemental_indexes = {
        i
        for i, o in enumerate(operations)
        if o.type == "cut_rect" and i != core_cut_index
    }
    core_ops = [o for i, o in enumerate(operations) if i not in supplemental_indexes]

    if tuple(o.type for o in core_ops) != _CORE_TYPES:
        add(
            "unsupported",
            "Core operations must be exactly cut_rect, inspect, fold, "
            "tape_joint, tape_joint, tape_joint, inspect, functional_test.",
            tuple(o.id for o in core_ops),
        )

    # Supplemental cuts: single active replacements, before their consumers.
    produced_by: dict[str, str] = {}
    if core_cut is not None:
        for child in core_cut.args.child_part_ids:
            produced_by[child] = core_cut.id
    replacement_children: set[str] = set()
    for i in sorted(supplemental_indexes):
        op = operations[i]
        children = tuple(op.args.child_part_ids)
        if len(children) != 1:
            add(
                "unsupported",
                "Supplemental replacement cut must produce exactly one part.",
                (op.id,),
            )
            continue
        child = children[0]
        replacement_children.add(child)
        if child not in parts:
            add(
                "invalid_reference",
                f"Supplemental cut produces unknown part {child}.",
                (op.id, child),
            )
            continue
        if child in _ORIGINALS or child not in active_ids.values():
            add(
                "invalid_reference",
                f"Supplemental cut part {child} is not an active replacement part.",
                (op.id, child),
            )
            continue
        if child in produced_by:
            add(
                "invalid_reference",
                f"Part {child} is produced by more than one cut.",
                (op.id, child),
            )
        produced_by[child] = op.id
        consumers = [
            j
            for j, other in enumerate(operations)
            if j not in supplemental_indexes
            and j != core_cut_index
            and (
                child in other.part_ids
                or child in getattr(other.args, "target_ids", ())
                or getattr(other.args, "part_id", None) == child
            )
        ]
        if consumers and i > min(consumers):
            add(
                "unsupported",
                f"Supplemental cut for replacement part {child} must occur "
                "before the first core operation that uses it.",
                (op.id, child),
            )

    # Active replacements must match their retired original and be cut.
    for role in ("support", "base", "brace"):
        active_id = active_ids[role]
        if active_id in _ORIGINALS:
            continue
        retired = parts[original_role[role]]
        active = parts[active_id]
        if active_id not in replacement_children:
            add(
                "invalid_reference",
                f"Active replacement {role} part {active_id} has no "
                "supplemental replacement cut.",
                (active_id,),
            )
        if (
            active.geometry.width != retired.geometry.width
            or active.geometry.height != retired.geometry.height
        ):
            add(
                "geometry_invalid",
                f"Active replacement {role} part must have the same width "
                "and height as its retired original.",
                (active_id, retired.id),
            )
        active_feats = [(f.kind, f.geometry) for f in active.features]
        retired_feats = [(f.kind, f.geometry) for f in retired.features]
        if active_feats != retired_feats:
            add(
                "geometry_invalid",
                f"Active replacement {role} part must have the same features "
                "as its retired original, apart from feature ID.",
                (active_id, retired.id),
            )

    # Every plan part is accounted for by the core or a supplemental cut.
    for part_id in parts:
        if part_id not in produced_by:
            add(
                "invalid_reference",
                f"Plan part {part_id} is not produced by any stand cut.",
                (part_id,),
            )
    for child, op_id in produced_by.items():
        if child not in parts:
            add(
                "invalid_reference",
                f"Cut {op_id} produces part {child} missing from plan parts.",
                (op_id, child),
            )
    extra_parts = set(parts) - set(_ORIGINALS)
    for part_id in sorted(extra_parts):
        if part_id not in active_ids.values():
            add(
                "invalid_reference",
                f"Extra plan part {part_id} is not an active replacement part.",
                (part_id,),
            )

    # --- Non-cut core operations must use the active role IDs. ---
    if tuple(o.type for o in core_ops) == _CORE_TYPES:
        inspect_cuts, fold_op = core_ops[1], core_ops[2]
        tape_ops = core_ops[3:6]
        inspect_fit, test_op = core_ops[6], core_ops[7]

        for op in (inspect_cuts, inspect_fit):
            if op.part_ids != active_ordered:
                add(
                    "invalid_reference",
                    f"Operation {op.id} must reference the active stand parts.",
                    (op.id,),
                )
            if tuple(op.args.target_ids) != active_ordered:
                add(
                    "invalid_reference",
                    f"Inspect operation {op.id} must target the active stand parts.",
                    (op.id,),
                )
        if fold_op.part_ids != (support_part.id,):
            add(
                "invalid_reference",
                "Fold operation must reference only the active support part.",
                (fold_op.id,),
            )
        if feature is not None and support is not None:
            fold = fold_op.args
            if (
                fold.part_id != support_part.id
                or fold.feature_id != feature.id
                or fold.start_x_mm != 0
                or fold.end_x_mm != support_part.geometry.width
                or fold.start_y_mm != support
                or fold.end_y_mm != support
                or fold.angle_deg != 90
                or fold.direction != "valley"
                or fold.reachable_face != "front"
            ):
                add(
                    "geometry_invalid",
                    "Fold operation arguments must match the active support "
                    "fold feature.",
                    (fold_op.id, feature.id),
                )
        expected_joints = list(_JOINT_IDS)
        for op, joint_id in zip(tape_ops, expected_joints, strict=True):
            if op.args.joint_id != joint_id:
                add(
                    "invalid_reference",
                    f"Tape operation {op.id} must attach joint {joint_id}.",
                    (op.id, joint_id),
                )
            if op.part_ids != ordered_topology[joint_id]:
                add(
                    "invalid_reference",
                    f"Tape operation {op.id} must reference the ordered parts "
                    f"of joint {joint_id}.",
                    (op.id, joint_id),
                )
            if op.args.length_mm != support_part.geometry.width:
                add(
                    "geometry_invalid",
                    f"Tape operation {op.id} length must equal the stand width.",
                    (op.id,),
                )
        if test_op.part_ids != active_ordered:
            add(
                "invalid_reference",
                "Functional test must reference the active stand parts.",
                (test_op.id,),
            )

        for op in (inspect_cuts, inspect_fit, test_op):
            if not any(
                c.after_operation_id == op.id and c.id == op.args.checkpoint_id
                for c in plan.checkpoints
            ):
                add(
                    "invalid_reference",
                    f"Operation {op.id} has no matching checkpoint.",
                    (op.id, op.args.checkpoint_id),
                )
        mass = plan.constraints.device_mass_g
        if (
            test_op.args.mass_g is None
            or mass.value is None
            or not mass.confirmed
            or test_op.args.mass_g != mass.value
        ):
            add(
                "geometry_invalid",
                "Functional test mass must equal the confirmed device mass constraint.",
                (test_op.id,),
            )

    # No operation may reference retired parts, especially via accessibility.
    retired = set(retired_ids)
    if retired:
        for op in operations:
            refs: set[str] = set(op.part_ids)
            refs.update(op.preconditions.accessible_part_ids)
            refs.update(getattr(op.args, "target_ids", ()) or ())
            if getattr(op.args, "part_id", None):
                refs.add(op.args.part_id)
            bad = sorted(refs & retired)
            if bad:
                add(
                    "invalid_reference",
                    f"Operation {op.id} references retired part(s) "
                    f"{', '.join(bad)}; active replacement parts must be used.",
                    (op.id, *bad),
                )
    else:
        for op in operations:
            unknown = [
                pid for pid in op.preconditions.accessible_part_ids if pid not in parts
            ]
            if unknown:
                add(
                    "invalid_reference",
                    f"Operation {op.id} lists unknown accessible part(s).",
                    (op.id, *unknown),
                )

    return tuple(blockers)


__all__ = ["stand_continuation_blockers"]
