"""Shared template/software geometry, not measurements or physical acceptance."""

import importlib.util
import math
from datetime import timedelta
from pathlib import Path

import pytest
from forma_stability.geometry import UnsupportedGeometry, project_nominal_geometry
from pydantic import ValidationError

from forma_domain.assembly_geometry_contracts import CanonicalGeometryPreview
from forma_domain.models import BuildPlan, PhysicalEvent

_spec = importlib.util.spec_from_file_location(
    "stability_geometry_stand_fixture",
    Path(__file__).resolve().parents[2] / "renderer/tests/test_stand_manual.py",
)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)


def plan(alternate=False):
    return _fixtures.build(alternate=alternate)[0]


def events(p, count=6):
    return tuple(
        PhysicalEvent(
            id=f"completion-{index}",
            project_id=p.project_id,
            version_id=p.version_id,
            operation_id=op.id,
            kind="operation_confirmed",
            actor="user",
            observation="Synthetic test report; no physical work performed",
            verification_state="user_confirmed",
            recorded_at=p.created_at + timedelta(seconds=index),
        )
        for index, op in enumerate(p.operations[:count])
    )


@pytest.mark.parametrize("alternate", [False, True])
def test_canonical_faces_match_template_side_elevation_and_conserve_mass(alternate):
    p = plan(alternate)
    geometry = project_nominal_geometry(p)
    parts = {part.id: part for part in p.parts}
    support = parts["stand-support"]
    length = support.features[0].geometry.y / 1000
    lip = (support.geometry.height - support.features[0].geometry.y) / 1000
    theta = math.radians(p.constraints.support_angle_deg.value)
    facets = {facet.facet_id: facet for facet in geometry.facets}
    support_face = facets["stand-support-support-face"]
    lip_face = facets["stand-support-lip-face"]
    assert support_face.vertices[2].y == pytest.approx(length * math.cos(theta))
    assert support_face.vertices[2].z == pytest.approx(length * math.sin(theta))
    assert lip_face.vertices[2].y == pytest.approx(-lip * math.sin(theta))
    assert lip_face.vertices[2].z == pytest.approx(lip * math.cos(theta))
    assert support_face.vertices[:2] == lip_face.vertices[:2]
    assert sum(
        f.area_fraction for f in geometry.facets if f.part_id == support.id
    ) == pytest.approx(1)
    for centroid in geometry.part_centroids:
        owned = [f for f in geometry.facets if f.part_id == centroid.part_id]
        for axis in ("x", "y", "z"):
            assert getattr(centroid.centroid, axis) == pytest.approx(
                sum(getattr(f.centroid, axis) * f.area_fraction for f in owned)
            )
    assert len(geometry.active_part_ids) == 3
    assert len(geometry.facets) == 4
    assert geometry.stage == "planned_preview"
    assert geometry.attached_joint_ids == geometry.completed_operation_ids == ()
    assert geometry.state_basis == "nominal"
    assert all(point.z == 0 for point in geometry.ground_polygon)
    assert geometry.ground_polygon[2].y == pytest.approx(
        parts["stand-base"].geometry.height / 1000
    )
    assert "uniform-sheet-centroids" in geometry.assumption_ids
    assert "unmodeled-connectors-device" in geometry.assumption_ids


def test_hash_deterministic_and_ignores_cut_layout_offsets_and_timestamp():
    p = plan()
    baseline = project_nominal_geometry(p)
    assert baseline == project_nominal_geometry(p)
    data = p.model_dump()
    data["created_at"] += timedelta(days=1)
    for part in data["parts"]:
        part["geometry"]["x"] += 1
        part["geometry"]["y"] += 1
    moved = project_nominal_geometry(BuildPlan.model_validate(data))
    assert moved.geometry_hash == baseline.geometry_hash
    assert moved.facets == baseline.facets
    assert project_nominal_geometry(plan(True)).geometry_hash != baseline.geometry_hash
    other_version = p.model_copy(update={"version_id": "different-version"})
    assert (
        project_nominal_geometry(other_version).geometry_hash != baseline.geometry_hash
    )


