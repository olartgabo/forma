"""Synthetic geometry only; none of these fixtures is physical evidence."""

from copy import deepcopy

import pytest
from forma_compiler import CutProcess, validate_plan
from pydantic import ValidationError

from forma_domain.models import BuildPlan, Evidence


def measurement(value, unit="mm"):
    return dict(
        value=value, unit=unit, source="user_ruler", confirmed=True, evidence_ids=[]
    )


def plan_data():
    unknown = dict(value=None, unit="mm", source="unknown", confirmed=False)
    return dict(
        project_id="project",
        version_id="v1",
        status="draft",
        family="tabletop_fixture_v1",
        stocks=[
            dict(
                id="sheet",
                kind="sheet",
                material="cardboard",
                width_mm=measurement(200),
                height_mm=measurement(120),
                thickness_mm=measurement(3),
                remaining_length_mm=unknown,
                condition="usable",
                usable_regions=[
                    dict(id="root", geometry=dict(x=0, y=0, width=200, height=120))
                ],
            )
        ],
        parts=[
            dict(
                id="base",
                source_stock_id="sheet",
                source_region_id="root",
                geometry=dict(x=5, y=5, width=60, height=90),
                condition="usable",
            )
        ],
        joint_profiles=[],
        joints=[],
        operations=[
            dict(
                id="cut",
                type="cut_rect",
                part_ids=[],
                stock_ids=["sheet"],
                depends_on=[],
                expected_state_id="state",
                preconditions=dict(safe_tools_confirmed=True),
                effects=dict(
                    created_part_ids=["base"],
                    consumed_region_ids=["root"],
                    created_offcuts=[
                        dict(
                            id="offcut", geometry=dict(x=70, y=0, width=130, height=120)
                        )
                    ],
                ),
                args=dict(
                    stock_id="sheet",
                    source_region_id="root",
                    child_part_ids=["base"],
                    kerf_mm=2,
                    edge_margin_mm=5,
                ),
            )
        ],
        checkpoints=[],
        constraints=dict(
            device_mass_g=measurement(180, "g"),
            support_angle_deg=measurement(60, "deg"),
            max_footprint_width_mm=measurement(200),
            max_footprint_height_mm=measurement(120),
        ),
        compiler_version="synthetic",
        created_at="2026-10-30T00:00:00Z",
    )


def process():
    return CutProcess(
        kerf_min_mm=2,
        edge_margin_min_mm=5,
        evidence=(
            Evidence(
                id="process_fixture",
                project_id="project",
                version_id="v1",
                kind="measurement",
                provenance="synthetic_fixture",
                recorded_at="2026-10-30T00:00:00Z",
                description="Synthetic process limits, not physical evidence",
                verification_state="unknown",
            ),
        ),
    )


def codes(data):
    return {
        b.code
        for b in validate_plan(
            BuildPlan.model_validate(data), process=process(), allow_synthetic=True
        ).blockers
    }


def second_cut(data, source="offcut"):
    data["parts"].append(
        dict(
            id="brace",
            source_stock_id="sheet",
            source_region_id=source,
            geometry=dict(x=75, y=5, width=30, height=50),
            condition="usable",
        )
    )
    op = deepcopy(data["operations"][0])
    op.update(id="cut_brace", depends_on=["cut"])
    op["args"].update(source_region_id=source, child_part_ids=["brace"])
    op["effects"] = dict(created_part_ids=["brace"], consumed_region_ids=[source])
    data["operations"].append(op)
    return data


def test_valid_cut_and_offcut_reuse():
    assert not codes(plan_data())
    assert not codes(second_cut(plan_data()))


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda d: d["parts"][0]["geometry"].update(width=300), "geometry_invalid"),
        (
            lambda d: d["stocks"][0]["width_mm"].update(
                value=None, source="unknown", confirmed=False
            ),
            "missing_measurement",
        ),
        (
            lambda d: d["operations"][0]["preconditions"].update(
                safe_tools_confirmed=False
            ),
            "needs_confirmation",
        ),
        (
            lambda d: d["operations"][0]["effects"].update(created_part_ids=[]),
            "invalid_reference",
        ),
        (
            lambda d: d["operations"][0]["effects"]["created_offcuts"][0][
                "geometry"
            ].update(x=50),
            "geometry_invalid",
        ),
        (lambda d: d["parts"][0]["geometry"].update(x=2), "geometry_invalid"),
    ],
)
def test_rejections(mutation, expected):
    data = plan_data()
    mutation(data)
    assert expected in codes(data)


