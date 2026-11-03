"""Independent geometry cases for the data-driven physical assembly producer."""

import json

import pytest
from forma_stability.generic_assembly import evaluate_assembly
from forma_stability.generic_examples import assembly_example
from forma_stability.stage_math import transform_point

from forma_domain.generic_assembly import GenericAssemblyRequest
from forma_domain.stability_contracts import Point3
from forma_domain.stage_mechanics import RigidTransform


def run(raw):
    return evaluate_assembly(GenericAssemblyRequest.model_validate(raw))


@pytest.mark.parametrize("name", ("triangle", "concave", "ramp", "box"))
def test_different_shapes_use_one_declarative_engine(name):
    request = assembly_example(name)
    result = evaluate_assembly(request)
    assert all(r.status == "modeled_pass" for r in result.reports)
    assert len(result.inputs[0].mechanical_snapshot.bodies) == len(
        request.assembly.parts
    )
    assert sum(
        b.mass.value for b in result.inputs[0].mechanical_snapshot.bodies
    ) == pytest.approx(0.1 * len(request.assembly.parts))
    assert not result.physical_evidence_ids
    assert result.request == request
    assert (
        any(len(f.vertices) != 4 for f in result.facets)
        if name in ("triangle", "concave")
        else True
    )


def test_box_analytic_com_margin_and_moment():
    result = evaluate_assembly(assembly_example("box"))
    overlay = result.world_overlays[0]
    assert (
        overlay.center_of_mass.x,
        overlay.center_of_mass.y,
        overlay.center_of_mass.z,
    ) == pytest.approx((0.1, 0.15, 0.04))
    assert overlay.signed_margin_m == pytest.approx(0.1)
    assert overlay.restoring_moment_n_m == pytest.approx(0.4905)


def test_concave_centroid_and_triangle_centroid_are_area_weighted():
    concave = evaluate_assembly(assembly_example("concave"))
    assert (
        concave.facets[0].centroid.x,
        concave.facets[0].centroid.y,
    ) == pytest.approx((0.11, 0.11))
    triangle = evaluate_assembly(assembly_example("triangle"))
    assert (
        triangle.facets[0].centroid.x,
        triangle.facets[0].centroid.y,
    ) == pytest.approx((0.1, 0.2 / 3))


def test_arbitrary_renamed_ids_leave_physics_unchanged():
    request = assembly_example("box")
    raw = request.model_dump(mode="json")
    replacements = {
        "generic-lab": "project-other",
        "generic-example-v1": "revision-other",
        "deck": "bottom-panel",
        "front": "wall-a",
        "right": "wall-b",
        "rear": "wall-c",
        "left": "wall-d",
    }
    ids = (
        {p.part_id for p in request.assembly.parts}
        | {f.facet_id for p in request.assembly.parts for f in p.facets}
        | {j.joint_id for j in request.assembly.joints}
    )
    replacements.update(
        {value: f"arbitrary-{i}" for i, value in enumerate(sorted(ids))}
    )

    def renamed(value):
        if isinstance(value, dict):
            return {k: renamed(v) for k, v in value.items()}
        if isinstance(value, list):
            return [renamed(v) for v in value]
        return replacements.get(value, value) if isinstance(value, str) else value

    result = run(renamed(raw))
    original = evaluate_assembly(request)
    assert result.reports[0].status == original.reports[0].status
    assert result.world_overlays[0].signed_margin_m == pytest.approx(
        original.world_overlays[0].signed_margin_m
    )
    assert (
        result.world_overlays[0].center_of_mass
        == original.world_overlays[0].center_of_mass
    )


def test_stage_membership_and_detachment_do_not_join_unconnected_support():
    raw = assembly_example("box").model_dump(mode="json")
    raw["assembly"]["stages"].append(
        dict(
            stage_id="loose",
            label="Loose walls",
            present_part_ids=[p["part_id"] for p in raw["assembly"]["parts"]],
            active_joint_ids=[],
        )
    )
    raw["stage_id"] = "loose"
    raw["snapshot"]["rigid_joint_ids"] = []
    result = run(raw)
    assert len(result.component_part_ids) == 5
    assert sum(r.status == "modeled_pass" for r in result.reports) == 1
    assert sum(r.status == "needs_measurement" for r in result.reports) == 4
    raw["stage_id"] = "base"
    raw["snapshot"]["parts"] = raw["snapshot"]["parts"][:1]
    raw["uniform_mass_part_ids"] = ["deck"]
    result = run(raw)
    assert len(result.future_part_ids) == 4
    assert len(result.inputs[0].mechanical_snapshot.bodies) == 1


