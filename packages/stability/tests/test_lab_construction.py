"""Generated proposals use actual mechanics and fabrication, without user events."""

import json
from urllib.error import HTTPError

import pytest
from forma_stability.lab import main
from forma_stability.lab_construction import run_generation
from test_lab import post

pytest_plugins = ["test_lab"]


def payload(kind="box", fabrication=False):
    return dict(
        shape=dict(kind=kind, width_mm=200.0, depth_mm=250.0, height_mm=100.0),
        synthetic_fabrication=fabrication,
    )


def test_generate_without_manual_stages_and_no_implicit_fabrication():
    result = run_generation(payload())
    steps = result["construction"]["steps"]
    assert len(steps) == 10
    assert sum(s["action"] == "join" for s in steps) == 4
    assert any(s["requires_external_support"] for s in steps)
    assert result["fabrication_report"] is None
    assert result["fabrication_basis"] == "not_assessed"
    assert result["fabrication_blockers"]
    assert all(not s["analysis"]["physical_evidence_ids"] for s in steps)


@pytest.mark.parametrize("kind", ["box", "ramp"])
def test_generated_rectangles_reach_real_fabrication_with_exact_bindings(kind):
    result = run_generation(payload(kind, True))
    report, plan = result["fabrication_report"], result["fabrication_plan"]
    assert report["status"] == "ready", result["fabrication_blockers"]
    assert report["order_status"] == "complete"
    assert not report["attached_joint_ids"]
    assert all(o["status"] != "completed" for o in report["operations"])
    operations = {o["id"] for o in plan["operations"]}
    bindings = {
        oid for step in result["construction"]["steps"] for oid in step["operation_ids"]
    }
    assert bindings == operations
    assert {o["operation_id"] for o in report["supported_order"]} == operations
    assert {o["operation_id"] for o in result["fabrication_instructions"]} == operations
    cut = next(o for o in plan["operations"] if o["type"] == "cut_rect")
    assert "200" in next(
        i["instruction"]
        for i in result["fabrication_instructions"]
        if i["operation_id"] == cut["id"]
    )
    assert (
        run_generation(payload(kind, True))["fabrication_report"]["snapshot"]
        == report["snapshot"]
    )


@pytest.mark.parametrize("kind", ["triangle", "concave"])
def test_nonrectangular_targets_generate_states_but_cannot_fabricate_bounding_box(kind):
    result = run_generation(payload(kind, True))
    assert len(result["construction"]["steps"]) == 2
    assert result["fabrication_report"] is None
    assert result["fabrication_blockers"]
    assert not any(s["operation_ids"] for s in result["construction"]["steps"])


def test_oversized_target_is_not_given_invented_larger_stock():
    request = payload("box", True)
    request["shape"]["width_mm"] = 2000.0
    result = run_generation(request)
    assert (
        result["fabrication_blockers"]
        or result["fabrication_report"]["status"] == "blocked"
    )


def test_generation_http_and_cli_recompute_saved_report(server, tmp_path, capsys):
    with post(server, "/generate-construction", payload("ramp", True)) as response:
        result = json.load(response)
        assert response.headers["Cache-Control"] == "no-store"
    expected = result["construction"]["target_hash"]
    result["construction"] = {"steps": [], "target_hash": "forged"}
    path = tmp_path / "construction.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    main(["--construction-input", str(path)])
    replay = json.loads(capsys.readouterr().out)
    assert replay["construction"]["target_hash"] == expected
    assert len(replay["construction"]["steps"]) == 4
    with pytest.raises(HTTPError) as error:
        post(
            server,
            "/generate-construction",
            payload(),
            Origin="https://foreign.invalid",
        )
    assert error.value.code == 403
