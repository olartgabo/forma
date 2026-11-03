"""Real compiler/fabrication checks for synthetic construction proposals only."""

import pytest
from forma_stability.construction import bind_operations, generate_construction
from forma_stability.construction_fabrication import build_fabrication
from forma_stability.generic_examples import assembly_example

from forma_domain.construction_plan import ConstructionRequest


def proposal(name="box"):
    return generate_construction(ConstructionRequest(target=assembly_example(name)))


@pytest.mark.parametrize("name", ("box", "ramp"))
def test_actual_fabrication_engine_orders_every_bound_rectangular_operation(name):
    construction = proposal(name)
    plan, report, bindings, blockers = build_fabrication(
        construction, allow_synthetic=True
    )
    assert not blockers
    assert report.status == "ready"
    assert not report.blockers
    assert report.snapshot.inputs_sha256
    assert len([op for op in plan.operations if op.type == "cut_rect"]) == 1
    assert len([op for op in plan.operations if op.type == "tape_joint"]) == len(
        construction.request.target.assembly.joints
    )
    assert sum(
        op.args.length_mm for op in plan.operations if op.type == "tape_joint"
    ) == 80 * len(plan.joints)
    bound = bind_operations(construction, bindings)
    flattened = [oid for step in bound.steps for oid in step.operation_ids]
    assert len(flattened) == len(set(flattened))
    assert set(flattened) == {op.id for op in plan.operations}
    assert all(op.requires_user_confirmation for op in plan.operations)
    assert report.snapshot.last_event_id is None
    assert report.attached_joint_ids == ()
    assert all(op.status != "completed" for op in report.operations)
    assert report.order_status == "complete"
    assert {step.operation_id for step in report.supported_order} == set(flattened)
    assert all(p.source_stock_id == plan.stocks[0].id for p in plan.parts)


def test_fixed_resources_do_not_expand_to_fit_target_and_tape_exhaustion_blocks():
    construction = proposal()
    plan, report, _, _ = build_fabrication(
        construction, allow_synthetic=True, sheet_width_mm=100, sheet_height_mm=100
    )
    assert plan.stocks[0].width_mm.value == 100
    assert report.status == "blocked"
    assert report.blockers
    plan, report, _, _ = build_fabrication(
        construction, allow_synthetic=True, tape_length_mm=1
    )
    assert plan.stocks[1].remaining_length_mm.value == 1
    assert report.status == "blocked"
    assert any(b.code == "stock_exhausted" for b in report.blockers)


@pytest.mark.parametrize("name", ("triangle", "concave"))
def test_nonrectangular_target_has_no_fabricated_cut_plan(name):
    plan, report, bindings, blockers = build_fabrication(
        proposal(name), allow_synthetic=True
    )
    assert plan is report is None
    assert not bindings
    assert "rectangular" in blockers[0]


def test_resource_opt_in_and_replay_identity_are_explicit():
    construction = proposal()
    assert build_fabrication(construction)[0] is None
    first = build_fabrication(construction, allow_synthetic=True)
    assert first == build_fabrication(construction, allow_synthetic=True)
    other = build_fabrication(construction, allow_synthetic=True, tape_length_mm=4000)
    assert first[0].version_id != other[0].version_id
    assert first[1].snapshot.inputs_sha256 != other[1].snapshot.inputs_sha256
    assert "synthetic" in first[0].compiler_version
    assert all(
        "SYNTHETIC" in note for note in first[0].joint_profiles[0].limitations[:1]
    )


def supplied(construction=None):
    """Software fixture of supplied records, not evidence of an actual build."""
    from forma_domain import models as m
    from forma_domain.construction_resources import ConstructionResources

    construction = construction or proposal()
    synthetic_plan = build_fabrication(construction, allow_synthetic=True)[0]
    project = construction.request.target.assembly.project_id
    evidence = m.Evidence(
        id="supplied-test",
        project_id=project,
        version_id="catalogue-v1",
        kind="physical_test",
        provenance="user",
        recorded_at=synthetic_plan.created_at,
        description="Test-only supplied record; no real physical observation",
        verification_state="user_confirmed",
    )
    profile = synthetic_plan.joint_profiles[0].model_copy(
        update={
            "test_evidence_ids": (evidence.id,),
            "limitations": ("Software fixture of supplied profile",),
        }
    )
    return ConstructionResources.model_validate(
        {
            "project_id": project,
            "inventory_revision_id": construction.request.target.snapshot.inventory_revision,
            "stocks": synthetic_plan.stocks,
            "declared_tools": ["ruler", "scissors"],
            "safe_tools_confirmed": True,
            "cut_process": {
                "kerf_min_mm": 2,
                "edge_margin_min_mm": 4,
                "evidence": [evidence],
            },
            "joint_profiles": [profile],
            "profile_evidence": [evidence],
            "joints": [
                {
                    "joint_id": j.id,
                    "profile_id": profile.id,
                    "stock_id": synthetic_plan.stocks[1].id,
                    "length_mm": 80,
                    "confirmed_accessible": True,
                }
                for j in synthetic_plan.joints
            ],
        }
    )