def test_double_spend_and_producer_dependency():
    assert "stock_exhausted" in codes(second_cut(plan_data(), "root"))
    data = second_cut(plan_data())
    data["operations"][1]["depends_on"] = []
    assert "invalid_order" in codes(data)


def test_duplicate_offcut_spend():
    data = second_cut(plan_data())
    third = deepcopy(data["operations"][1])
    third["id"] = "third"
    data["operations"].append(third)
    assert "stock_exhausted" in codes(data)


def test_kerf_and_orientation():
    data = plan_data()
    data["operations"][0]["effects"]["created_offcuts"][0]["geometry"]["x"] = 66
    assert "geometry_invalid" in codes(data)
    data = plan_data()
    data["stocks"][0]["allowed_rotations_deg"] = [0]
    data["parts"][0]["geometry"]["rotation_deg"] = 90
    assert "geometry_invalid" in codes(data)


def test_schema_rejects_missing_parts_and_bad_dependencies():
    data = plan_data()
    data["operations"][0]["args"]["child_part_ids"] = ["missing"]
    with pytest.raises(ValidationError):
        BuildPlan.model_validate(data)
    data = plan_data()
    data["operations"][0]["depends_on"] = ["cut"]
    with pytest.raises(ValidationError):
        BuildPlan.model_validate(data)


def test_validation_is_pure():
    plan = BuildPlan.model_validate(plan_data())
    before = plan.model_dump_json()
    validate_plan(plan)
    assert plan.model_dump_json() == before


def joined_data(strategy="tape"):
    data = second_cut(plan_data())
    data["joint_profiles"] = [
        dict(
            id="profile",
            strategy=strategy,
            status="tested",
            material="cardboard",
            thickness_min_mm=2,
            thickness_max_mm=4,
            tolerated_error_mm=0.5,
            test_evidence_ids=["synthetic_joint_fixture"],
        )
    ]
    data["constraints"]["allowed_profile_ids"] = ["profile"]
    data["joints"] = [
        dict(
            id="joint",
            profile_id="profile",
            part_ids=["base", "brace"],
            confirmed_accessible=True,
        )
    ]
    unknown = dict(value=None, unit="mm", source="unknown", confirmed=False)
    data["stocks"].append(
        dict(
            id="tape",
            kind="tape",
            material="other_supported",
            width_mm=unknown,
            height_mm=unknown,
            thickness_mm=unknown,
            remaining_length_mm=measurement(100),
            condition="usable",
        )
    )
    data["operations"].append(
        dict(
            id="join",
            type="tape_joint",
            part_ids=["base", "brace"],
            stock_ids=["tape"],
            depends_on=["cut_brace"],
            expected_state_id="joined",
            preconditions={},
            effects=dict(attached_joint_ids=["joint"]),
            args=dict(joint_id="joint", stock_id="tape", length_mm=80),
            reversible="lossy",
        )
    )
    return data


def test_joint_profiles_and_connector_accounting():
    assert not codes(joined_data())
    data = joined_data()
    data["joint_profiles"][0]["status"] = "experimental"
    assert "unsupported_profile" in codes(data)
    data = joined_data()
    data["stocks"][1]["remaining_length_mm"]["value"] = 50
    assert "stock_exhausted" in codes(data)
    data = joined_data()
    data["joints"][0]["confirmed_accessible"] = None
    assert "needs_confirmation" in codes(data)
    data = joined_data()
    data["joint_profiles"][0]["thickness_max_mm"] = 2.5
    assert "unsupported_profile" in codes(data)


def test_process_evidence_required_and_fixture_opt_in():
    plan = BuildPlan.model_validate(plan_data())
    assert validate_plan(plan).status == "blocked"
    assert validate_plan(plan, process=process()).status == "blocked"
    assert (
        validate_plan(plan, process=process(), allow_synthetic=True).status
        == "accepted"
    )
    strict = process().model_copy(update={"kerf_min_mm": 3})
    assert validate_plan(plan, process=strict, allow_synthetic=True).status == "blocked"


def test_stock_regions_may_not_overlap():
    data = plan_data()
    data["stocks"][0]["usable_regions"].append(
        dict(id="overlap", geometry=dict(x=1, y=1, width=50, height=50))
    )
    assert "geometry_invalid" in codes(data)


def test_wrong_stock_offcut_provenance():
    data = second_cut(plan_data())
    other = deepcopy(data["stocks"][0])
    other["id"] = "other"
    other["usable_regions"] = [
        dict(id="other_region", geometry=dict(x=0, y=0, width=200, height=120))
    ]
    data["stocks"].append(other)
    data["operations"][1]["args"]["stock_id"] = "other"
    assert "invalid_reference" in codes(data)


