"""Synthetic offline regressions, never physical evidence."""

from copy import deepcopy

import pytest
from forma_compiler import CutProcess
from forma_replanner import rank_feasible, simulate_patch

from forma_domain.models import BuildPlan, Evidence, ReplannerInput

STAMP = "2026-10-30T00:00:00Z"


def measurement(value, unit="mm"):
    return dict(value=value, unit=unit, source="user_ruler", confirmed=True)


def fixture():
    unknown = dict(value=None, unit="mm", source="unknown", confirmed=False)
    return dict(
        project_id="project",
        version_id="v1",
        status="draft",
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
            ),
            dict(
                id="brace",
                source_stock_id="sheet",
                source_region_id="offcut",
                geometry=dict(x=75, y=5, width=30, height=50),
                condition="usable",
            ),
        ],
        joint_profiles=[],
        joints=[],
        operations=[
            dict(
                id="cut",
                type="cut_rect",
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
            ),
            dict(
                id="cut_brace",
                type="cut_rect",
                stock_ids=["sheet"],
                depends_on=["cut"],
                expected_state_id="brace_state",
                preconditions=dict(safe_tools_confirmed=True),
                effects=dict(
                    created_part_ids=["brace"], consumed_region_ids=["offcut"]
                ),
                args=dict(
                    stock_id="sheet",
                    source_region_id="offcut",
                    child_part_ids=["brace"],
                    kerf_mm=2,
                    edge_margin_mm=5,
                ),
            ),
        ],
        checkpoints=[
            dict(
                id="check",
                after_operation_id="cut_brace",
                method="ruler",
                description="Measure cut brace",
            )
        ],
        constraints=dict(
            device_mass_g=measurement(180, "g"),
            support_angle_deg=measurement(60, "deg"),
            max_footprint_width_mm=measurement(200),
            max_footprint_height_mm=measurement(120),
        ),
        compiler_version="synthetic",
        created_at=STAMP,
    )


def event(oid="cut", **updates):
    return (
        dict(
            id="event_" + str(oid),
            project_id="project",
            version_id="v1",
            operation_id=oid,
            kind="operation_confirmed",
            recorded_at=STAMP,
            actor="user",
            observation="Synthetic user report",
            verification_state="user_confirmed",
        )
        | updates
    )


def input_data(completed=("cut",)):
    base = fixture()
    stock = deepcopy(base["stocks"])
    for op in base["operations"]:
        if op["id"] in completed:
            stock[0]["usable_regions"] = deepcopy(
                op["effects"].get("created_offcuts", [])
            )
    return dict(
        base_plan=base,
        events=[event(oid) for oid in completed],
        evidence=[],
        material_transactions=[],
        remaining_stock=stock,
        patch=dict(
            id="resize",
            base_version_id="v1",
            kind="resize_part",
            target_id="brace",
            replacement_stock_id=None,
            replacement_profile_id=None,
            width_mm=35,
            height_mm=50,
            angle_deg=None,
            rationale="Synthetic edit",
        ),
    )


def process():
    return CutProcess(
        kerf_min_mm=2,
        edge_margin_min_mm=5,
        evidence=(
            Evidence(
                id="process",
                project_id="project",
                version_id="v1",
                kind="measurement",
                provenance="synthetic_fixture",
                recorded_at=STAMP,
                description="Synthetic limits",
                verification_state="unknown",
            ),
        ),
    )


def run(data):
    return simulate_patch(
        ReplannerInput.model_validate(data), process=process(), allow_synthetic=True
    )


def codes(result):
    return {b.code for b in result.blockers}


def unused_unknown(kind="sheet"):
    def unknown():
        return dict(value=None, unit="mm", source="unknown", confirmed=False)

    return dict(
        id="unused-unknown",
        kind=kind,
        material="cardboard" if kind == "sheet" else "other_supported",
        width_mm=unknown(),
        height_mm=unknown(),
        thickness_mm=unknown(),
        remaining_length_mm=unknown(),
        condition="uncertain",
        usable_regions=[],
    )


def add_unused_unknown(data, stock):
    data["base_plan"]["stocks"].append(deepcopy(stock))
    data["remaining_stock"].append(deepcopy(stock))
    return data