def test_supplied_materials_call_production_report_and_preserve_stock():
    construction = proposal()
    resources = supplied(construction)
    before = resources.model_dump_json()
    plan, report, bindings, blockers = build_fabrication(
        construction, resources=resources
    )
    assert not blockers
    assert plan.stocks == resources.stocks
    assert report.status == "ready", report.blockers
    assert report.order_status == "complete", report.order_blockers
    assert report.snapshot.inventory_revision_id == resources.inventory_revision_id
    assert report.snapshot.last_event_id is None
    assert report.attached_joint_ids == ()
    assert all(op.status != "completed" for op in report.operations)
    assert resources.model_dump_json() == before
    assert {b.operation_id for b in bindings} == {o.id for o in plan.operations}
    assert build_fabrication(construction, resources=resources) == (
        plan,
        report,
        bindings,
        blockers,
    )
    with pytest.raises(ValueError, match="synthetic"):
        build_fabrication(construction, resources=resources, allow_synthetic=True)


def test_multiple_actual_regions_and_rotation_are_allocated_without_expansion():
    from forma_domain import models as m

    construction = proposal()
    resources = supplied(construction)
    sheet, tape = resources.stocks
    # Five separate sheets: each target panel gets its own actual region. The
    # deck fits its sheet only rotated. Other source dimensions remain fixed.
    sizes = [(310, 210), (310, 110), (310, 110), (310, 110), (310, 110)]
    sheets = tuple(
        sheet.model_copy(
            update={
                "id": f"sheet-{i}",
                "width_mm": sheet.width_mm.model_copy(update={"value": w}),
                "height_mm": sheet.height_mm.model_copy(update={"value": h}),
                "usable_regions": (
                    m.Region(
                        id=f"region-{i}", geometry=m.Rect(x=0, y=0, width=w, height=h)
                    ),
                ),
            }
        )
        for i, (w, h) in enumerate(sizes)
    )
    resources = resources.model_copy(update={"stocks": sheets + (tape,)})
    plan, report, _, blockers = build_fabrication(construction, resources=resources)
    assert not blockers, blockers
    assert report.status == "ready", report.blockers
    assert len({p.source_stock_id for p in plan.parts}) == 5
    assert plan.parts[0].geometry.rotation_deg == 90
    assert plan.stocks == resources.stocks
    assert len([o for o in plan.operations if o.type == "cut_rect"]) == 5


@pytest.mark.parametrize(
    "field",
    [
        "cut_process",
        "active_version_id",
        "inventory_revision_id",
        "project_id",
        "joints",
    ],
)
def test_missing_process_foreign_scope_and_existing_work_block(field):
    resources = supplied()
    values = {
        "cut_process": None,
        "active_version_id": "active-v1",
        "inventory_revision_id": "foreign-revision",
        "project_id": "foreign-project",
        "joints": (),
    }
    # For project mismatch do not create an internally foreign evidence record.
    if field == "project_id":
        target = proposal().model_copy(
            update={
                "request": proposal().request.model_copy(
                    update={
                        "target": proposal().request.target.model_copy(
                            update={
                                "assembly": proposal().request.target.assembly.model_copy(
                                    update={"project_id": "foreign-project"}
                                )
                            }
                        )
                    }
                )
            }
        )
        result = build_fabrication(target, resources=resources)
    else:
        result = build_fabrication(
            proposal(), resources=resources.model_copy(update={field: values[field]})
        )
    assert result[0] is result[1] is None
    assert result[3]


