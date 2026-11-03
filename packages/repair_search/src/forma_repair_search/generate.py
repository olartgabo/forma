"""Enumerate repair candidates from operators FORMA already supports.

Only flat RepairPatch edits are produced: replacing a target part from remaining
sheet stock, resizing it to a size the user measured, or swapping a joint to
another allowed tested profile. Angle changes would need an invented angle and
are not generated. The simulator, not this module, decides what is feasible.
"""

import hashlib
import json

from forma_domain.models import BuildPlan, RepairPatch, Stock
from forma_domain.repair_search_contracts import ResizeMeasurement


def _patch(base_version_id: str, kind: str, target_id: str, rationale: str, **values):
    fields = dict(
        replacement_stock_id=None,
        replacement_profile_id=None,
        width_mm=None,
        height_mm=None,
        angle_deg=None,
    )
    fields.update(values)
    digest = hashlib.sha256(
        json.dumps([base_version_id, kind, target_id, fields], sort_keys=True).encode()
    ).hexdigest()[:16]
    return RepairPatch(
        id=f"search-{kind.replace('_', '-')}-{digest}",
        base_version_id=base_version_id,
        kind=kind,
        target_id=target_id,
        rationale=rationale,
        **fields,
    )


def generate_candidates(
    plan: BuildPlan,
    target_ids: tuple[str, ...],
    remaining_stock: tuple[Stock, ...],
    resizes: tuple[ResizeMeasurement, ...] = (),
) -> tuple[RepairPatch, ...]:
    """Deterministic candidates in target order, then stock or profile ID order."""
    parts = {p.id for p in plan.parts}
    joints = {j.id: j for j in plan.joints}
    profiles = sorted(
        p.id
        for p in plan.joint_profiles
        if p.status == "tested" and p.id in plan.constraints.allowed_profile_ids
    )
    sheets = sorted(
        s.id
        for s in remaining_stock
        if s.kind in ("sheet", "strip") and s.condition == "usable" and s.usable_regions
    )
    found: dict[str, RepairPatch] = {}

    def add(patch: RepairPatch) -> None:
        found.setdefault(patch.id, patch)

    for target in target_ids:
        joint_targets = []
        if target in parts:
            for stock_id in sheets:
                add(
                    _patch(
                        plan.version_id,
                        "replace_part",
                        target,
                        f"Search: cut a replacement {target} from {stock_id}.",
                        replacement_stock_id=stock_id,
                    )
                )
            for size in resizes:
                if size.part_id == target:
                    add(
                        _patch(
                            plan.version_id,
                            "resize_part",
                            target,
                            f"Search: resize {target} to the measured "
                            f"{size.width_mm:g} x {size.height_mm:g} mm.",
                            width_mm=size.width_mm,
                            height_mm=size.height_mm,
                        )
                    )
            joint_targets = sorted(j for j in joints if target in joints[j].part_ids)
        elif target in joints:
            joint_targets = [target]
        for joint_id in joint_targets:
            for profile_id in profiles:
                if profile_id != joints[joint_id].profile_id:
                    add(
                        _patch(
                            plan.version_id,
                            "replace_joint_profile",
                            joint_id,
                            f"Search: join {joint_id} with tested profile {profile_id}.",
                            replacement_profile_id=profile_id,
                        )
                    )
    return tuple(found.values())
