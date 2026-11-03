"""Canonical nominal triangular-stand projection shared by mechanics and viewers.

Flat stock offsets are not world positions. Poses follow the validated template's
support/base/brace topology and fold, in the same frame as its side elevation.
This producer does not resolve masses, observed contacts or physical success.
"""

import hashlib
import json
from math import cos, radians, sin

from forma_renderer.continuation import stand_continuation_blockers

from forma_domain.assembly_geometry_contracts import (
    CanonicalFacet,
    CanonicalGeometryPreview,
    PartCentroid,
)
from forma_domain.models import BuildPlan, PhysicalEvent
from forma_domain.stability_contracts import Point3

PRODUCER_VERSION = "triangular-stand-nominal-v1"
_PARTS = ("stand-support", "stand-base", "stand-brace")
_JOINTS = ("stand-joint-front", "stand-joint-rear", "stand-joint-apex")
_ASSUMPTIONS = (
    (
        "nominal-zero-thickness",
        "Nominal zero-thickness surfaces omit fold allowance and physical deformation.",
    ),
    (
        "nominal-horizontal-base",
        "The full base rectangle is an assumed horizontal contact, not an observed contact patch.",
    ),
    (
        "uniform-sheet-centroids",
        "Geometric centroids and facet mass fractions assume uniform sheet density and thickness; they are not measured centers of mass.",
    ),
    (
        "unmodeled-connectors-device",
        "Connector mass and device pose, contact and mass remain unresolved; these sheet surfaces alone cannot establish stability.",
    ),
)


class UnsupportedGeometry(ValueError):
    """The plan/history cannot support this bounded canonical projection."""


def _history_stage(plan, events):
    operations = {op.id: op for op in plan.operations}
    completed: list[str] = []
    attached: set[str] = set()
    previous_time = None
    seen = set()
    for event in events:
        if event.project_id != plan.project_id or event.version_id != plan.version_id:
            raise UnsupportedGeometry(
                "Geometry history must match the exact project and plan version"
            )
        if event.id in seen or (
            previous_time is not None and event.recorded_at < previous_time
        ):
            raise UnsupportedGeometry(
                "Geometry history must be chronological with unique event IDs"
            )
        seen.add(event.id)
        previous_time = event.recorded_at
        if event.kind == "damage" or event.verification_state in (
            "failed",
            "invalidated",
        ):
            raise UnsupportedGeometry(
                "Damage or failed/invalidated reports require resolved physical geometry"
            )
        if event.operation_id is not None and event.operation_id not in operations:
            raise UnsupportedGeometry(
                "Geometry history references an unknown operation"
            )
        if event.kind != "operation_confirmed":
            continue
        if event.verification_state != "user_confirmed" or event.actor != "user":
            raise UnsupportedGeometry(
                "Assembly completion requires explicit user-reported confirmation"
            )
        op = operations[event.operation_id]
        if op.id in completed or not set(op.depends_on) <= set(completed):
            raise UnsupportedGeometry(
                "Assembly reports must be unique and dependency ordered"
            )
        if op.type == "detach" or op.effects.detached_joint_ids:
            raise UnsupportedGeometry("Detached assembly geometry is not supported")
        completed.append(op.id)
        attached.update(op.effects.attached_joint_ids)
    if not completed:
        return "planned_preview", (), ()
    required = {op.id for op in plan.operations[:6]}
    if not required <= set(completed) or attached != set(_JOINTS):
        raise UnsupportedGeometry(
            "Intermediate construction has no supported assembled contact geometry"
        )
    return (
        "reported_assembled",
        tuple(completed),
        tuple(j for j in _JOINTS if j in attached),
    )


