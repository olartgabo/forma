"""Tape-peel continuation for an attached brace or base of the triangular stand.

Pure offline helper used by ``simulation``. It only stages new work on a
copied plan dictionary: two explicit ``peel_tape`` detach operations for the
two joints holding the replaced part (rear and apex for the brace, front and
rear for the base), a replacement cut from a measured remaining region, an
inspection, and two reattachment tape joints using new joint records.
Historical operations, joints, parts and checkpoints in the copy are left
unchanged except for the not-yet-completed fit/functional-test operations,
which are retargeted to the replacement. The third hinge is never touched
(front for the brace, apex for the base). No tape is refunded: peeled tape is
named as material loss and the compiler/replanner ledgers charge reattachment
separately. Support replacement would undo a completed fold and stays
unsupported.
"""

import copy
from dataclasses import dataclass
from hashlib import sha256

from forma_domain.models import Blocker

ORIGINAL_PARTS = ("stand-support", "stand-base", "stand-brace")
ORIGINAL_JOINTS = (
    "stand-joint-front",
    "stand-joint-rear",
    "stand-joint-apex",
)
CORE_TYPES = (
    "cut_rect",
    "inspect",
    "fold",
    "tape_joint",
    "tape_joint",
    "tape_joint",
    "inspect",
    "functional_test",
)


@dataclass(frozen=True)
class TapeRole:
    name: str
    # (joint id, original tape op id, partner part id, short name), peel order
    touching: tuple[tuple[str, str, str, str], ...]
    # Completed work that proves the part is attached on both touching joints.
    required_completed: tuple[str, ...]
    # Extra prerequisites of the first peel, so the untouched joint's attach
    # is an ancestor of the new functional test that requires it.
    peel_after: tuple[str, ...] = ()


TAPE_ROLES = {
    "stand-brace": TapeRole(
        "brace",
        (
            ("stand-joint-rear", "stand-joint-rear-attach", "stand-base", "rear"),
            ("stand-joint-apex", "stand-joint-apex-attach", "stand-support", "apex"),
        ),
        ("stand-fold-lip", "stand-joint-rear-attach", "stand-joint-apex-attach"),
    ),
    "stand-base": TapeRole(
        "base",
        (
            ("stand-joint-front", "stand-joint-front-attach", "stand-support", "front"),
            ("stand-joint-rear", "stand-joint-rear-attach", "stand-brace", "rear"),
        ),
        (
            "stand-fold-lip",
            "stand-joint-front-attach",
            "stand-joint-rear-attach",
            "stand-joint-apex-attach",
        ),
        peel_after=("stand-joint-apex-attach",),
    ),
}


def peel_human_checks(joint_id, partner_id):
    """Explicit human confirmations required before peeling one joint."""
    return (
        f"Remove the device and support the stand so {joint_id} is not load-bearing before peeling.",
        f"Confirm access to {joint_id} and confirm {partner_id} can be supported while peeling.",
        f"Peel the tape slowly; confirm the undamaged partner part {partner_id} is intact after peeling.",
        "Old tape is lost when peeled and is not reused or refunded.",
    )