def test_future_resize_preserves_actual_cut_and_invalidates_downstream():
    data = input_data()
    data["evidence"] = [
        dict(
            id="prior_check",
            project_id="project",
            version_id="v1",
            kind="user_report",
            provenance="user",
            recorded_at=STAMP,
            description="Synthetic checkpoint record",
            verification_state="user_confirmed",
            checkpoint_ids=["check"],
        )
    ]
    original = deepcopy(data)
    result = run(data)
    assert result.status == "feasible"
    assert result.preserved_operation_ids == ("cut",)
    assert result.invalidated_checkpoint_ids == ("check",)
    assert result.invalidated_evidence_ids == ("prior_check",)
    assert result.plan.parent_version_id == "v1"
    assert result.plan.operations[0].id == "cut"
    assert result.plan.operations[1].id != "cut_brace"
    assert result.plan.operations[1].id in result.incomplete_operation_ids
    assert result.cost.new_irreversible_actions == 1
    assert result.cost.estimated_extra_minutes is None
    assert data == original
    assert run(data) == result


def test_completed_incompatible_cut_is_not_preserved():
    result = run(input_data(("cut", "cut_brace")))
    assert "irreversible_conflict" in codes(result)
    assert result.plan is None
    assert result.preserved_operation_ids == ("cut",)
    assert result.cost is None


def test_original_parent_cannot_return_after_cut():
    data = input_data()
    data["remaining_stock"] = deepcopy(data["base_plan"]["stocks"])
    assert "stock_exhausted" in codes(run(data))


def test_duplicate_completion_and_stock_rejected():
    data = input_data()
    data["events"].append(event(id="different_event"))
    assert "invalid_order" in codes(run(data))
    data = input_data()
    data["remaining_stock"] *= 2
    assert "invalid_reference" in codes(run(data))


@pytest.mark.parametrize(
    "change",
    [
        {"verification_state": "unknown"},
        {"version_id": "other"},
        {"evidence_ids": ["missing"]},
    ],
)
def test_uncertain_stale_missing_history_blocks(change):
    data = input_data()
    data["events"][0].update(change)
    assert run(data).status == "blocked"


def test_no_late_prerequisite_completion():
    assert "invalid_order" in codes(run(input_data(("cut_brace",))))


def test_impossible_resize_fails_before_ranking():
    data = input_data()
    data["patch"]["width_mm"] = 300
    bad = run(data)
    good = run(input_data())
    assert "geometry_invalid" in codes(bad)
    assert rank_feasible((bad, good)) == (good,)
    with pytest.raises(ValueError):
        rank_feasible((good,) * 4)


def test_damage_loss_cannot_be_spent_by_future_work():
    data = input_data()
    data["events"].append(
        event(
            None,
            id="loss",
            kind="observation",
            observation="Confirmed whole offcut lost",
        )
    )
    data["material_transactions"] = [
        dict(
            id="loss_tx",
            project_id="project",
            version_id="v1",
            operation_id="cut",
            source_stock_id="sheet",
            kind="waste",
            source_region_id="offcut",
            quantity=15600,
            unit="mm2",
            recorded_at=STAMP,
            physical_event_id="loss",
        )
    ]
    data["remaining_stock"][0]["usable_regions"] = []
    assert "stock_exhausted" in codes(run(data))


def test_fake_salvage_cannot_return_consumed_parent():
    data = input_data()
    data["material_transactions"] = [
        dict(
            id="fake",
            project_id="project",
            version_id="v1",
            operation_id="cut",
            source_stock_id="sheet",
            kind="salvage",
            source_region_id="root",
            output_region=data["base_plan"]["stocks"][0]["usable_regions"][0],
            quantity=24000,
            unit="mm2",
            recorded_at=STAMP,
            physical_event_id="event_cut",
        )
    ]
    assert "unsupported" in codes(run(data))


def test_real_salvage_of_lost_known_offcut_restores_only_that_region():
    data = input_data()
    data["events"].append(event(None, id="loss", kind="observation"))
    data["events"].append(event(None, id="recovered", kind="observation"))
    tx = dict(
        project_id="project",
        version_id="v1",
        operation_id="cut",
        source_stock_id="sheet",
        source_region_id="offcut",
        quantity=15600,
        unit="mm2",
        recorded_at=STAMP,
    )
    data["material_transactions"] = [
        tx | dict(id="lost", kind="waste", physical_event_id="loss"),
        tx
        | dict(
            id="salvaged",
            kind="salvage",
            physical_event_id="recovered",
            output_region=data["remaining_stock"][0]["usable_regions"][0],
        ),
    ]
    assert run(data).status == "feasible"


