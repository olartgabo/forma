"""Generated action graphs and stage physics, without a fabrication scheduler."""

import copy

import pytest
from forma_stability.construction import bind_operations, generate_construction
from forma_stability.generic_assembly import evaluate_assembly
from forma_stability.generic_examples import assembly_example

from forma_domain.construction_plan import (
    ConstructionOperationBinding,
    ConstructionRequest,
)
from forma_domain.generic_assembly import GenericAssemblyRequest


@pytest.mark.parametrize(
    "name,places,joins",
    [("triangle", 1, 0), ("concave", 1, 0), ("ramp", 2, 1), ("box", 5, 4)],
)
def test_distinct_targets_generate_graph_steps_without_authored_stage_sequence(
    name, places, joins
):
    target = assembly_example(name)
    original = target.model_dump_json()
    plan = generate_construction(ConstructionRequest(target=target))
    assert len(plan.steps) == places + joins + 1
    assert sum(s.action == "place" for s in plan.steps) == places
    assert sum(s.action == "join" for s in plan.steps) == joins
    assert plan.steps[-1].action == "inspect"
    assert plan.steps[0].part_ids == ("deck",)
    assert target.model_dump_json() == original
    previous = set()
    for step in plan.steps:
        assert set(step.depends_on_step_ids) <= previous
        assert step.analysis.snapshot.completed_operation_ids == ()
        assert step.analysis.snapshot.basis == "hypothetical"
        assert not step.analysis.physical_evidence_ids
        assert len(step.analysis.request.assembly.stages) == 1
        previous.add(step.step_id)
    final = evaluate_assembly(target)
    assert plan.steps[-1].analysis.present_part_ids == final.present_part_ids
    assert plan.steps[-1].analysis.active_joint_ids == final.active_joint_ids
    assert plan.steps[-1].analysis.world_overlays[0].signed_margin_m == pytest.approx(
        final.world_overlays[0].signed_margin_m
    )


def test_join_dependencies_follow_sources_and_unjoined_vertical_parts_need_support():
    plan = generate_construction(ConstructionRequest(target=assembly_example("box")))
    positions = {s.part_ids[0]: s.step_id for s in plan.steps if s.action == "place"}
    for step in plan.steps:
        if step.action == "place" and step.part_ids != ("deck",):
            assert step.requires_external_support
            assert any(
                "Self-support is not established" in text
                for text in step.unresolved_predicates
            )
            assert any(r.status == "needs_measurement" for r in step.analysis.reports)
            isolated = next(
                p for p in step.analysis.snapshot.parts if p.part_id == step.part_ids[0]
            )
            assert not isolated.contacts
        if step.action == "join":
            assert set(step.depends_on_step_ids) == {
                positions[pid] for pid in step.part_ids
            }
            assert not step.requires_external_support
    assert not plan.steps[-1].requires_external_support


def test_each_step_excludes_unplaced_sources_and_future_joints():
    plan = generate_construction(ConstructionRequest(target=assembly_example("box")))
    present = set()
    active = set()
    for step in plan.steps:
        if step.action == "place":
            present.update(step.part_ids)
        if step.action == "join":
            active.add(step.joint_id)
        assert set(step.analysis.present_part_ids) == present
        assert set(step.analysis.active_joint_ids) == active
        assert {p.part_id for p in step.analysis.snapshot.parts} == present
        assert sum(
            b.mass.value
            for i in step.analysis.inputs
            for b in i.mechanical_snapshot.bodies
        ) == pytest.approx(0.1 * len(present))


def test_input_collection_order_does_not_change_generated_action_sequence():
    raw = assembly_example("box").model_dump(mode="json")
    first = generate_construction(
        ConstructionRequest(target=GenericAssemblyRequest.model_validate(raw))
    )
    raw["assembly"]["parts"].reverse()
    raw["assembly"]["joints"].reverse()
    raw["snapshot"]["parts"].reverse()
    raw["snapshot"]["rigid_joint_ids"].reverse()
    second = generate_construction(
        ConstructionRequest(target=GenericAssemblyRequest.model_validate(raw))
    )
    assert [
        (s.action, s.part_ids, s.joint_id, s.depends_on_step_ids) for s in first.steps
    ] == [
        (s.action, s.part_ids, s.joint_id, s.depends_on_step_ids) for s in second.steps
    ]