def test_supplied_records_do_not_bypass_confirmation_or_profile_evidence():
    resources = supplied()
    sheet, tape = resources.stocks
    variants = [
        resources.model_copy(update={"safe_tools_confirmed": False}),
        resources.model_copy(update={"declared_tools": ()}),
        resources.model_copy(update={"profile_evidence": ()}),
        resources.model_copy(
            update={
                "stocks": (
                    sheet.model_copy(
                        update={
                            "thickness_mm": sheet.thickness_mm.model_copy(
                                update={"confirmed": False}
                            )
                        }
                    ),
                    tape,
                )
            }
        ),
        resources.model_copy(
            update={
                "stocks": (
                    sheet,
                    tape.model_copy(
                        update={
                            "remaining_length_mm": tape.remaining_length_mm.model_copy(
                                update={"value": 1}
                            )
                        }
                    ),
                )
            }
        ),
        resources.model_copy(
            update={
                "joints": tuple(
                    j.model_copy(update={"confirmed_accessible": None})
                    for j in resources.joints
                )
            }
        ),
    ]
    for variant in variants:
        plan, report, _, blockers = build_fabrication(proposal(), resources=variant)
        assert plan is not None and not blockers
        assert report.status == "blocked", variant
        assert report.blockers or report.order_blockers
    fixture_evidence = resources.cut_process.evidence[0].model_copy(
        update={
            "kind": "measurement",
            "provenance": "synthetic_fixture",
            "verification_state": "unknown",
        }
    )
    synthetic = resources.model_copy(
        update={
            "cut_process": resources.cut_process.model_copy(
                update={"evidence": (fixture_evidence,)}
            )
        }
    )
    assert build_fabrication(proposal(), resources=synthetic)[1].status == "blocked"


def test_short_actual_stock_stays_short_and_new_revision_changes_identity():
    resources = supplied()
    sheet, tape = resources.stocks
    tiny_region = sheet.usable_regions[0].model_copy(
        update={
            "geometry": sheet.usable_regions[0].geometry.model_copy(
                update={"width": 50, "height": 50}
            )
        }
    )
    tiny = resources.model_copy(
        update={
            "stocks": (
                sheet.model_copy(update={"usable_regions": (tiny_region,)}),
                tape,
            )
        }
    )
    assert build_fabrication(proposal(), resources=tiny)[0] is None
    first = build_fabrication(proposal(), resources=resources)
    changed = resources.model_copy(
        update={"declared_tools": ("ruler", "scissors", "marker")}
    )
    second = build_fabrication(proposal(), resources=changed)
    assert first[0].version_id != second[0].version_id
    assert first[1].snapshot.inputs_sha256 != second[1].snapshot.inputs_sha256


def test_supplied_polygon_and_too_long_joint_do_not_invent_operations():
    resources = supplied()
    polygon_resources = resources.model_copy(update={"joints": ()})
    result = build_fabrication(proposal("triangle"), resources=polygon_resources)
    assert result[0] is None and "nonrectangular" in result[3][0]
    bad_joint = resources.joints[0].model_copy(update={"length_mm": 10000})
    result = build_fabrication(
        proposal(),
        resources=resources.model_copy(
            update={"joints": (bad_joint, *resources.joints[1:])}
        ),
    )
    assert result[0] is None and "exceeds" in result[3][0]


def test_known_out_of_bounds_region_remains_a_compiler_blocker():
    resources = supplied()
    sheet, tape = resources.stocks
    # Deliberately corrupt a declared source region; allocation cannot sanitize
    # a contradictory actual inventory into a valid manufactured plan.
    sheet = sheet.model_copy(
        update={"width_mm": sheet.width_mm.model_copy(update={"value": 300})}
    )
    result = build_fabrication(
        proposal(), resources=resources.model_copy(update={"stocks": (sheet, tape)})
    )
    assert result[1].status == "blocked"
    assert any(b.code == "geometry_invalid" for b in result[1].blockers)


def test_region_cut_is_shown_at_earliest_generated_placement_not_input_order():
    target = assembly_example("box")
    target = target.model_copy(
        update={
            "assembly": target.assembly.model_copy(
                update={"parts": tuple(reversed(target.assembly.parts))}
            )
        }
    )
    construction = generate_construction(ConstructionRequest(target=target))
    plan, report, bindings, blockers = build_fabrication(
        construction, resources=supplied(construction)
    )
    assert not blockers and report.status == "ready"
    first_place = next(step for step in construction.steps if step.action == "place")
    assert first_place.part_ids[0] != target.assembly.parts[0].part_id
    cut = next(o for o in plan.operations if o.type == "cut_rect")
    binding = next(b for b in bindings if b.operation_id == cut.id)
    assert binding.subject_id == first_place.part_ids[0]
    bound = bind_operations(construction, bindings)
    assert cut.id in bound.steps[first_place.index].operation_ids