def build_tape_undo_candidate(data, base, patch, completed, remaining, process):
    """Stage a tape-undo candidate in the copied plan dict ``data``.

    Returns ``(handled, blocker, peel_operation_ids, peeled_operation_ids)``.
    ``handled`` is False when this is not the canonical attached-brace case
    and the generic replacement path should decide the outcome.
    """
    role = TAPE_ROLES.get(patch.target_id)
    if patch.kind != "replace_part" or role is None:
        return False, None, (), ()
    target = patch.target_id
    touching = role.touching
    if base.compiler_version != "triangular-tape-stand-v1":
        return False, None, (), ()
    parts = {p.id: p for p in base.parts}
    joints = {j.id: j for j in base.joints}
    operations = {o.id: o for o in base.operations}
    if (
        set(parts) != set(ORIGINAL_PARTS)
        or set(joints) != set(ORIGINAL_JOINTS)
        or tuple(o.type for o in base.operations) != CORE_TYPES
    ):
        return False, None, (), ()
    expected_joints = {
        "stand-joint-front": ("stand-support", "stand-base"),
        "stand-joint-rear": ("stand-base", "stand-brace"),
        "stand-joint-apex": ("stand-support", "stand-brace"),
    }
    if any(joints[jid].part_ids != pair for jid, pair in expected_joints.items()):
        return False, None, (), ()
    creator = operations.get("stand-cut-panels")
    if creator is None or tuple(creator.args.child_part_ids) != ORIGINAL_PARTS:
        return False, None, (), ()

    def blocked(code, message, *ids):
        return True, Blocker(code=code, message=message, target_ids=ids), (), ()

    # The part must already be attached: fold and both touching tape
    # joints completed. Reversibility of the touching work controls
    # admissibility; an irreversible touching operation cannot be peeled.
    missing = [oid for oid in role.required_completed if oid not in completed]
    if creator.id not in completed or missing:
        return False, None, (), ()
    completed_final_checks = tuple(
        oid
        for oid in ("stand-inspect-fit", "stand-functional-test")
        if oid in completed
    )
    fit_completed = "stand-inspect-fit" in completed
    test_completed = "stand-functional-test" in completed
    seven_build = fit_completed and not test_completed
    if test_completed and not fit_completed:
        return blocked(
            "unsupported",
            "Tape-undo replacement does not support a completed "
            "stand-inspect-fit or stand-functional-test operation; "
            "completed final checks cannot be retargeted to the "
            f"replacement {role.name}.",
            *completed_final_checks,
        )
    # Resolve each original final checkpoint by the operation's own
    # checkpoint reference, before staging any candidate mutation.
    original_final_checkpoints = {}
    if fit_completed:
        for old_op_id in ("stand-inspect-fit", "stand-functional-test"):
            referenced_id = operations[old_op_id].args.checkpoint_id
            matches = [c for c in base.checkpoints if c.id == referenced_id]
            if len(matches) != 1 or matches[0].after_operation_id != old_op_id:
                return blocked(
                    "invalid_reference",
                    "Tape-undo replacement requires the checkpoint referenced "
                    f"by {old_op_id} to exist exactly once and follow that "
                    "operation; the original final checkpoint is absent or "
                    "mismatched.",
                    old_op_id,
                    referenced_id,
                )
            original_final_checkpoints[old_op_id] = matches[0]
    for joint_id, op_id, _partner, _name in touching:
        op = operations[op_id]
        if op.reversible == "irreversible":
            return blocked(
                "irreversible_conflict",
                "A completed touching tape joint is irreversible and cannot be peeled.",
                op_id,
            )
        if joints[joint_id].confirmed_accessible is not True:
            return blocked(
                "needs_confirmation",
                "Confirm scoped access to the touching tape joint before peeling.",
                joint_id,
            )
    if process is None:
        return blocked(
            "unsupported_profile",
            "Replacement cut requires a measured cutting process.",
        )
    original = parts[target]
    margin = max(process.edge_margin_min_mm, creator.args.edge_margin_mm)
    kerf = max(process.kerf_min_mm, creator.args.kerf_mm)
    source_stock = remaining.get(patch.replacement_stock_id)
    source = next(
        (
            r
            for r in (source_stock.usable_regions if source_stock else ())
            if r.geometry.width >= original.geometry.width + 2 * margin
            and r.geometry.height >= original.geometry.height + 2 * margin
        ),
        None,
    )
    if source is None:
        return blocked(
            "stock_exhausted",
            f"No actual remaining region fits the replacement {role.name} and measured margins.",
            patch.replacement_stock_id,
        )
    tape_ids = {operations[op_id].args.stock_id for _j, op_id, _p, _n in touching}
    if len(tape_ids) != 1:
        return blocked(
            "unsupported",
            "Touching tape joints must use one original tape stock.",
            *(op for _j, op, _p, _n in touching),
        )
    tape_id = next(iter(tape_ids))

    token = sha256(patch.model_dump_json().encode()).hexdigest()[:10]
    new_pid = f"replacement_{token}"
    new_cut = f"replacement_cut_{token}"
    inspect_id = f"replacement_inspect_{token}"
    checkpoint_id = f"{inspect_id}-check"
    peel_ids = tuple(f"peel_tape_{token}_{name}" for _j, _o, _p, name in touching)
    new_joint_ids = tuple(
        f"{joint_id}-replacement-{token}" for joint_id, _o, _p, _n in touching
    )
    reattach_ids = tuple(f"{joint_id}-attach" for joint_id in new_joint_ids)
    new_fit_id = f"replacement_inspect_fit_{token}"
    new_test_id = f"replacement_functional_test_{token}"
    active = tuple(new_pid if pid == target else pid for pid in ORIGINAL_PARTS)
    new_joint_by_original = {
        joint_id: new_joint_id
        for (joint_id, _o, _p, _n), new_joint_id in zip(
            touching, new_joint_ids, strict=True
        )
    }
    required_joints = tuple(
        new_joint_by_original.get(jid, jid) for jid in ORIGINAL_JOINTS
    )

    new_part = original.model_dump(mode="python")
    new_part.update(
        id=new_pid,
        source_stock_id=patch.replacement_stock_id,
        source_region_id=source.id,
        condition="usable",
    )
    new_part["geometry"].update(
        x=source.geometry.x + margin, y=source.geometry.y + margin
    )
    data["parts"] = (*data["parts"], new_part)
    new_pairs = {}
    for (joint_id, _op, _partner, _name), new_joint_id in zip(
        touching, new_joint_ids, strict=True
    ):
        joint = joints[joint_id]
        # Keep the original part order with the replacement in the retired slot.
        new_pairs[new_joint_id] = tuple(
            new_pid if pid == target else pid for pid in joint.part_ids
        )
        data["joints"] = (
            *data["joints"],
            {
                "id": new_joint_id,
                "profile_id": joint.profile_id,
                "part_ids": new_pairs[new_joint_id],
                "interface_feature_ids": (),
                "confirmed_accessible": True,
            },
        )
    data["checkpoints"] = (
        *data["checkpoints"],
        {
            "id": checkpoint_id,
            "after_operation_id": inspect_id,
            "method": "ruler",
            "description": (
                f"Measure the replacement {role.name} against the retired {role.name} "
                "dimensions and confirm its edges are undamaged before taping."
            ),
            "invalidated_by": (),
        },
    )
    if fit_completed:
        for old_op_id, new_op_id in (
            ("stand-inspect-fit", new_fit_id),
            ("stand-functional-test", new_test_id),
        ):
            cloned = copy.deepcopy(
                original_final_checkpoints[old_op_id].model_dump(mode="python")
            )
            cloned.update(
                id=f"{new_op_id}-check",
                after_operation_id=new_op_id,
                invalidated_by=(),
            )
            if seven_build and old_op_id == "stand-functional-test":
                # The unfinished test is renamed, so its checkpoint is
                # retargeted rather than left pointing at the old operation.
                original_id = original_final_checkpoints[old_op_id].id
                data["checkpoints"] = tuple(
                    cloned if c["id"] == original_id else c for c in data["checkpoints"]
                )
            else:
                data["checkpoints"] = (*data["checkpoints"], cloned)

    new_ops = []
    for (joint_id, op_id, partner, _name), peel_id in zip(
        touching, peel_ids, strict=True
    ):
        depends = (
            (op_id, *role.peel_after)
            if peel_id == peel_ids[0]
            else (peel_ids[0], op_id)
        )
        new_ops.append(
            {
                "id": peel_id,
                "type": "detach",
                "part_ids": joints[joint_id].part_ids,
                "stock_ids": (tape_id,),
                "depends_on": depends,
                "expected_state_id": f"state_{peel_id}",
                "requires_user_confirmation": True,
                "preconditions": {
                    "accessible_part_ids": joints[joint_id].part_ids,
                    "human_checks": peel_human_checks(joint_id, partner),
                },
                "effects": {"detached_joint_ids": (joint_id,)},
                "args": {
                    "joint_id": joint_id,
                    "supported_inverse": "peel_tape",
                    "material_loss_stock_ids": (tape_id,),
                },
                "reversible": "lossy",
            }
        )
    source_producer = next(
        (
            o.id
            for o in base.operations
            if any(r.id == source.id for r in o.effects.created_offcuts)
        ),
        None,
    )
    cut_depends = (peel_ids[-1],) + ((source_producer,) if source_producer else ())
    new_ops.append(
        {
            "id": new_cut,
            "type": "cut_rect",
            "part_ids": (),
            "stock_ids": (patch.replacement_stock_id,),
            "depends_on": cut_depends,
            "expected_state_id": f"state_{new_cut}",
            "requires_user_confirmation": True,
            "preconditions": {
                "safe_tools_confirmed": creator.preconditions.safe_tools_confirmed,
                "human_checks": (
                    "Confirm replacement dimensions and cutting tools before the new cut.",
                ),
            },
            "effects": {
                "created_part_ids": (new_pid,),
                "consumed_region_ids": (source.id,),
            },
            "args": {
                "stock_id": patch.replacement_stock_id,
                "source_region_id": source.id,
                "child_part_ids": (new_pid,),
                "kerf_mm": kerf,
                "edge_margin_mm": margin,
            },
        }
    )
    new_ops.append(
        {
            "id": inspect_id,
            "type": "inspect",
            "part_ids": (new_pid,),
            "stock_ids": (),
            "depends_on": (new_cut,),
            "expected_state_id": f"state_{inspect_id}",
            "requires_user_confirmation": True,
            "preconditions": {
                "accessible_part_ids": (new_pid,),
                "human_checks": (
                    f"Confirm the replacement {role.name} is undamaged and matches the retired {role.name} dimensions.",
                ),
            },
            "effects": {},
            "args": {
                "target_ids": (new_pid,),
                "checkpoint_id": checkpoint_id,
                "method": "ruler",
            },
        }
    )
    width = parts["stand-support"].geometry.width
    for (_joint_id, _op, partner, _name), new_joint_id, reattach_id in zip(
        touching, new_joint_ids, reattach_ids, strict=True
    ):
        new_ops.append(
            {
                "id": reattach_id,
                "type": "tape_joint",
                "part_ids": new_pairs[new_joint_id],
                "stock_ids": (tape_id,),
                "depends_on": (
                    (inspect_id,)
                    if reattach_id == reattach_ids[0]
                    else (reattach_ids[0],)
                ),
                "expected_state_id": f"state_{reattach_id}",
                "requires_user_confirmation": True,
                "preconditions": {
                    "accessible_part_ids": new_pairs[new_joint_id],
                    "human_checks": (
                        f"Confirm access to {new_joint_id}; verify tape overlap on each face, the undamaged partner part {partner} and actual grip by hand.",
                    ),
                },
                "effects": {"attached_joint_ids": (new_joint_id,)},
                "args": {
                    "joint_id": new_joint_id,
                    "stock_id": tape_id,
                    "length_mm": width,
                },
                "reversible": "lossy",
            }
        )

    operations_data = list(data["operations"])
    if fit_completed:
        by_id = {op["id"]: op for op in operations_data}
        fit = copy.deepcopy(by_id["stand-inspect-fit"])
        fit.update(
            id=new_fit_id,
            part_ids=active,
            depends_on=(reattach_ids[-1],),
            expected_state_id=f"state_{new_fit_id}",
        )
        fit["preconditions"]["accessible_part_ids"] = active
        fit["args"].update(target_ids=active, checkpoint_id=f"{new_fit_id}-check")
        test = copy.deepcopy(by_id["stand-functional-test"])
        test.update(
            id=new_test_id,
            part_ids=active,
            depends_on=(new_fit_id,),
            expected_state_id=f"state_{new_test_id}",
        )
        test["preconditions"]["accessible_part_ids"] = ()
        test["preconditions"]["required_joint_ids"] = required_joints
        test["args"]["checkpoint_id"] = f"{new_test_id}-check"
        new_ops = [*new_ops, fit, test]
        if seven_build:
            # Keep the seven historical operations exactly; the unfinished
            # functional test is renamed/retargeted as the new final test.
            historical = [
                op for op in operations_data if op["id"] != "stand-functional-test"
            ]
            data["operations"] = tuple(historical + new_ops)
        else:
            data["operations"] = tuple(operations_data + new_ops)
    else:
        for op in operations_data:
            if op["id"] == "stand-inspect-fit":
                op["part_ids"] = active
                op["depends_on"] = (reattach_ids[-1],)
                op["preconditions"]["accessible_part_ids"] = active
                op["args"]["target_ids"] = active
            elif op["id"] == "stand-functional-test":
                op["part_ids"] = active
                op["preconditions"]["accessible_part_ids"] = ()
                op["preconditions"]["required_joint_ids"] = required_joints
        insert_at = (
            next(
                i
                for i, o in enumerate(operations_data)
                if o["id"] == "stand-joint-apex-attach"
            )
            + 1
        )
        data["operations"] = tuple(
            operations_data[:insert_at] + new_ops + operations_data[insert_at:]
        )
    peeled = tuple(op for _j, op, _p, _n in touching)
    return True, None, peel_ids, peeled
