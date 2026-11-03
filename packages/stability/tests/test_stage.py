"""Analytic explicit stage tests, never evidence of physical construction."""

import json
from pathlib import Path

import pytest
from forma_stability import stage
from forma_stability.geometry import project_nominal_geometry
from forma_stability.lab_plan import inspect_plan
from pydantic import ValidationError

from forma_domain.models import BuildPlan
from forma_domain.stability_contracts import AnalysisPolicy, Point3
from forma_domain.stage_mechanics import RigidTransform, StageSnapshot


def plan():
    return BuildPlan.model_validate(
        json.loads(Path(stage.__file__).with_name("lab-stand-plan.json").read_text())[
            "plan"
        ]
    )


def policy(budget=16):
    return AnalysisPolicy(
        policy_id="test",
        version="v1",
        length_tolerance_m=1e-9,
        force_tolerance_n=1e-9,
        moment_tolerance_n_m=1e-9,
        relative_tolerance=1e-12,
        required_margin_m=0.0,
        uncertainty_method="analytic_interval",
        evaluation_budget=budget,
        required_check_types=("support", "tip"),
        required_case_ids=("component-1",),
    )


def test_cut_panels_are_separate_real_components_and_fold_mass_conserved():
    p = plan()
    s = stage.flat_parts_example(p)
    r = stage.evaluate_stage(p, s, policy())
    assert len(r.reports) == 3
    assert all(x.status == "modeled_pass" for x in r.reports)
    assert r.active_joint_ids == ()
    assert r.future_part_ids == ()
    assert len(r.facets) == 4
    assert sum(
        b.mass.value for i in r.inputs for b in i.mechanical_snapshot.bodies
    ) == pytest.approx(0.06)
    assert all(len(i.mechanical_snapshot.bodies) == 1 for i in r.inputs)
    for report, component in zip(r.reports, r.component_part_ids):
        part = next(x for x in p.parts if x.id == component[0])
        assert report.overlays[0].signed_margin_m == pytest.approx(
            min(part.geometry.width, part.geometry.height) / 2000
        )
    assert not r.physical_evidence_ids


def test_component_without_contact_cannot_borrow_other_parts_support():
    p = plan()
    raw = stage.flat_parts_example(p).model_dump()
    raw["parts"][0]["contacts"] = []
    r = stage.evaluate_stage(p, StageSnapshot.model_validate(raw), policy())
    assert any(x.status == "needs_measurement" for x in r.reports)
    assert sum(x.status == "modeled_pass" for x in r.reports) == 2


