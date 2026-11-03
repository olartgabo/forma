"""One polygonal physical producer for declarative assemblies of any panel shape."""

import hashlib
import json
from math import sqrt

from shapely.geometry import Polygon
from shapely.ops import unary_union

from forma_domain.generic_assembly import (
    GenericAssemblyRequest,
    GenericAssemblyResult,
    PolygonalFacet,
)
from forma_domain.stability_contracts import Point3
from forma_domain.stage_mechanics import StageSnapshot
from forma_stability.physical_checks import quantities_for_case
from forma_stability.stage_math import transform_point
from forma_stability.stage_solver import solve_components

VERSION = "polygonal-assembly-v1"
TOLERANCE_M = 1e-8


def _xyz(point):
    return (point.x, point.y, point.z)


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _unit(v):
    n = sqrt(_dot(v, v))
    if n <= 1e-12:
        raise ValueError("Polygon edges must have positive resolved length")
    return tuple(x / n for x in v)


def polygon_geometry(vertices):
    """Validate a simple planar polygon and return area, centroid and plane basis."""
    coordinates = [_xyz(p) for p in vertices]
    if any(abs(x) > 1e6 for p in coordinates for x in p):
        raise ValueError(
            "Physical coordinates exceed the supported million-metre range"
        )
    if len(set(coordinates)) != len(coordinates):
        raise ValueError(
            "Polygon vertices must be unique without a repeated closing vertex"
        )
    origin = coordinates[0]
    u = _unit(_sub(coordinates[1], origin))
    cross = next(
        (
            _cross(u, _sub(p, origin))
            for p in coordinates[2:]
            if sqrt(_dot(_cross(u, _sub(p, origin)), _cross(u, _sub(p, origin))))
            > 1e-12
        ),
        None,
    )
    if cross is None:
        raise ValueError("Polygon must have nonzero area")
    normal = _unit(cross)
    v = _cross(normal, u)
    if any(abs(_dot(normal, _sub(p, origin))) > TOLERANCE_M for p in coordinates):
        raise ValueError("Panel facets must be planar")
    polygon = Polygon(
        [(_dot(u, _sub(p, origin)), _dot(v, _sub(p, origin))) for p in coordinates]
    )
    if not polygon.is_valid or polygon.area <= 1e-16:
        raise ValueError("Panel polygon must be simple and have resolved positive area")
    center = polygon.centroid
    centroid = Point3(
        **dict(
            zip(
                ("x", "y", "z"),
                (origin[i] + u[i] * center.x + v[i] * center.y for i in range(3)),
            )
        )
    )
    return polygon.area, centroid, (origin, u, v, normal, polygon)


def _unique(values, label):
    if len(set(values)) != len(values):
        raise ValueError(f"Duplicate {label}")
    return set(values)


def contact_id_for_facet(facet_id):
    return "face-" + hashlib.sha256(facet_id.encode()).hexdigest()[:24]


def _edge(edge, faces):
    if edge.facet_id not in faces:
        raise ValueError("Unknown facet edge reference")
    points = faces[edge.facet_id]
    if edge.edge_index >= len(points):
        raise ValueError("Facet edge index exceeds polygon vertex count")
    return (points[edge.edge_index], points[(edge.edge_index + 1) % len(points)])


def _coincident(a, b):
    return all(
        any(
            sqrt(_dot(_sub(_xyz(p), _xyz(q)), _sub(_xyz(p), _xyz(q)))) <= TOLERANCE_M
            for q in b
        )
        for p in a
    )


def _validate_contact(contact, facets):
    _, _, (origin, u, v, normal, polygon) = polygon_geometry(contact.polygon_world)
    surface = []
    for facet in facets:
        if all(
            abs(_dot(normal, _sub(_xyz(p), origin))) <= TOLERANCE_M
            for p in facet.vertices
        ):
            surface.append(
                Polygon(
                    [
                        (_dot(u, _sub(_xyz(p), origin)), _dot(v, _sub(_xyz(p), origin)))
                        for p in facet.vertices
                    ]
                )
            )
    if not surface or not unary_union(surface).buffer(TOLERANCE_M).covers(polygon):
        raise ValueError(
            "The entire contact polygon must lie on the transformed source surface"
        )


