"""Canonical physical stage projection with one support hull per rigid component."""

import hashlib
import json
from math import sqrt

from shapely.geometry import Point, Polygon

from forma_domain.models import BuildPlan
from forma_domain.stability_contracts import AnalysisPolicy, Point3, StabilityInput
from forma_domain.stage_mechanics import StageAnalysisResult, StageSnapshot
from forma_stability import evaluate_stability
from forma_stability.geometry import project_nominal_geometry

VERSION = "explicit-stage-v1"


def transform_point(transform, point, *, inverse=False):
    p = [point.x, point.y, point.z]
    t = transform.translation_m
    offset = [t.x, t.y, t.z]
    r = transform.rotation
    values = (
        [sum(r[j][i] * (p[j] - offset[j]) for j in range(3)) for i in range(3)]
        if inverse
        else [sum(r[i][j] * p[j] for j in range(3)) + offset[i] for i in range(3)]
    )
    return Point3(x=values[0], y=values[1], z=values[2])


def _q(value, unit):
    return dict(
        kind="unknown" if value is None else "scalar",
        value=value,
        unit=unit,
        provenance="unknown" if value is None else "assumed",
        confirmed=False,
    )


def flat_parts_example(plan: BuildPlan, completed_prefix: int = 1) -> StageSnapshot:
    """Explicit opt-in invented cut panels lying separately on a horizontal table.

    This is never inferred from cutting layout or represented as observed work.
    Facet transforms flatten the not-yet-folded lip while conserving source mass.
    """
    if completed_prefix not in (1, 2):
        raise ValueError(
            "The separated flat-panel example supports only stages 1 and 2"
        )
    reference = project_nominal_geometry(plan)
    parts = []
    offset_x = 0.0
    for part in plan.parts:
        width, height = part.geometry.width / 1000, part.geometry.height / 1000
        poses = []
        for facet in reference.facets:
            if facet.part_id != part.id:
                continue
            a, b, _, d = facet.vertices
            u = [b.x - a.x, b.y - a.y, b.z - a.z]
            v = [d.x - a.x, d.y - a.y, d.z - a.z]
            u = [x / sqrt(sum(t * t for t in u)) for x in u]
            v = [x / sqrt(sum(t * t for t in v)) for x in v]
            ystart = 0.0
            if part.id == "stand-support":
                lip = height - part.features[0].geometry.y / 1000
                ystart = lip
                if facet.feature_id:
                    v = [-x for x in v]
            n = [
                u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0],
            ]
            rotation = [u, v, n]
            av = [a.x, a.y, a.z]
            target = [offset_x - width / 2, ystart, 0.0]
            translation = [
                target[i] - sum(rotation[i][j] * av[j] for j in range(3))
                for i in range(3)
            ]
            poses.append(
                dict(
                    facet_id=facet.facet_id,
                    transform=dict(
                        rotation=rotation,
                        translation_m=dict(zip(("x", "y", "z"), translation)),
                    ),
                )
            )
        parts.append(
            dict(
                part_id=part.id,
                mass_kg=0.02,
                center_of_mass_world=dict(x=offset_x, y=height / 2, z=0.0),
                facet_poses=poses,
                contacts=[
                    dict(
                        contact_id=f"contact-{part.id}",
                        polygon_world=[
                            dict(x=offset_x + x, y=y, z=0.0)
                            for x, y in (
                                (-width / 2, 0),
                                (width / 2, 0),
                                (width / 2, height),
                                (-width / 2, height),
                            )
                        ],
                    )
                ],
                rigid_body_assumed=True,
            )
        )
        offset_x += width + 0.05
    return StageSnapshot.model_validate(
        dict(
            project_id=plan.project_id,
            plan_version_id=plan.version_id,
            inventory_revision="lab-not-inventory",
            history_cursor=None,
            completed_operation_ids=[o.id for o in plan.operations[:completed_prefix]],
            basis="hypothetical",
            support_frame=dict(
                rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                translation_m=dict(x=0.0, y=0.0, z=0.0),
            ),
            gravity_world_m_s2=dict(x=0.0, y=0.0, z=-9.81),
            parts=parts,
            rigid_joint_ids=[],
            assumption_notes=[
                "INVENTED diagnostic example: cut panels laid separately flat; 20g per source part, uniform distribution and full-face table contact. No physical work or measurement."
            ],
        )
    )


