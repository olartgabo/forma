"""Parametric target geometry, never prewritten construction sequences."""

import math

from forma_domain.generic_assembly import GenericAssemblyRequest
from forma_stability.generic_examples import assembly_example


def polygon_target(kind, width_mm, depth_mm, height_mm, sides):
    """Flat polygon or connected rectangular walls with no invented edge contact."""
    w, d, h = (v / 1000 for v in (width_mm, depth_mm, height_mm))
    if kind == "screen":
        points = [(w * i / sides, d * (i % 2), 0.0) for i in range(sides + 1)]
    else:
        raw = [
            (math.cos(2 * math.pi * i / sides), math.sin(2 * math.pi * i / sides))
            for i in range(sides)
        ]
        lo = tuple(min(p[k] for p in raw) for k in (0, 1))
        span = tuple(max(p[k] for p in raw) - lo[k] for k in (0, 1))
        points = [
            ((x - lo[0]) * w / span[0], (y - lo[1]) * d / span[1], 0.0) for x, y in raw
        ]

    def point(p):
        return dict(zip(("x", "y", "z"), p))

    panels = {}
    if kind == "polygon":
        panels["panel"] = points
    else:
        for i in range(sides):
            a, b = points[i], points[(i + 1) % len(points)]
            panels[f"wall-{i + 1:02d}"] = [a, b, (b[0], b[1], h), (a[0], a[1], h)]
    ids = list(panels)
    joints = [
        dict(
            joint_id=f"corner-{i + 1:02d}",
            first=dict(facet_id=ids[i] + "-face", edge_index=1),
            second=dict(facet_id=ids[(i + 1) % len(ids)] + "-face", edge_index=3),
        )
        for i in range(len(ids) if kind == "enclosure" else len(ids) - 1)
    ]
    base = assembly_example("triangle").model_dump(mode="json")
    identity = base["snapshot"]["support_frame"]
    base["assembly"]["parts"] = [
        dict(
            part_id=pid,
            facets=[
                dict(
                    facet_id=pid + "-face", vertices_local=[point(p) for p in vertices]
                )
            ],
        )
        for pid, vertices in panels.items()
    ]
    base["assembly"]["joints"] = joints
    base["assembly"]["stages"] = [
        dict(
            stage_id="complete",
            label="Proposed finished target",
            present_part_ids=ids,
            active_joint_ids=[j["joint_id"] for j in joints],
        )
    ]
    base["snapshot"]["parts"] = [
        dict(
            part_id=pid,
            mass_kg=None,
            center_of_mass_world=None,
            facet_poses=[dict(facet_id=pid + "-face", transform=identity)],
            contacts=[],
            rigid_body_assumed=True,
        )
        for pid in ids
    ]
    base["snapshot"]["rigid_joint_ids"] = [j["joint_id"] for j in joints]
    base["snapshot"]["assumption_notes"] = [
        "Proposed panel geometry and assumed rigid connections. Mass, ground contact, joint strength and physical completion are not inferred."
    ]
    base["uniform_mass_part_ids"] = ids
    base["full_face_contact_facet_ids"] = ["panel-face"] if kind == "polygon" else []
    return GenericAssemblyRequest.model_validate(base)