def joint_data():
    data = input_data()
    base = data["base_plan"]
    profile = dict(
        id="old",
        strategy="tape",
        status="tested",
        material="cardboard",
        thickness_min_mm=2,
        thickness_max_mm=4,
        tolerated_error_mm=0.5,
        test_evidence_ids=["synthetic_profile"],
    )
    base["joint_profiles"] = [profile, profile | dict(id="new")]
    base["constraints"]["allowed_profile_ids"] = ["old", "new"]
    base["joints"] = [
        dict(
            id="joint",
            profile_id="old",
            part_ids=["base", "brace"],
            confirmed_accessible=True,
        )
    ]
    unknown = dict(value=None, unit="mm", source="unknown", confirmed=False)
    tape = dict(
        id="tape",
        kind="tape",
        material="other_supported",
        width_mm=unknown,
        height_mm=unknown,
        thickness_mm=unknown,
        remaining_length_mm=measurement(100),
        condition="usable",
        usable_regions=[],
    )
    base["stocks"].append(tape)
    data["remaining_stock"].append(deepcopy(tape))
    base["operations"].append(
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
    data["patch"].update(
        id="replace_profile",
        kind="replace_joint_profile",
        target_id="joint",
        replacement_profile_id="new",
        width_mm=None,
        height_mm=None,
    )
    return data


def test_future_profile_edit_preserves_completed_cuts():
    data = joint_data()
    data["events"].append(event("cut_brace"))
    data["remaining_stock"][0]["usable_regions"] = []
    result = run(data)
    assert result.status == "feasible"
    assert result.preserved_operation_ids == ("cut", "cut_brace")
    assert result.newly_required_operation_ids == result.incomplete_operation_ids
    assert result.plan.joints[0].profile_id == "new"


def test_changed_completed_join_requires_explicit_undo():
    data = joint_data()
    data["events"].extend([event("cut_brace"), event("join")])
    data["remaining_stock"][0]["usable_regions"] = []
    data["remaining_stock"][1]["remaining_length_mm"] = measurement(20)
    result = run(data)
    assert result.status == "blocked"
    assert result.required_undo_operation_ids == ("join",)


def test_remaining_connector_cannot_be_resurrected():
    data = joint_data()
    data["events"].extend([event("cut_brace"), event("join")])
    data["remaining_stock"][0]["usable_regions"] = []
    assert "stock_exhausted" in codes(run(data))


def test_preservation_compares_interfaces_not_only_operation_ids():
    data = input_data(("cut", "cut_brace"))
    # Every operation ID remains identical, but the cut's part geometry changes.
    assert "irreversible_conflict" in codes(run(data))


def test_process_evidence_still_required():
    result = simulate_patch(ReplannerInput.model_validate(input_data()))
    assert "unsupported_profile" in codes(result)


def test_completed_part_replacement_uses_actual_spare_sheet_and_new_identities():
    data = joint_data()
    data["events"].append(event("cut_brace"))
    data["remaining_stock"][0]["usable_regions"] = []
    spare = deepcopy(data["base_plan"]["stocks"][0])
    spare["id"] = "spare"
    spare["usable_regions"][0]["id"] = "spare_region"
    data["base_plan"]["stocks"].append(spare)
    data["remaining_stock"].append(deepcopy(spare))
    data["patch"].update(
        id="replacement",
        kind="replace_part",
        target_id="brace",
        replacement_stock_id="spare",
        replacement_profile_id=None,
    )
    result = run(data)
    assert result.status == "feasible", result.blockers
    assert result.preserved_operation_ids == ("cut",)
    assert result.lost_part_ids == ("brace",)
    assert result.lost_operation_ids == ("cut_brace",)
    assert result.plan.parts[1].id == "brace"
    assert result.plan.parts[2].id != "brace"
    assert result.plan.parts[2].source_stock_id == "spare"
    assert "brace" not in result.plan.joints[0].part_ids
    assert "cut_brace" not in result.incomplete_operation_ids
    assert result.cost.irreversible_completed_actions_lost == 1
    assert result.cost.new_irreversible_actions == 1


def test_replacement_may_not_spend_already_consumed_original_sheet():
    data = input_data(("cut", "cut_brace"))
    data["patch"].update(
        kind="replace_part", replacement_stock_id="sheet", width_mm=None, height_mm=None
    )
    assert "stock_exhausted" in codes(run(data))


def test_ancestor_completion_requires_exact_compatible_original_plan():
    data = input_data()
    old = BuildPlan.model_validate(data["base_plan"])
    data["base_plan"].update(version_id="v2", parent_version_id="v1")
    data["patch"]["base_version_id"] = "v2"
    request = ReplannerInput.model_validate(data)
    assert "stale_version" in codes(
        simulate_patch(request, process=process(), allow_synthetic=True)
    )
    result = simulate_patch(
        request, process=process(), allow_synthetic=True, historical_plans=(old,)
    )
    assert result.status == "feasible"
    assert result.preserved_operation_ids == ("cut",)
    data["base_plan"]["parts"][0]["geometry"]["width"] = 61
    result = simulate_patch(
        ReplannerInput.model_validate(data),
        process=process(),
        allow_synthetic=True,
        historical_plans=(old,),
    )
    assert "irreversible_conflict" in codes(result)


def test_stand_repair_requires_family_manual_geometry_validation():
    data = input_data()
    data["base_plan"]["compiler_version"] = "triangular-tape-stand-v1"
    assert "unsupported" in codes(run(data))
    result = simulate_patch(
        ReplannerInput.model_validate(data),
        process=process(),
        allow_synthetic=True,
        family_validator=lambda plan: (),
    )
    assert result.status == "feasible"


def test_known_scoped_damage_can_be_replaced_without_rewriting_history():
    data = joint_data()
    data["events"].append(event("cut_brace"))
    data["remaining_stock"][0]["usable_regions"] = []
    spare = deepcopy(data["base_plan"]["stocks"][0])
    spare["id"] = "spare"
    spare["usable_regions"][0]["id"] = "spare_region"
    data["base_plan"]["stocks"].append(spare)
    data["remaining_stock"].append(deepcopy(spare))
    data["evidence"] = [
        dict(
            id="damage_photo",
            project_id="project",
            version_id="v1",
            kind="photo",
            provenance="user",
            recorded_at=STAMP,
            description="Synthetic confirmed damage",
            verification_state="user_confirmed",
            part_ids=["brace"],
        )
    ]
    data["events"].append(
        event(None, id="damage", kind="damage", evidence_ids=["damage_photo"])
    )
    data["patch"].update(
        id="replace_damage",
        kind="replace_part",
        target_id="brace",
        replacement_stock_id="spare",
        replacement_profile_id=None,
    )
    before = deepcopy(data)
    result = run(data)
    assert result.status == "feasible", result.blockers
    assert result.lost_part_ids == ("brace",)
    assert result.invalidated_evidence_ids == ("damage_photo",)
    assert data == before


def test_unrelated_uncertain_observation_does_not_erase_confirmed_work():
    data = input_data()
    data["evidence"] = [
        dict(
            id="unrelated",
            project_id="project",
            version_id="v1",
            kind="model_interpretation",
            provenance="model",
            recorded_at=STAMP,
            description="Uncertain cosmetic appearance of a different part",
            verification_state="unknown",
            part_ids=["base"],
        )
    ]
    data["events"].append(
        event(
            None,
            id="observation",
            kind="observation",
            verification_state="unknown",
            evidence_ids=["unrelated"],
        )
    )
    assert run(data).status == "feasible"


def test_noop_patch_is_not_ranked_as_a_free_repair():
    data = input_data()
    data["patch"]["width_mm"] = 30
    assert "no_feasible_repair" in codes(run(data))


def test_family_validator_rejection_blocks_ranking():
    from forma_domain.models import Blocker

    result = simulate_patch(
        ReplannerInput.model_validate(input_data()),
        process=process(),
        allow_synthetic=True,
        family_validator=lambda plan: (
            Blocker(code="geometry_invalid", message="Unsupported physical triangle"),
        ),
    )
    assert result.status == "blocked"
    assert not rank_feasible((result,))


def two_offcut_data():
    data = input_data()
    second = dict(id="strip", geometry=dict(x=0, y=100, width=65, height=20))
    data["base_plan"]["operations"][0]["effects"]["created_offcuts"].append(second)
    data["remaining_stock"][0]["usable_regions"].append(deepcopy(second))
    tx = dict(
        project_id="project",
        version_id="v1",
        operation_id="cut",
        source_stock_id="sheet",
        source_region_id="root",
        kind="offcut",
        unit="mm2",
        recorded_at=STAMP,
        physical_event_id="event_cut",
    )
    offcuts = data["base_plan"]["operations"][0]["effects"]["created_offcuts"]
    data["material_transactions"] = [
        tx
        | dict(
            id="tx_" + r["id"],
            output_region=r,
            quantity=r["geometry"]["width"] * r["geometry"]["height"],
        )
        for r in offcuts
    ]
    return data


def test_one_cut_may_record_each_distinct_offcut():
    assert run(two_offcut_data()).status == "feasible"


def test_same_offcut_recorded_twice_is_duplicate_accounting():
    data = two_offcut_data()
    data["material_transactions"].append(
        data["material_transactions"][0] | dict(id="again")
    )
    result = run(data)
    assert "stock_exhausted" in codes(result)
    assert any("Duplicate" in b.message for b in result.blockers)


def test_salvaged_offcut_can_be_lost_again():
    data = input_data()
    for name in ("loss", "recovered", "lost_again"):
        data["events"].append(event(None, id=name, kind="observation"))
    tx = dict(
        project_id="project",
        version_id="v1",
        operation_id="cut",
        source_stock_id="sheet",
        source_region_id="offcut",
        quantity=15600,
        unit="mm2",
        recorded_at=STAMP,
    )
    data["material_transactions"] = [
        tx | dict(id="lost", kind="waste", physical_event_id="loss"),
        tx
        | dict(
            id="salvaged",
            kind="salvage",
            physical_event_id="recovered",
            output_region=data["remaining_stock"][0]["usable_regions"][0],
        ),
        tx | dict(id="lost2", kind="waste", physical_event_id="lost_again"),
    ]
    data["remaining_stock"][0]["usable_regions"] = []
    result = run(data)
    assert not any("Duplicate" in b.message for b in result.blockers)
    assert result.lost_region_ids == ("offcut",)
    assert "stock_exhausted" in codes(result)


def test_future_resize_with_identical_unused_unknown_sheet():
    data = add_unused_unknown(input_data(), unused_unknown())
    original = deepcopy(data)
    result = run(data)
    assert result.status == "feasible", result.blockers
    assert result.preserved_operation_ids == ("cut",)
    retained = next(s for s in result.plan.stocks if s.id == "unused-unknown")
    assert retained.condition == "uncertain"
    assert retained.width_mm.value is None
    assert retained.height_mm.value is None
    assert retained.thickness_mm.value is None
    assert retained.remaining_length_mm.value is None
    assert not retained.width_mm.confirmed
    assert retained.usable_regions == ()
    assert data == original


def test_future_resize_with_identical_unused_unknown_connector():
    data = add_unused_unknown(input_data(), unused_unknown(kind="tape"))
    original = deepcopy(data)
    result = run(data)
    assert result.status == "feasible", result.blockers
    assert result.preserved_operation_ids == ("cut",)
    retained = next(s for s in result.plan.stocks if s.id == "unused-unknown")
    assert retained.kind == "tape"
    assert retained.condition == "uncertain"
    assert retained.remaining_length_mm.value is None
    assert not retained.remaining_length_mm.confirmed
    assert data == original


def test_unused_unknown_stock_with_unchanged_region_is_retained():
    stock = unused_unknown()
    stock["usable_regions"] = [
        dict(id="unused-region", geometry=dict(x=0, y=0, width=10, height=10))
    ]
    data = add_unused_unknown(input_data(), stock)
    result = run(data)
    assert result.status == "feasible", result.blockers
    retained = next(s for s in result.plan.stocks if s.id == "unused-unknown")
    assert [r.id for r in retained.usable_regions] == ["unused-region"]


def test_unknown_source_referenced_by_replacement_patch_still_blocks():
    data = add_unused_unknown(input_data(("cut", "cut_brace")), unused_unknown())
    data["patch"].update(
        kind="replace_part",
        target_id="brace",
        replacement_stock_id="unused-unknown",
        width_mm=None,
        height_mm=None,
    )
    result = run(data)
    assert result.status == "blocked"
    assert result.plan is None
    assert "needs_confirmation" in codes(result)
    assert any("unused-unknown" in b.target_ids for b in result.blockers)


@pytest.mark.parametrize("change", ["length", "condition", "material", "regions"])
def test_changed_unused_unknown_connector_is_not_treated_as_confirmed(change):
    data = add_unused_unknown(input_data(), unused_unknown(kind="tape"))
    remaining = data["remaining_stock"][-1]
    if change == "length":
        remaining["remaining_length_mm"] = measurement(100)
    elif change == "condition":
        remaining["condition"] = "usable"
    elif change == "material":
        remaining["material"] = "cardboard"
    else:
        remaining["usable_regions"] = [
            dict(
                id="invented-region",
                geometry=dict(x=0, y=0, width=10, height=10),
            )
        ]
    result = run(data)
    assert result.status == "blocked"
    assert result.plan is None
    assert "needs_confirmation" in codes(result)
    assert any("unused-unknown" in b.target_ids for b in result.blockers)