def test_names_have_no_family_logic_and_contact_root_wins_over_lexical_order():
    raw = assembly_example("ramp").model_dump(mode="json")
    replacements = {
        "deck": "zz-support",
        "deck-face": "zz-face",
        "slope": "aa-panel",
        "slope-face": "aa-face",
        "join-slope": "connector-q",
    }

    def rename(value):
        if isinstance(value, dict):
            return {k: rename(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rename(v) for v in value]
        return replacements.get(value, value) if isinstance(value, str) else value

    plan = generate_construction(
        ConstructionRequest(target=GenericAssemblyRequest.model_validate(rename(raw)))
    )
    assert plan.steps[0].part_ids == ("zz-support",)
    assert plan.steps[1].part_ids == ("aa-panel",)
    assert plan.steps[2].joint_id == "connector-q"
    assert plan.steps[1].requires_external_support


def test_absent_contacts_are_not_replaced_by_hypothetical_holding():
    raw = assembly_example("ramp").model_dump(mode="json")
    raw["full_face_contact_facet_ids"] = []
    plan = generate_construction(
        ConstructionRequest(target=GenericAssemblyRequest.model_validate(raw))
    )
    assert all(s.requires_external_support for s in plan.steps)
    assert all(
        not part.contacts
        for step in plan.steps
        for part in step.analysis.snapshot.parts
    )
    assert all(
        r.status != "modeled_pass" for s in plan.steps for r in s.analysis.reports
    )


def test_disconnected_graph_retains_separate_components_at_final_step():
    raw = assembly_example("box").model_dump(mode="json")
    raw["assembly"]["joints"] = []
    for stage in raw["assembly"]["stages"]:
        stage["active_joint_ids"] = []
    raw["snapshot"]["rigid_joint_ids"] = []
    plan = generate_construction(
        ConstructionRequest(target=GenericAssemblyRequest.model_validate(raw))
    )
    assert len(plan.steps) == 6
    assert len(plan.steps[-1].analysis.component_part_ids) == 5
    assert plan.steps[-1].requires_external_support


def test_target_omissions_rejected_instead_of_silently_leaving_parts_unbuilt():
    raw = assembly_example("box").model_dump(mode="json")
    raw["stage_id"] = "base"
    raw["snapshot"]["parts"] = raw["snapshot"]["parts"][:1]
    raw["snapshot"]["rigid_joint_ids"] = []
    raw["uniform_mass_part_ids"] = ["deck"]
    with pytest.raises(ValueError, match="all declared source parts"):
        generate_construction(
            ConstructionRequest(target=GenericAssemblyRequest.model_validate(raw))
        )


def test_bindings_attach_without_recalculating_or_claiming_readiness(monkeypatch):
    import forma_stability.construction as construction

    plan = generate_construction(ConstructionRequest(target=assembly_example("ramp")))

    def forbidden(*args, **kwargs):
        raise AssertionError("Binding must not recompute physics")

    monkeypatch.setattr(construction, "evaluate_assembly", forbidden)
    bindings = (
        ConstructionOperationBinding(
            action="place", subject_id="deck", operation_id="cut-source"
        ),
        ConstructionOperationBinding(
            action="join", subject_id="join-slope", operation_id="tape-slope"
        ),
        ConstructionOperationBinding(
            action="inspect", subject_id="assembly", operation_id="inspect-complete"
        ),
    )
    result = bind_operations(plan, bindings)
    assert result.steps[0].operation_ids == ("cut-source",)
    assert result.steps[2].operation_ids == ("tape-slope",)
    assert result.steps[-1].operation_ids == ("inspect-complete",)
    assert all(a.analysis is b.analysis for a, b in zip(plan.steps, result.steps))
    assert all(not s.operation_ids for s in plan.steps)
    assert result.target_hash != plan.target_hash
    with pytest.raises(ValueError, match="generated action"):
        bind_operations(
            plan,
            (
                ConstructionOperationBinding(
                    action="place", subject_id="foreign", operation_id="bad"
                ),
            ),
        )


def test_final_load_demands_are_not_reused_for_an_intermediate_component():
    target = assembly_example("ramp")
    final = evaluate_assembly(target)
    raw = target.model_dump(mode="json")
    raw["snapshot"]["component_loads"] = [
        final.inputs[0].cases[0].model_dump(mode="json")
    ]
    plan = generate_construction(
        ConstructionRequest(
            target=GenericAssemblyRequest.model_validate(copy.deepcopy(raw))
        )
    )
    assert plan.steps[0].analysis.snapshot.component_loads == ()
    assert plan.steps[1].analysis.snapshot.component_loads == ()
    assert plan.steps[2].analysis.snapshot.component_loads
    assert any(
        "not transferred" in text for text in plan.steps[0].unresolved_predicates
    )