@pytest.mark.parametrize(
    "kind",
    (
        "self_intersection",
        "nonplanar",
        "remote_joint",
        "future_part",
        "duplicate_id",
        "unknown_edge",
        "observed",
    ),
)
def test_invalid_geometry_and_membership_cannot_pass(kind):
    raw = assembly_example("box").model_dump(mode="json")
    if kind == "self_intersection":
        vertices = raw["assembly"]["parts"][0]["facets"][0]["vertices_local"]
        vertices[1], vertices[2] = vertices[2], vertices[1]
    elif kind == "nonplanar":
        raw["assembly"]["parts"][0]["facets"][0]["vertices_local"][2]["z"] += 0.01
    elif kind == "remote_joint":
        raw["snapshot"]["parts"][1]["facet_poses"][0]["transform"]["translation_m"][
            "x"
        ] += 1.0
    elif kind == "future_part":
        raw["stage_id"] = "base"
    elif kind == "duplicate_id":
        raw["assembly"]["parts"][1]["part_id"] = "deck"
    elif kind == "unknown_edge":
        raw["assembly"]["joints"][0]["first"]["edge_index"] = 20
    elif kind == "observed":
        raw["snapshot"]["basis"] = "observed"
    with pytest.raises(ValueError):
        run(raw)


def test_contact_polygon_cannot_bridge_missing_material_of_concave_source():
    raw = assembly_example("concave").model_dump(mode="json")
    raw["full_face_contact_facet_ids"] = []
    raw["snapshot"]["parts"][0]["contacts"] = [
        dict(
            contact_id="fake-contact",
            polygon_world=[
                dict(x=x, y=y, z=0.0) for x, y in ((0.0, 0.0), (0.3, 0.1), (0.1, 0.3))
            ],
        )
    ]
    with pytest.raises(ValueError, match="entire contact polygon"):
        run(raw)


def test_missing_pose_and_mass_are_unknown_and_cannot_gain_automatic_contact():
    raw = assembly_example("triangle").model_dump(mode="json")
    raw["snapshot"]["parts"][0]["facet_poses"] = []
    result = run(raw)
    assert result.reports[0].status == "needs_measurement"
    assert result.snapshot.parts[0].contacts == ()
    raw = assembly_example("triangle").model_dump(mode="json")
    raw["snapshot"]["parts"][0]["mass_kg"] = None
    assert run(raw).reports[0].status == "needs_measurement"


def test_rotated_support_frame_preserves_physics_and_world_overlay():
    request = assembly_example("ramp")
    raw = request.model_dump(mode="json")
    transform = RigidTransform(
        rotation=((0.0, -1.0, 0.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0)),
        translation_m=Point3(x=2.0, y=3.0, z=4.0),
    )
    raw["snapshot"]["support_frame"] = transform.model_dump(mode="json")
    raw["snapshot"]["gravity_world_m_s2"] = {"x": 0.0, "y": 9.81, "z": 0.0}
    for part in raw["snapshot"]["parts"]:
        for pose in part["facet_poses"]:
            pose["transform"] = transform.model_dump(mode="json")
    result = run(raw)
    original = evaluate_assembly(request)
    assert result.reports[0].status == original.reports[0].status
    assert result.world_overlays[0].signed_margin_m == pytest.approx(
        original.world_overlays[0].signed_margin_m
    )
    expected = transform_point(transform, original.world_overlays[0].center_of_mass)
    assert tuple(
        result.world_overlays[0].center_of_mass.model_dump().values()
    ) == pytest.approx(tuple(expected.model_dump().values()))


def test_multiple_facets_require_connected_seams_and_conserve_source_mass():
    raw = assembly_example("triangle").model_dump(mode="json")
    original = raw["assembly"]["parts"][0]
    original["facets"] = [
        dict(
            facet_id="first",
            vertices_local=[
                dict(x=x, y=y, z=0.0) for x, y in ((0.0, 0.0), (0.2, 0.0), (0.2, 0.2))
            ],
        ),
        dict(
            facet_id="second",
            vertices_local=[
                dict(x=x, y=y, z=0.0) for x, y in ((0.0, 0.0), (0.2, 0.2), (0.0, 0.2))
            ],
        ),
    ]
    identity = raw["snapshot"]["support_frame"]
    raw["snapshot"]["parts"][0]["facet_poses"] = [
        dict(facet_id=f["facet_id"], transform=identity) for f in original["facets"]
    ]
    raw["full_face_contact_facet_ids"] = ["first", "second"]
    with pytest.raises(ValueError, match="connected declared seams"):
        run(raw)
    original["seams"] = [
        dict(
            first=dict(facet_id="first", edge_index=2),
            second=dict(facet_id="second", edge_index=0),
        )
    ]
    result = run(raw)
    assert len(result.inputs[0].mechanical_snapshot.bodies) == 1
    assert result.inputs[0].mechanical_snapshot.bodies[0].mass.value == 0.1
    assert sum(f.area_fraction for f in result.facets) == pytest.approx(1.0)
    assert result.reports[0].status == "modeled_pass"
    assert json.loads(result.model_dump_json())[
        "request"
    ] == GenericAssemblyRequest.model_validate(raw).model_dump(mode="json")
