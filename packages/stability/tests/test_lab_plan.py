"""Compiled synthetic plan inspection reuses canonical geometry and real mechanics."""

import json
from pathlib import Path

import pytest
from forma_stability import lab_plan
from forma_stability.geometry import project_nominal_geometry
from forma_stability.lab import main

from forma_domain.models import BuildPlan


def request(prefix=6):
    data = json.loads(
        Path(lab_plan.__file__)
        .with_name("lab-stand-plan.json")
        .read_text(encoding="utf-8")
    )
    assert "SYNTHETIC" in data["label"]
    return dict(
        plan=data["plan"],
        completed_prefix=prefix,
        loads=dict(
            part_mass_g={p["id"]: 20.0 for p in data["plan"]["parts"]},
            device_mass_g=200.0,
            device_x_mm=0.0,
            device_y_mm=70.0,
            device_z_mm=110.0,
            required_margin_mm=0.0,
            tolerance_mm=0.000001,
            gravity_m_s2=9.81,
            uniform_mass_assumed=True,
            connector_shares_included=True,
            full_base_contact_assumed=True,
            rigid_device_attachment_assumed=True,
        ),
    )


def test_actual_compiled_plan_uses_exact_canonical_facets_and_source_mass_once():
    payload = request()
    result = lab_plan.inspect_plan(payload)
    reference = project_nominal_geometry(BuildPlan.model_validate(payload["plan"]))
    assert result["reference_geometry"] == reference.model_dump(mode="json")
    assert result["report"]["status"] == "modeled_pass"
    assert result["report"]["physical_evidence_ids"] == []
    assert len(result["reference_geometry"]["facets"]) == 4
    bodies = result["input"]["mechanical_snapshot"]["bodies"]
    stand_bodies = [b for b in bodies if b["body_kind"] == "stand_part"]
    assert len(stand_bodies) == 3
    assert sum(b["mass"]["value"] for b in stand_bodies) == pytest.approx(0.06)
    assert set(p for b in stand_bodies for p in b["source_part_ids"]) == set(
        reference.active_part_ids
    )
    assert result["input"]["mechanical_snapshot"]["contacts"][0]["polygon_world"] == [
        p.model_dump() for p in reference.ground_polygon
    ]
    assert all(not b["mass"]["confirmed"] for b in bodies)
    assert result["request"] == payload


@pytest.mark.parametrize("prefix", range(6))
def test_no_final_contacts_or_report_can_pass_an_unbuilt_or_partial_stage(prefix):
    result = lab_plan.inspect_plan(request(prefix))
    assert result["report"] is None
    assert result["input"] is None
    assert result["policy"] is None
    assert result["blockers"]
    assert result["reference_geometry"]["stage"] == "planned_preview"
    if prefix:
        assert result["selected_geometry"] is None


def test_operations_are_real_ordered_plan_data_and_test_never_passes():
    payload = request(8)
    result = lab_plan.inspect_plan(payload)
    assert [o["id"] for o in result["operations"]] == [
        o["id"] for o in payload["plan"]["operations"]
    ]
    assert all(not o["physical_test_simulated"] for o in result["operations"])
    assert all(o["instruction"] and o["tools"] for o in result["operations"])
    assert result["report"]["physical_evidence_ids"] == []
    assert (
        "stand-functional-test"
        not in result["selected_geometry"]["completed_operation_ids"]
    )
    assert result["selected_geometry"]["state_basis"] == "nominal"


@pytest.mark.parametrize(
    "field,status",
    [
        ("uniform_mass_assumed", "needs_measurement"),
        ("connector_shares_included", "needs_measurement"),
        ("full_base_contact_assumed", "needs_measurement"),
        ("rigid_device_attachment_assumed", "unsupported"),
    ],
)
def test_missing_distribution_connectors_contact_or_device_constraint_cannot_pass(
    field, status
):
    payload = request()
    payload["loads"][field] = False
    assert lab_plan.inspect_plan(payload)["report"]["status"] == status


def test_unknown_and_outside_device_inputs_reach_real_engine_and_bad_source_ids_reject():
    payload = request()
    payload["loads"]["device_mass_g"] = None
    assert lab_plan.inspect_plan(payload)["report"]["status"] == "needs_measurement"
    payload = request()
    payload["loads"]["device_y_mm"] = 1000.0
    result = lab_plan.inspect_plan(payload)
    assert result["report"]["status"] == "modeled_fail"
    assert result["report"]["overlays"][0]["signed_margin_m"] < 0
    payload["loads"]["part_mass_g"]["fake-part"] = 1.0
    with pytest.raises(ValueError, match="exactly one mass"):
        lab_plan.inspect_plan(payload)
    with pytest.raises(ValueError, match="prefix"):
        lab_plan.inspect_plan(request(9))


def test_plan_feedback_can_be_replayed_without_trusting_stored_report(tmp_path, capsys):
    payload = request()
    payload["loads"]["device_y_mm"] = 1000.0
    result = lab_plan.inspect_plan(payload)
    result["report"]["status"] = "modeled_pass"
    path = tmp_path / "feedback.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    main(["--plan-input", str(path)])
    assert json.loads(capsys.readouterr().out)["report"]["status"] == "modeled_fail"