def _stage_membership(plan, completed):
    operations = {o.id: o for o in plan.operations}
    seen, present, joints = set(), set(), set()
    for oid in completed:
        if oid not in operations or oid in seen:
            raise ValueError(
                "Stage operation IDs must be unique and belong to the plan"
            )
        op = operations[oid]
        if not set(op.depends_on) <= seen:
            raise ValueError("Stage operation sequence must be dependency closed")
        seen.add(oid)
        present.update(op.effects.created_part_ids)
        joints.difference_update(op.effects.detached_joint_ids)
        joints.update(op.effects.attached_joint_ids)
    return present, joints


def evaluate_stage(
    plan: BuildPlan, snapshot: StageSnapshot, policy: AnalysisPolicy
) -> StageAnalysisResult:
    """Evaluate explicit poses/contacts; caller authenticates observed provenance.

    The supplied support frame has +z opposite gravity. An inclined/noncoplanar
    support is explicitly unsupported rather than flattened into a fictitious hull.
    """
    if (snapshot.project_id, snapshot.plan_version_id) != (
        plan.project_id,
        plan.version_id,
    ):
        raise ValueError("Stage snapshot must match project and plan")
    reference = project_nominal_geometry(plan)
    present, active = _stage_membership(plan, snapshot.completed_operation_ids)
    parts = {p.part_id: p for p in snapshot.parts}
    if len(parts) != len(snapshot.parts) or set(parts) != present:
        raise ValueError(
            "Stage must include exactly its present source parts; future parts cannot contribute"
        )
    if (
        len(set(snapshot.rigid_joint_ids)) != len(snapshot.rigid_joint_ids)
        or not set(snapshot.rigid_joint_ids) <= active
    ):
        raise ValueError("Rigid joint assumptions must refer only to active joints")
    allcontacts = [c.contact_id for p in snapshot.parts for c in p.contacts]
    if len(allcontacts) != len(set(allcontacts)):
        raise ValueError("Stage contact IDs must be globally unique")
    facets = []
    unknown_poses = set()
    for pid, part in parts.items():
        expected = {f.facet_id: f for f in reference.facets if f.part_id == pid}
        poses = {p.facet_id: p.transform for p in part.facet_poses}
        if len(poses) != len(part.facet_poses) or not poses.keys() <= expected.keys():
            raise ValueError(
                "Facet poses must be unique and match their canonical source part"
            )
        if poses.keys() != expected.keys():
            unknown_poses.add(pid)
        for fid, transform in poses.items():
            facet = expected[fid]
            facets.append(
                facet.model_copy(
                    update=dict(
                        vertices=tuple(
                            transform_point(transform, p) for p in facet.vertices
                        ),
                        centroid=transform_point(transform, facet.centroid),
                    )
                )
            )
    groups = [{p} for p in sorted(present)]
    joints = {j.id: j for j in plan.joints}
    face_map = {f.facet_id: f for f in facets}

    def on_face(point, facet):
        a, b, _, d = facet.vertices
        u = [getattr(b, k) - getattr(a, k) for k in ("x", "y", "z")]
        v = [getattr(d, k) - getattr(a, k) for k in ("x", "y", "z")]
        un, vn = sqrt(sum(x * x for x in u)), sqrt(sum(x * x for x in v))
        u, v = [x / un for x in u], [x / vn for x in v]
        n = [
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        ]
        q = [getattr(point, k) - getattr(a, k) for k in ("x", "y", "z")]
        return abs(sum(n[i] * q[i] for i in range(3))) <= 1e-8 and Polygon(
            ((0, 0), (un, 0), (un, vn), (0, vn))
        ).buffer(1e-8).covers(
            Point(
                sum(u[i] * q[i] for i in range(3)), sum(v[i] * q[i] for i in range(3))
            )
        )

    for pid, part in parts.items():
        if pid in unknown_poses:
            continue
        source_facets = [f for f in facets if f.part_id == pid]
        if any(
            not any(on_face(point, f) for f in source_facets)
            for c in part.contacts
            for point in c.polygon_world
        ):
            raise ValueError(
                "Stage contacts must lie on their transformed source body's surface"
            )

    def coincident(first, second):
        return all(
            any(
                sum((getattr(a, k) - getattr(b, k)) ** 2 for k in ("x", "y", "z"))
                <= 1e-16
                for b in second
            )
            for a in first
        )

    support = face_map.get("stand-support-support-face")
    lip = face_map.get("stand-support-lip-face")
    if support and lip:
        if not coincident(support.vertices[:2], lip.vertices[:2]):
            raise ValueError(
                "Source support and lip facets must retain their shared fold edge"
            )
        fold_done = any(
            o.type == "fold" and o.id in snapshot.completed_operation_ids
            for o in plan.operations
        )
        if not fold_done:
            a, b, c = support.vertices[:3]
            u = [getattr(b, k) - getattr(a, k) for k in ("x", "y", "z")]
            v = [getattr(c, k) - getattr(a, k) for k in ("x", "y", "z")]
            n = [
                u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0],
            ]
            norm = sqrt(sum(x * x for x in n))
            if any(
                abs(
                    sum(
                        n[i] * (getattr(p, k) - getattr(a, k))
                        for i, k in enumerate(("x", "y", "z"))
                    )
                )
                > norm * 1e-8
                for p in lip.vertices
            ):
                raise ValueError(
                    "Before the fold operation, support and lip must remain coplanar"
                )
    joint_edges = {
        "stand-joint-front": (
            "stand-support-support-face",
            (0, 1),
            "stand-base-base-face",
            (0, 1),
        ),
        "stand-joint-rear": (
            "stand-base-base-face",
            (2, 3),
            "stand-brace-brace-face",
            (2, 3),
        ),
        "stand-joint-apex": (
            "stand-support-support-face",
            (2, 3),
            "stand-brace-brace-face",
            (0, 1),
        ),
    }
    for jid in sorted(active):
        if jid not in joints or not set(joints[jid].part_ids) <= present:
            raise ValueError("Active joint references absent source parts")
        first, ai, second, bi = joint_edges[jid]
        if (
            first in face_map
            and second in face_map
            and not coincident(
                [face_map[first].vertices[i] for i in ai],
                [face_map[second].vertices[i] for i in bi],
            )
        ):
            raise ValueError(
                "Active joint edges must coincide in the supplied physical poses"
            )
        touched = [g for g in groups if g & set(joints[jid].part_ids)]
        merged = set().union(*touched)
        groups = [g for g in groups if g not in touched] + [merged]
    groups.sort(key=lambda g: sorted(g))
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
    digest = hashlib.sha256(
        json.dumps(
            dict(
                plan=plan.model_dump(mode="json"),
                snapshot=snapshot.model_dump(mode="json"),
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
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
            if set(joints[jid].part_ids) <= group
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
                    mass=_q(part.mass_kg, "kg"),
                    center_of_mass={
                        axis: _q(getattr(center, axis) if center else None, "m")
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
                gravity_m_s2=_q(magnitude, "m_s2"),
            )
        else:
            expected_joints = {
                jid for jid in active if set(joints[jid].part_ids) <= group
            }
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
            case["gravity_m_s2"] = _q(magnitude, "m_s2")
        analysis = StabilityInput.model_validate(
            dict(
                identity=dict(
                    project_id=plan.project_id,
                    plan_version_id=plan.version_id,
                    inventory_revision=snapshot.inventory_revision,
                    history_cursor=snapshot.history_cursor,
                    operation_state_id=f"stage-component-{index + 1}",
                    canonical_geometry_hash=digest,
                    evidence_hash=hashlib.sha256(b"no-stage-evidence").hexdigest(),
                    profile_hash=digest,
                ),
                geometry_version=VERSION,
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
    return StageAnalysisResult(
        producer_version=VERSION,
        snapshot_hash=digest,
        snapshot=snapshot,
        present_part_ids=tuple(sorted(present)),
        future_part_ids=tuple(sorted(set(reference.active_part_ids) - present)),
        active_joint_ids=tuple(sorted(active)),
        facets=tuple(facets),
        component_part_ids=tuple(tuple(sorted(g)) for g in groups),
        inputs=tuple(inputs),
        policies=tuple(policies),
        reports=tuple(reports),
        blockers=tuple(blockers),
    )