def tab_slot_data():
    data = joined_data("tab_slot")
    data["parts"][0]["features"] = [
        dict(id="tab", kind="tab", geometry=dict(x=0, y=0, width=10, height=3))
    ]
    data["parts"][1]["features"] = [
        dict(id="slot", kind="slot", geometry=dict(x=5, y=5, width=10, height=3))
    ]
    data["joints"][0]["interface_feature_ids"] = ["tab", "slot"]
    data["operations"].insert(
        2,
        dict(
            id="slot_cut",
            type="cut_slot",
            part_ids=["brace"],
            stock_ids=[],
            depends_on=["cut_brace"],
            expected_state_id="slotted",
            preconditions=dict(safe_tools_confirmed=True),
            effects=dict(changed_part_ids=["brace"]),
            args=dict(
                part_id="brace",
                feature_id="slot",
                geometry=dict(x=5, y=5, width=10, height=3),
                profile_id="profile",
                kerf_mm=2,
                edge_margin_mm=5,
            ),
        ),
    )
    data["operations"][-1].update(
        type="insert_tab",
        args=dict(joint_id="joint", tab_feature_id="tab", slot_feature_id="slot"),
        depends_on=["slot_cut"],
        reversible="reversible",
    )
    return data


def test_slot_must_be_cut_and_fit_measured_profile():
    assert not codes(tab_slot_data())
    data = tab_slot_data()
    data["operations"].pop(2)
    data["operations"][-1]["depends_on"] = ["cut_brace"]
    assert "invalid_order" in codes(data)
    data = tab_slot_data()
    data["parts"][0]["features"][0]["geometry"]["width"] = 12
    assert "geometry_invalid" in codes(data)
    data = tab_slot_data()
    data["joint_profiles"][0]["strategy"] = "tape"
    assert "unsupported_profile" in codes(data)


def test_measurement_prerequisite_is_temporal():
    data = plan_data()
    data["operations"][0]["preconditions"]["confirmed_measurement_ids"] = [
        "width_measured"
    ]
    data["operations"].append(
        dict(
            id="measure",
            type="measure",
            depends_on=[],
            expected_state_id="measured",
            preconditions={},
            effects={},
            args=dict(
                target_id="sheet",
                measurement_id="width_measured",
                dimension="width",
                method="ruler",
            ),
        )
    )
    assert "invalid_order" in codes(data)


def test_joint_prerequisite_and_inverse_are_temporal():
    data = joined_data()
    data["operations"].append(
        dict(
            id="detach",
            type="detach",
            part_ids=["base"],
            depends_on=["cut_brace"],
            expected_state_id="detached",
            preconditions={},
            effects=dict(detached_joint_ids=["joint"]),
            args=dict(joint_id="joint", supported_inverse="untie"),
            reversible="reversible",
        )
    )
    assert {"invalid_order", "unsupported"} <= codes(data)


def test_process_scope_cannot_cross_project():
    proc = process()
    wrong = proc.evidence[0].model_copy(update={"project_id": "other"})
    proc = proc.model_copy(update={"evidence": (wrong,)})
    result = validate_plan(
        BuildPlan.model_validate(plan_data()), process=proc, allow_synthetic=True
    )
    assert "invalid_reference" in {b.code for b in result.blockers}


def test_slot_change_effect_must_identify_changed_part():
    data = tab_slot_data()
    data["operations"][2]["effects"]["changed_part_ids"] = []
    assert "invalid_reference" in codes(data)


def test_detach_irreversible_join_requires_rejection():
    data = joined_data()
    data["operations"][-1]["reversible"] = "irreversible"
    data["operations"].append(
        dict(
            id="detach",
            type="detach",
            depends_on=["join"],
            expected_state_id="detached",
            preconditions={},
            effects=dict(detached_joint_ids=["joint"]),
            args=dict(
                joint_id="joint",
                supported_inverse="peel_tape",
                material_loss_stock_ids=["tape"],
            ),
            reversible="lossy",
        )
    )
    assert "irreversible_conflict" in codes(data)


def test_model_copy_cannot_bypass_plan_validation():
    plan = BuildPlan.model_validate(plan_data())
    malformed = plan.model_copy(update={"parts": ()})
    result = validate_plan(malformed, process=process(), allow_synthetic=True)
    assert result.status == "blocked"
    assert result.blockers[0].code == "invalid_reference"
