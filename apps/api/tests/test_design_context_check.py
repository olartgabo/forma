"""Operator manifest check. Synthetic fixture values test the checker only."""

import json

from test_plans import stand_inputs

from forma_api import design_context_check
from forma_api.design_context import DesignContext

PROJECT = "project-check"
REVISION = "inventory-check-1"


def full_entry():
    _, _, _, parameters, process, profiles = stand_inputs(PROJECT)
    return DesignContext(
        project_id=PROJECT,
        inventory_revision_id=REVISION,
        process=process,
        parameters=parameters,
        joint_profiles=profiles,
        kerf_mm=2,
        edge_margin_mm=4,
    ).model_dump(mode="json")


def write(tmp_path, body):
    path = tmp_path / "context.json"
    path.write_text(
        body if isinstance(body, str) else json.dumps(body), encoding="utf-8"
    )
    return path


def run(capsys, *argv):
    code = design_context_check.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_template_is_scoped_and_leaves_every_measured_fact_empty(tmp_path, capsys):
    code, body = run(
        capsys, "template", "--project-id", PROJECT, "--revision-id", REVISION
    )
    assert code == 0
    (entry,) = body["contexts"]
    assert entry["project_id"] == PROJECT
    assert entry["inventory_revision_id"] == REVISION
    assert entry["process"] is None and entry["parameters"] is None
    assert entry["joint_profiles"] == []
    assert entry["kerf_mm"] is None and entry["edge_margin_mm"] is None
    # The unfilled template loads but reports every context fact as missing.
    path = write(tmp_path, body)
    code, report = run(
        capsys,
        "check",
        str(path),
        "--project-id",
        PROJECT,
        "--revision-id",
        REVISION,
    )
    assert code == 1
    assert report["status"] == "incomplete"
    assert report["blockers"] == [] and report["problems"] == []
    assert len(report["missing"]) == 5
    assert "Measured cutting process is not configured." in report["missing"]


def test_complete_entry_passes_only_for_its_exact_revision(tmp_path, capsys):
    path = write(tmp_path, {"contexts": [full_entry()]})
    args = ["check", str(path), "--project-id", PROJECT]
    code, report = run(capsys, *args, "--revision-id", REVISION)
    assert code == 0
    assert report == {
        "project_id": PROJECT,
        "inventory_revision_id": REVISION,
        "status": "complete",
        "blockers": [],
        "problems": [],
        "missing": [],
    }
    code, report = run(capsys, *args, "--revision-id", "inventory-check-2")
    assert code == 1
    assert report["blockers"] == [
        "No server-configured design context for this project and inventory revision."
    ]


def test_invalid_manifest_names_field_locations_without_values(tmp_path, capsys):
    entry = full_entry()
    entry["kerf_mm"] = -7.25
    path = write(tmp_path, {"contexts": [entry]})
    code, report = run(
        capsys,
        "check",
        str(path),
        "--project-id",
        PROJECT,
        "--revision-id",
        REVISION,
    )
    assert code == 1
    assert report["blockers"] == ["Configured design context is invalid."]
    assert any(p.startswith("contexts.0.kerf_mm:") for p in report["problems"])
    assert "-7.25" not in json.dumps(report)


def test_unreadable_and_duplicate_manifests_explain_the_resolver_verdict(
    tmp_path, capsys
):
    args = ["--project-id", PROJECT, "--revision-id", REVISION]
    path = write(tmp_path, "{not json")
    code, report = run(capsys, "check", str(path), *args)
    assert code == 1
    assert report["problems"][0].startswith("Manifest is not valid JSON (line 1)")
    path = write(tmp_path, {"contexts": [full_entry(), full_entry()]})
    code, report = run(capsys, "check", str(path), *args)
    assert report["problems"] == [
        "2 entries match this project and revision; keep exactly one."
    ]
    code, report = run(capsys, "check", str(tmp_path / "absent.json"), *args)
    assert report["problems"] == ["Manifest file does not exist or is not a file."]
