"""Shared physical component-to-evaluator adapter for all canonical producers."""

import hashlib
from math import sqrt

from forma_domain.stability_contracts import StabilityInput
from forma_stability import evaluate_stability
from forma_stability.stage_math import transform_point


def quantity(value, unit):
    return dict(
        kind="unknown" if value is None else "scalar",
        value=value,
        unit=unit,
        provenance="unknown" if value is None else "assumed",
        confirmed=False,
    )


def solve_components(
    snapshot, policy, groups, parts, active, joint_parts, unknown_poses, digest, version
):
    gravity = snapshot.gravity_world_m_s2
    gv = [gravity.x, gravity.y, gravity.z]
    magnitude = sqrt(sum(v * v for v in gv))
    if magnitude == 0:
        raise ValueError("Stage gravity magnitude must be positive")
    r = snapshot.support_frame.rotation
    local_g = [sum(r[j][i] * gv[j] for j in range(3)) for i in range(3)]
    horizontal = (
        abs(local_g[0]) <= magnitude * 1e-9
        and abs(local_g[1]) <= magnitude * 1e-9
        and local_g[2] < 0
    )
    supplied = {frozenset(c.body_ids): c for c in snapshot.component_loads}
    if len(supplied) != len(snapshot.component_loads) or (
        supplied and set(supplied) != {frozenset(g) for g in groups}
    ):
        raise ValueError(
            "Explicit load cases must cover exactly each separate component once"
        )
    inputs, policies, reports, blockers = [], [], [], []
    if not groups:
        blockers.append("No physical parts have been created at this stage")
    remaining = policy.evaluation_budget
    for index, group in enumerate(groups):
        group_ids = sorted(group)
        bodies, contacts = [], []
        rigid = all(parts[p].rigid_body_assumed for p in group)
        rigid &= all(
            jid in snapshot.rigid_joint_ids
            for jid in active
            if set(joint_parts[jid]) <= group
        )
        for pid in group_ids:
            part = parts[pid]
            center = (
                transform_point(
                    snapshot.support_frame, part.center_of_mass_world, inverse=True
                )
                if part.center_of_mass_world and pid not in unknown_poses
                else None
            )
            bodies.append(
                dict(
                    body_id=pid,
                    source_part_ids=[pid],
                    mass=quantity(part.mass_kg, "kg"),
                    center_of_mass={
                        axis: quantity(getattr(center, axis) if center else None, "m")
                        for axis in ("x", "y", "z")
                    },
                )
            )
            contacts.extend(
                dict(
                    contact_id=c.contact_id,
                    body_id=pid,
                    polygon_world=[
                        transform_point(
                            snapshot.support_frame, p, inverse=True
                        ).model_dump()
                        for p in c.polygon_world
                    ],
                    # Without every source facet pose, surface membership cannot
                    # be validated. Keep the ID for actionable case diagnostics,
                    # but never let this unvalidated contact carry a load/check.
                    active=pid not in unknown_poses,
                    assumption_ids=["explicit-stage-contact"],
                )
                for c in part.contacts
            )
        case = supplied.get(frozenset(group))
        if case is None:
            case = dict(
                case_id=f"component-{index + 1}",
                orientation="Explicit physical stage component",
                body_ids=group_ids,
                contact_ids=[c["contact_id"] for c in contacts],
                gravity_m_s2=quantity(magnitude, "m_s2"),
            )
        else:
            expected_joints = {jid for jid in active if set(joint_parts[jid]) <= group}
            supplied_joints = {j.joint_id for j in case.joint_demands}
            if supplied_joints and supplied_joints != expected_joints:
                raise ValueError(
                    "Joint demand checks must cover exactly the component's active joints"
                )
            case = case.model_dump(mode="python")
            if set(case["contact_ids"]) != {c["contact_id"] for c in contacts}:
                raise ValueError(
                    "Component case must include exactly its stage contacts"
                )
            case["gravity_m_s2"] = quantity(magnitude, "m_s2")
        analysis = StabilityInput.model_validate(
            dict(
                identity=dict(
                    project_id=snapshot.project_id,
                    plan_version_id=snapshot.plan_version_id,
                    inventory_revision=snapshot.inventory_revision,
                    history_cursor=snapshot.history_cursor,
                    operation_state_id=f"stage-component-{index + 1}",
                    canonical_geometry_hash=digest,
                    evidence_hash=hashlib.sha256(b"no-stage-evidence").hexdigest(),
                    profile_hash=digest,
                ),
                geometry_version=version,
                profile_version="explicit-stage-assumptions-v1",
                mechanical_snapshot=dict(
                    bodies=bodies,
                    contacts=contacts,
                    rigid_assembly=rigid,
                    horizontal_support=horizontal,
                    gravity_only=True,
                    state_basis="nominal"
                    if snapshot.basis == "hypothetical"
                    else "observed",
                    assumption_ids=[
                        "explicit-stage-poses",
                        "explicit-stage-contact",
                        "scalar-estimates-not-bounds",
                    ],
                ),
                cases=[case],
            )
        )
        derived = policy.model_copy(
            update=dict(required_case_ids=(case["case_id"],), evaluation_budget=1)
        )
        if remaining <= 0:
            blockers.append(
                f"Stage evaluation budget exhausted before component {index + 1}"
            )
            continue
        remaining -= 1
        inputs.append(analysis)
        policies.append(derived)
        reports.append(evaluate_stability(analysis, derived))
    return tuple(inputs), tuple(policies), tuple(reports), tuple(blockers)
