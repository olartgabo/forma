"""Friendly editor uses canonical generic geometry, never preset-only mechanics."""

import copy
import json
from urllib.error import HTTPError

import pytest
from forma_stability.lab import main
from forma_stability.lab_assembly import editor_request, run_assembly
from test_lab import post

pytest_plugins = ["test_lab"]


def editor_case():
    def state(stage, x):
        return dict(
            stage_id=stage,
            translation_mm=[x, 0.0, 0.0],
            rotation_deg=[0.0, 0.0, 0.0],
            full_face_contact_assumed=True,
            rigid_body_assumed=True,
        )

    return dict(
        editor=dict(
            stages=[
                dict(id="lay-first", label="Place the triangle"),
                dict(id="lay-second", label="Add the five-sided panel"),
            ],
            panels=[
                dict(
                    id="triangle",
                    label="Triangle",
                    vertices_mm=[[0.0, 0.0], [120.0, 0.0], [0.0, 90.0]],
                    mass_g=30.0,
                    uniform_sheet_assumed=True,
                    first_stage=0,
                    states=[state("lay-first", 0.0), state("lay-second", 0.0)],
                ),
                dict(
                    id="pentagon",
                    label="Five sides",
                    vertices_mm=[
                        [0.0, 0.0],
                        [100.0, 0.0],
                        [130.0, 60.0],
                        [60.0, 110.0],
                        [0.0, 80.0],
                    ],
                    mass_g=45.0,
                    uniform_sheet_assumed=True,
                    first_stage=1,
                    states=[state("lay-second", 300.0)],
                ),
            ],
            joints=[],
            required_margin_mm=0.0,
        ),
        stage_index=0,
    )


def test_editor_triangle_and_pentagon_stage_membership_and_real_centroid():
    payload = editor_case()
    first = run_assembly(payload)["result"]
    assert first["present_part_ids"] == ["triangle"]
    assert "pentagon" in first["future_part_ids"]
    assert len(first["facets"][0]["vertices"]) == 3
    overlay = first["reports"][0]["overlays"][0]
    assert overlay["center_of_mass"]["x"] == pytest.approx(0.04)
    assert overlay["center_of_mass"]["y"] == pytest.approx(0.03)
    assert first["reports"][0]["status"] == "modeled_pass"
    second = run_assembly(payload | {"stage_index": 1})["result"]
    assert len(second["component_part_ids"]) == 2
    assert sorted(len(f["vertices"]) for f in second["facets"]) == [3, 5]
    assert all(r["status"] == "modeled_pass" for r in second["reports"])
    assert first["snapshot_hash"] != second["snapshot_hash"]


def test_editor_modifications_unknowns_and_pose_are_real_inputs():
    original = editor_case()
    baseline = run_assembly(original)["result"]
    changed = copy.deepcopy(original)
    changed["editor"]["panels"][0]["vertices_mm"][1][0] = 180.0
    result = run_assembly(changed)["result"]
    assert result["reports"][0]["overlays"][0]["center_of_mass"]["x"] == pytest.approx(
        0.06
    )
    assert result["snapshot_hash"] != baseline["snapshot_hash"]
    changed["editor"]["panels"][0]["mass_g"] = None
    assert run_assembly(changed)["result"]["reports"][0]["status"] != "modeled_pass"
    changed = copy.deepcopy(original)
    changed["editor"]["panels"][0]["states"][0]["rotation_deg"][0] = 30.0
    assert run_assembly(changed)["result"]["reports"][0]["status"] != "modeled_pass"


def test_editor_missing_stage_pose_or_unconfirmed_mass_distribution_cannot_pass():
    payload = editor_case()
    payload["editor"]["panels"][0]["states"] = payload["editor"]["panels"][0]["states"][
        1:
    ]
    with pytest.raises(ValueError, match="physical pose"):
        run_assembly(payload)
    payload = editor_case()
    payload["editor"]["panels"][0]["uniform_sheet_assumed"] = False
    assert run_assembly(payload)["result"]["reports"][0]["status"] != "modeled_pass"


def test_generic_feedback_cli_recomputes_and_rejects_observed(tmp_path, capsys):
    response = run_assembly(editor_case())
    response["result"] = {"reports": [{"status": "invented-pass"}]}
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(response), encoding="utf-8")
    main(["--assembly-input", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert result["result"]["reports"][0]["status"] == "modeled_pass"
    request = editor_request(editor_case()).model_dump(mode="json")
    request["snapshot"]["basis"] = "observed"
    with pytest.raises(ValueError, match="hypothetical"):
        run_assembly({"request": request})


def test_generic_http_calls_canonical_engine_and_rejects_bad_geometry(server):
    with post(server, "/evaluate-assembly", editor_case()) as response:
        result = json.load(response)
        assert result["result"]["reports"][0]["status"] == "modeled_pass"
        assert response.headers["Cache-Control"] == "no-store"
    invalid = editor_case()
    invalid["editor"]["panels"][0]["vertices_mm"] = [
        [0, 0],
        [100, 100],
        [100, 0],
        [0, 100],
    ]
    with pytest.raises(HTTPError) as error:
        post(server, "/evaluate-assembly", invalid)
    assert error.value.code == 422
    with pytest.raises(HTTPError) as error:
        post(
            server,
            "/evaluate-assembly",
            editor_case(),
            Origin="https://foreign.invalid",
        )
    assert error.value.code == 403