def project_nominal_geometry(
    plan: BuildPlan, *, history_events: tuple[PhysicalEvent, ...] = ()
) -> CanonicalGeometryPreview:
    """Project an initial supported stand, never an incomplete or repaired pose.

    No assembly reports means an explicitly planned final-assembly preview. A
    reported assembly requires chronological, dependency-closed physical reports.
    Repaired plans await a bounded cross-version stage replay; they fail closed.
    """
    if plan.parent_version_id is not None or set(p.id for p in plan.parts) != set(
        _PARTS
    ):
        raise UnsupportedGeometry(
            "Repaired or replacement assemblies require cross-version geometry replay"
        )
    if plan.status == "blocked" or plan.compiler_version != "triangular-tape-stand-v1":
        raise UnsupportedGeometry(
            "Canonical geometry requires the supported stand compiler and an unblocked plan"
        )
    if len(plan.operations) != 8 or any(op.type == "detach" for op in plan.operations):
        raise UnsupportedGeometry("Only the initial eight-operation stand is supported")
    blockers = stand_continuation_blockers(plan)
    if blockers:
        raise UnsupportedGeometry("Unsupported canonical stand: " + blockers[0].message)
    for op in plan.operations:
        expected_attached = (op.args.joint_id,) if op.type == "tape_joint" else ()
        if (
            op.effects.attached_joint_ids != expected_attached
            or op.effects.detached_joint_ids
        ):
            raise UnsupportedGeometry(
                "Canonical operation effects disagree with the assembly topology"
            )
    if any(part.condition != "usable" for part in plan.parts):
        raise UnsupportedGeometry(
            "Damaged or uncertain parts require resolved physical geometry"
        )
    stage, completed, attached = _history_stage(plan, history_events)
    parts = {part.id: part for part in plan.parts}
    support = parts["stand-support"]
    width = support.geometry.width / 1000
    length = support.features[0].geometry.y / 1000
    lip = support.geometry.height / 1000 - length
    depth = parts["stand-base"].geometry.height / 1000
    theta = radians(plan.constraints.support_angle_deg.value)
    front = Point3(x=0, y=0, z=0)
    rear = Point3(x=0, y=depth, z=0)
    apex = Point3(x=0, y=length * cos(theta), z=length * sin(theta))
    lip_end = Point3(x=0, y=-lip * sin(theta), z=lip * cos(theta))

    def face(part_id, suffix, start, end, fraction=1.0, feature_id=None):
        return CanonicalFacet(
            facet_id=f"{part_id}-{suffix}",
            part_id=part_id,
            feature_id=feature_id,
            vertices=(
                Point3(x=-width / 2, y=start.y, z=start.z),
                Point3(x=width / 2, y=start.y, z=start.z),
                Point3(x=width / 2, y=end.y, z=end.z),
                Point3(x=-width / 2, y=end.y, z=end.z),
            ),
            centroid=Point3(x=0, y=(start.y + end.y) / 2, z=(start.z + end.z) / 2),
            area_fraction=fraction,
        )

    facets = (
        face("stand-support", "support-face", front, apex, length / (length + lip)),
        face(
            "stand-support",
            "lip-face",
            front,
            lip_end,
            lip / (length + lip),
            support.features[0].id,
        ),
        face("stand-base", "base-face", front, rear),
        face("stand-brace", "brace-face", apex, rear),
    )
    centroids = tuple(
        PartCentroid(
            part_id=part_id,
            centroid=Point3(
                **{
                    axis: sum(
                        getattr(f.centroid, axis) * f.area_fraction
                        for f in facets
                        if f.part_id == part_id
                    )
                    for axis in ("x", "y", "z")
                }
            ),
        )
        for part_id in _PARTS
    )
    fields = dict(
        project_id=plan.project_id,
        plan_version_id=plan.version_id,
        producer_version=PRODUCER_VERSION,
        history_cursor=history_events[-1].id if history_events else None,
        stage=stage,
        active_part_ids=_PARTS,
        nominal_joint_ids=_JOINTS,
        attached_joint_ids=attached,
        completed_operation_ids=completed,
        facets=facets,
        part_centroids=centroids,
        ground_part_id="stand-base",
        ground_polygon=facets[2].vertices,
        assumption_ids=tuple(item[0] for item in _ASSUMPTIONS),
        assumptions=tuple(item[1] for item in _ASSUMPTIONS),
    )
    provisional = CanonicalGeometryPreview(geometry_hash="0" * 64, **fields)
    canonical = provisional.model_dump(mode="json", exclude={"geometry_hash"})
    # Bind full event content, not only a cursor or completed-operation set.
    canonical["history"] = [event.model_dump(mode="json") for event in history_events]
    digest = hashlib.sha256(
        json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return CanonicalGeometryPreview(geometry_hash=digest, **fields)