def evaluate_assembly(request: GenericAssemblyRequest) -> GenericAssemblyResult:
    """Evaluate hypothetical declared physical stages without fabrication approval."""
    assembly, snapshot, policy = request.assembly, request.snapshot, request.policy
    if snapshot.basis != "hypothetical" or snapshot.completed_operation_ids:
        raise ValueError(
            "Declarative assembly stages are hypothetical and cannot claim completed fabrication operations"
        )
    if (assembly.project_id, assembly.plan_version_id) != (
        snapshot.project_id,
        snapshot.plan_version_id,
    ):
        raise ValueError("Assembly and snapshot identity must match")
    for case in snapshot.component_loads:
        quantities = (case.gravity_m_s2, *quantities_for_case(case))
        if any(
            q.provenance == "measured" or q.confirmed or q.evidence_ids
            for q in quantities
        ):
            raise ValueError(
                "Hypothetical assembly inputs cannot authenticate measurements or evidence"
            )
    part_ids = _unique([p.part_id for p in assembly.parts], "assembly part ID")
    local = {f.facet_id: f.vertices_local for p in assembly.parts for f in p.facets}
    facet_count = sum(len(p.facets) for p in assembly.parts)
    if len(local) != facet_count or facet_count > 128:
        raise ValueError("Facet IDs must be globally unique and total at most 128")
    owner = {f.facet_id: p.part_id for p in assembly.parts for f in p.facets}
    metrics = {fid: polygon_geometry(vertices) for fid, vertices in local.items()}
    joint_ids = _unique([j.joint_id for j in assembly.joints], "assembly joint ID")
    stage_ids = _unique([s.stage_id for s in assembly.stages], "assembly stage ID")
    if request.stage_id not in stage_ids:
        raise ValueError("Unknown assembly stage")
    joint_parts = {}
    for joint in assembly.joints:
        _edge(joint.first, local)
        _edge(joint.second, local)
        members = (owner[joint.first.facet_id], owner[joint.second.facet_id])
        if members[0] == members[1]:
            raise ValueError(
                "Inter-part joints require different source parts; use a source seam within a part"
            )
        joint_parts[joint.joint_id] = members
    for part in assembly.parts:
        fids = {f.facet_id for f in part.facets}
        connected = {next(iter(fids))}
        seam_pairs = []
        for seam in part.seams:
            _edge(seam.first, local)
            _edge(seam.second, local)
            pair = {seam.first.facet_id, seam.second.facet_id}
            if len(pair) != 2 or not pair <= fids:
                raise ValueError(
                    "Source seams must connect distinct facets of the same source part"
                )
            seam_pairs.append(pair)
        while True:
            expanded = connected | set().union(
                *(pair for pair in seam_pairs if pair & connected)
            )
            if expanded == connected:
                break
            connected = expanded
        if connected != fids:
            raise ValueError(
                "Multiple facets of one mass source require connected declared seams"
            )
    for declared in assembly.stages:
        present = _unique(list(declared.present_part_ids), "stage part")
        active = _unique(list(declared.active_joint_ids), "stage joint")
        if (
            not present <= part_ids
            or not active <= joint_ids
            or any(not set(joint_parts[j]) <= present for j in active)
        ):
            raise ValueError(
                "Stage membership/joints must reference present declared sources"
            )
    selected = next(s for s in assembly.stages if s.stage_id == request.stage_id)
    present, active = set(selected.present_part_ids), set(selected.active_joint_ids)
    parts = {p.part_id: p for p in snapshot.parts}
    if len(parts) != len(snapshot.parts) or set(parts) != present:
        raise ValueError(
            "Snapshot must include exactly the selected stage's present sources"
        )
    rigid = _unique(list(snapshot.rigid_joint_ids), "rigid joint")
    if not rigid <= active:
        raise ValueError("Only active stage joints can be assumed rigid")
    _unique([c.contact_id for p in snapshot.parts for c in p.contacts], "contact ID")
    facets = []
    unknown = set()
    for part in snapshot.parts:
        expected = {fid for fid in local if owner[fid] == part.part_id}
        poses = {f.facet_id: f.transform for f in part.facet_poses}
        if len(poses) != len(part.facet_poses) or not poses.keys() <= expected:
            raise ValueError(
                "Facet poses must uniquely refer to their owning source part"
            )
        if set(poses) != expected:
            unknown.add(part.part_id)
        total = sum(metrics[fid][0] for fid in expected)
        for fid, pose in poses.items():
            vertices = tuple(transform_point(pose, p) for p in local[fid])
            _, center, _ = polygon_geometry(vertices)
            facets.append(
                PolygonalFacet(
                    facet_id=fid,
                    part_id=part.part_id,
                    vertices=vertices,
                    centroid=center,
                    area_fraction=metrics[fid][0] / total,
                )
            )
    world = {f.facet_id: f.vertices for f in facets}
    for part in assembly.parts:
        if part.part_id not in present:
            continue
        for seam in part.seams:
            if (
                seam.first.facet_id in world
                and seam.second.facet_id in world
                and not _coincident(_edge(seam.first, world), _edge(seam.second, world))
            ):
                raise ValueError(
                    "Source seams must remain coincident under physical facet transforms"
                )
    groups = [{pid} for pid in sorted(present)]
    for joint in assembly.joints:
        if joint.joint_id not in active:
            continue
        if (
            joint.first.facet_id in world
            and joint.second.facet_id in world
            and not _coincident(_edge(joint.first, world), _edge(joint.second, world))
        ):
            raise ValueError("Active joint edge poses must coincide")
        touched = [g for g in groups if g & set(joint_parts[joint.joint_id])]
        groups = [g for g in groups if g not in touched] + [set().union(*touched)]
    groups.sort(key=lambda g: sorted(g))
    uniform = _unique(list(request.uniform_mass_part_ids), "uniform mass assumption")
    full_faces = _unique(
        list(request.full_face_contact_facet_ids), "full-face contact assumption"
    )
    if (
        not uniform <= present
        or not full_faces <= local.keys()
        or any(owner[fid] not in present for fid in full_faces)
    ):
        raise ValueError("Derived assumptions must refer to present sources/facets")
    normalized = []
    for pid, part in parts.items():
        updates = {}
        part_facets = [f for f in facets if f.part_id == pid]
        if pid in uniform:
            if part.center_of_mass_world is not None:
                raise ValueError(
                    "Choose explicit COM or hypothetical uniform centroid, not both"
                )
            if pid not in unknown:
                updates["center_of_mass_world"] = Point3(
                    **{
                        axis: sum(
                            getattr(f.centroid, axis) * f.area_fraction
                            for f in part_facets
                        )
                        for axis in ("x", "y", "z")
                    }
                )
        requested = [fid for fid in full_faces if owner[fid] == pid]
        if requested:
            if part.contacts:
                raise ValueError(
                    "Choose supplied contact polygons or full-face contacts for a source, not both"
                )
            updates["contacts"] = tuple(
                dict(contact_id=contact_id_for_facet(fid), polygon_world=world[fid])
                for fid in sorted(requested)
                if fid in world
            )
        if updates:
            part = type(part).model_validate({**part.model_dump(), **updates})
        if pid not in unknown:
            for contact in part.contacts:
                _validate_contact(contact, part_facets)
        normalized.append(part)
    snapshot = StageSnapshot.model_validate(
        {**snapshot.model_dump(), "parts": normalized}
    )
    _unique(
        [c.contact_id for p in snapshot.parts for c in p.contacts],
        "normalized contact ID",
    )
    digest = hashlib.sha256(
        json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    inputs, policies, reports, blockers = solve_components(
        snapshot,
        policy,
        groups,
        {p.part_id: p for p in snapshot.parts},
        active,
        joint_parts,
        unknown,
        digest,
        VERSION,
    )
    overlays = []
    for report in reports:
        for overlay in report.overlays:
            overlays.append(
                overlay.model_copy(
                    update=dict(
                        center_of_mass=transform_point(
                            snapshot.support_frame, overlay.center_of_mass
                        ),
                        support_polygon=tuple(
                            transform_point(snapshot.support_frame, p)
                            for p in overlay.support_polygon
                        ),
                        critical_edge=tuple(
                            transform_point(snapshot.support_frame, p)
                            for p in overlay.critical_edge
                        ),
                    )
                )
            )
    return GenericAssemblyResult(
        producer_version=VERSION,
        stage_id=selected.stage_id,
        stage_label=selected.label,
        snapshot_hash=digest,
        request=request,
        snapshot=snapshot,
        present_part_ids=tuple(sorted(present)),
        future_part_ids=tuple(sorted(part_ids - present)),
        active_joint_ids=tuple(sorted(active)),
        facets=tuple(facets),
        component_part_ids=tuple(tuple(sorted(g)) for g in groups),
        inputs=inputs,
        policies=policies,
        reports=reports,
        world_overlays=tuple(overlays),
        blockers=blockers,
    )