def test_reported_assembly_replays_dependencies_but_remains_nominal():
    p = plan()
    reports = events(p)
    geometry = project_nominal_geometry(p, history_events=reports)
    assert geometry.stage == "reported_assembled"
    assert geometry.state_basis == "nominal"
    assert geometry.completed_operation_ids == tuple(op.id for op in p.operations[:6])
    assert geometry.attached_joint_ids == geometry.nominal_joint_ids
    assert geometry.history_cursor == reports[-1].id
    assert geometry.geometry_hash != project_nominal_geometry(p).geometry_hash
    altered_report = reports[-1].model_copy(
        update={"observation": "different history content"}
    )
    assert (
        project_nominal_geometry(
            p, history_events=reports[:-1] + (altered_report,)
        ).geometry_hash
        != geometry.geometry_hash
    )


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_partial_assembly_cannot_borrow_final_contacts(count):
    p = plan()
    with pytest.raises(UnsupportedGeometry, match="Intermediate"):
        project_nominal_geometry(p, history_events=events(p, count))


@pytest.mark.parametrize(
    "change",
    [
        "foreign_project",
        "foreign_version",
        "duplicate",
        "out_of_order",
        "dependency",
        "unconfirmed",
        "damage",
        "failed",
    ],
)
def test_unsafe_or_incoherent_history_rejected(change):
    p = plan()
    reports = list(events(p))
    if change == "foreign_project":
        reports[0] = reports[0].model_copy(update={"project_id": "other"})
    elif change == "foreign_version":
        reports[0] = reports[0].model_copy(update={"version_id": "other"})
    elif change == "duplicate":
        reports.append(reports[-1])
    elif change == "out_of_order":
        reports[1] = reports[1].model_copy(
            update={"recorded_at": p.created_at - timedelta(seconds=1)}
        )
    elif change == "dependency":
        reports.pop(0)
    elif change == "unconfirmed":
        reports[0] = reports[0].model_copy(update={"verification_state": "unknown"})
    elif change == "damage":
        reports.append(
            reports[-1].model_copy(update={"id": "damage", "kind": "damage"})
        )
    elif change == "failed":
        reports.append(
            reports[-1].model_copy(
                update={
                    "id": "failure",
                    "kind": "observation",
                    "verification_state": "failed",
                }
            )
        )
    with pytest.raises(UnsupportedGeometry):
        project_nominal_geometry(p, history_events=tuple(reports))


@pytest.mark.parametrize(
    "change",
    [
        "repair",
        "blocked",
        "wrong_compiler",
        "bad_brace",
        "bad_fold",
        "bad_joint",
        "damaged_part",
        "fake_effects",
    ],
)
def test_unsupported_plan_or_topology_rejected(change):
    data = plan().model_dump()
    if change == "repair":
        data["parent_version_id"] = "previous"
    elif change == "blocked":
        data["status"] = "blocked"
    elif change == "wrong_compiler":
        data["compiler_version"] = "other"
    elif change == "bad_brace":
        data["parts"][2]["geometry"]["height"] += 1
    elif change == "bad_fold":
        data["operations"][2]["args"]["angle_deg"] = 45
    elif change == "bad_joint":
        data["joints"][0]["part_ids"] = ("stand-support", "stand-brace")
    elif change == "damaged_part":
        data["parts"][0]["condition"] = "damaged"
    elif change == "fake_effects":
        data["operations"][0]["effects"]["attached_joint_ids"] = ("stand-joint-front",)
    with pytest.raises(UnsupportedGeometry):
        project_nominal_geometry(BuildPlan.model_validate(data))


@pytest.mark.parametrize(
    "change",
    [
        "fraction",
        "duplicate_facet",
        "wrong_part",
        "false_completion",
        "nonplanar_contact",
    ],
)
def test_geometry_contract_rejects_inconsistent_claims(change):
    data = project_nominal_geometry(plan()).model_dump()
    if change == "fraction":
        data["facets"][0]["area_fraction"] = 0.5
    elif change == "duplicate_facet":
        data["facets"][1]["facet_id"] = data["facets"][0]["facet_id"]
    elif change == "wrong_part":
        data["part_centroids"][0]["part_id"] = "foreign"
    elif change == "false_completion":
        data["attached_joint_ids"] = data["nominal_joint_ids"]
    elif change == "nonplanar_contact":
        data["ground_polygon"][0]["z"] = 1
    with pytest.raises(ValidationError):
        CanonicalGeometryPreview.model_validate(data)