def test_frame_translation_rotation_leaves_physics_invariant():
    p = plan()
    s = stage.flat_parts_example(p)
    original = stage.evaluate_stage(p, s, policy())
    transform = RigidTransform(
        rotation=((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
        translation_m=Point3(x=2.0, y=3.0, z=4.0),
    )
    raw = s.model_dump()
    raw["support_frame"] = transform.model_dump()
    raw["gravity_world_m_s2"] = {"x": 0.0, "y": 9.81, "z": 0.0}
    for part in raw["parts"]:
        part["center_of_mass_world"] = stage.transform_point(
            transform, Point3.model_validate(part["center_of_mass_world"])
        ).model_dump()
        for contact in part["contacts"]:
            contact["polygon_world"] = [
                stage.transform_point(transform, Point3.model_validate(x)).model_dump()
                for x in contact["polygon_world"]
            ]
        for facet in part["facet_poses"]:
            old = RigidTransform.model_validate(facet["transform"])
            r = tuple(
                tuple(
                    sum(transform.rotation[i][k] * old.rotation[k][j] for k in range(3))
                    for j in range(3)
                )
                for i in range(3)
            )
            facet["transform"] = RigidTransform(
                rotation=r,
                translation_m=stage.transform_point(transform, old.translation_m),
            ).model_dump()
    rotated = stage.evaluate_stage(p, StageSnapshot.model_validate(raw), policy())
    for a, b in zip(original.reports, rotated.reports):
        assert a.status == b.status
        assert a.overlays[0].signed_margin_m == pytest.approx(
            b.overlays[0].signed_margin_m
        )
        assert a.overlays[0].restoring_moment_n_m == pytest.approx(
            b.overlays[0].restoring_moment_n_m
        )
    assert original.snapshot_hash != rotated.snapshot_hash


@pytest.mark.parametrize(
    "rotation",
    [
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),
        ((2.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    ],
)
def test_invalid_rigid_transforms_rejected(rotation):
    with pytest.raises(ValidationError):
        RigidTransform(rotation=rotation, translation_m=Point3(x=0.0, y=0.0, z=0.0))


@pytest.mark.parametrize(
    "change",
    ["future", "joint", "remote_contact", "disconnected_lip", "foreign", "order"],
)
def test_invalid_stage_cannot_produce_plausible_report(change):
    p = plan()
    raw = stage.flat_parts_example(p).model_dump()
    if change == "future":
        raw["completed_operation_ids"] = []
    elif change == "joint":
        raw["rigid_joint_ids"] = ["stand-joint-apex"]
    elif change == "remote_contact":
        raw["parts"][0]["contacts"][0]["polygon_world"][0]["x"] += 10
    elif change == "disconnected_lip":
        raw["parts"][0]["facet_poses"][1]["transform"]["translation_m"]["x"] += 1
    elif change == "foreign":
        raw["project_id"] = "different"
    elif change == "order":
        raw["completed_operation_ids"] = ["stand-inspect-cuts"]
    with pytest.raises(ValueError):
        stage.evaluate_stage(p, StageSnapshot.model_validate(raw), policy())


def test_missing_pose_unknown_mass_and_budget_do_not_pass_all_components():
    p = plan()
    raw = stage.flat_parts_example(p).model_dump()
    raw["parts"][0]["facet_poses"] = []
    raw["parts"][1]["mass_kg"] = None
    r = stage.evaluate_stage(p, StageSnapshot.model_validate(raw), policy())
    assert sum(x.status == "needs_measurement" for x in r.reports) == 2
    limited = stage.evaluate_stage(p, stage.flat_parts_example(p), policy(1))
    assert len(limited.reports) == 1 and limited.blockers


def test_lab_explicit_example_preserves_replay_and_world_overlays():
    p = plan()
    result = inspect_plan(
        dict(plan=p.model_dump(mode="json"), completed_prefix=1, stage_example=True)
    )
    assert result["report"] is None
    assert len(result["stage_analysis"]["reports"]) == 3
    assert len(result["stage_analysis_world_overlays"]) == 3
    assert result["request"]["stage_example"] is False
    assert inspect_plan(result["request"])["stage_analysis"] == result["stage_analysis"]


def nominal_snapshot(prefix):
    p = plan()
    reference = project_nominal_geometry(p)
    raw = stage.flat_parts_example(p).model_dump()
    raw["completed_operation_ids"] = [o.id for o in p.operations[:prefix]]
    raw["rigid_joint_ids"] = [
        j for o in p.operations[:prefix] for j in o.effects.attached_joint_ids
    ]
    identity = dict(
        rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        translation_m=dict(x=0.0, y=0.0, z=0.0),
    )
    for part in raw["parts"]:
        part["center_of_mass_world"] = next(
            c.centroid.model_dump()
            for c in reference.part_centroids
            if c.part_id == part["part_id"]
        )
        part["facet_poses"] = [
            dict(facet_id=f.facet_id, transform=identity)
            for f in reference.facets
            if f.part_id == part["part_id"]
        ]
        part["contacts"] = (
            [
                dict(
                    contact_id="base-contact",
                    polygon_world=[x.model_dump() for x in reference.ground_polygon],
                )
            ]
            if part["part_id"] == "stand-base"
            else []
        )
    return StageSnapshot.model_validate(raw)


def test_active_joints_change_components_without_borrowing_future_brace_contact():
    p = plan()
    intermediate = stage.evaluate_stage(p, nominal_snapshot(4), policy())
    assert intermediate.active_joint_ids == ("stand-joint-front",)
    assert len(intermediate.component_part_ids) == 2
    assert any(c == ("stand-brace",) for c in intermediate.component_part_ids)
    brace = next(
        report
        for component, report in zip(
            intermediate.component_part_ids, intermediate.reports
        )
        if component == ("stand-brace",)
    )
    assert brace.status == "needs_measurement"
    assembled = stage.evaluate_stage(p, nominal_snapshot(6), policy())
    assert len(assembled.reports) == 1
    assert assembled.reports[0].status == "modeled_pass"
    unknown_hinge = nominal_snapshot(4).model_copy(update=dict(rigid_joint_ids=()))
    unresolved = stage.evaluate_stage(p, unknown_hinge, policy())
    assert any(x.status == "unsupported" for x in unresolved.reports)


def test_remote_active_joint_and_fold_before_operation_are_rejected():
    p = plan()
    raw = nominal_snapshot(4).model_dump()
    brace = next(part for part in raw["parts"] if part["part_id"] == "stand-support")
    for facet in brace["facet_poses"]:
        facet["transform"]["translation_m"]["x"] += 1.0
    with pytest.raises(ValueError, match="joint edges"):
        stage.evaluate_stage(p, StageSnapshot.model_validate(raw), policy())
    with pytest.raises(ValueError, match="coplanar"):
        stage.evaluate_stage(p, nominal_snapshot(1), policy())


def test_missing_pose_cannot_pass_sliding_on_unvalidated_remote_contact():
    p = plan()
    snapshot = stage.flat_parts_example(p)
    initial = stage.evaluate_stage(p, snapshot, policy())
    raw = snapshot.model_dump()
    target = raw["parts"][0]
    target["facet_poses"] = []
    for point in target["contacts"][0]["polygon_world"]:
        point["x"] += 10.0

    def q(value, unit):
        return dict(
            kind="scalar", value=value, unit=unit, provenance="assumed", confirmed=False
        )

    cases = []
    for analysis in initial.inputs:
        case = analysis.cases[0].model_dump()
        case["sliding"] = dict(
            contact_id=case["contact_ids"][0],
            normal_force_n=q(10.0, "N"),
            tangential_force_n=q(1.0, "N"),
            friction_coefficient=q(0.5, "1"),
            planar_coulomb_applicable=True,
        )
        cases.append(case)
    raw["component_loads"] = cases
    result = stage.evaluate_stage(
        p,
        StageSnapshot.model_validate(raw),
        policy().model_copy(update=dict(required_check_types=("slide",))),
    )
    affected = next(
        (analysis, report)
        for analysis, report in zip(result.inputs, result.reports)
        if target["part_id"] in analysis.cases[0].body_ids
    )
    assert not affected[0].mechanical_snapshot.contacts[0].active
    assert affected[1].status == "needs_measurement"
    assert affected[1].results[0].status != "modeled_pass"
    assert (
        sum(
            check.status == "modeled_pass"
            for report in result.reports
            for check in report.results
            if check.check_type == "slide"
        )
        == 2
    )
