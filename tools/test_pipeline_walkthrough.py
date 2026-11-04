"""Verify synthetic walkthrough boundaries and real connected engine replies."""

import importlib.util
import json
import sqlite3
from pathlib import Path

from forma_domain.models import BuildPlan


def test_walkthrough_runs_engines_without_physical_or_provider_evidence(tmp_path):
    script = Path(__file__).with_name("generate-pipeline-walkthrough.py")
    spec = importlib.util.spec_from_file_location("pipeline_walkthrough", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path, snapshot = module.generate(tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["physical_verification"] == "not_attempted"
    assert saved["provider_calls"] == 0
    assert len(path.read_bytes()) < 2_000_000
    assert len({s["id"] for s in saved["steps"]}) == len(saved["steps"])
    steps = {s["id"]: s for s in saved["steps"]}
    assert not [s for s in saved["steps"] if s["status"] == "error"]
    plan = BuildPlan.model_validate(saved["artifacts"]["plan"])
    assert plan.version_id == saved["version_id"]
    assert steps["synthesis-search"]["output"]["status"] == "candidates_found"
    assert steps["assembly-view"]["output"]["status"] == "ready"
    assert steps["fabrication"]["output"]["status"] == "ready"
    assert steps["stability-connected"]["output"]["status"] == "needs_measurement"
    assert steps["stage-8"]["output"]["report"]["physical_evidence_ids"] == []
    assert steps["stage-8"]["output"]["report"]["status"] == "modeled_pass"
    assert (
        steps["replanner-simulate"]["output"]["previews"][0]["simulation"]["status"]
        == "blocked"
    )
    assert (
        steps["replanner-resize"]["output"]["previews"][0]["simulation"]["status"]
        == "feasible"
    )
    assert (
        steps["photo-measure"]["output"]["result"]["measurement_status"]
        == "photo_estimate_unconfirmed"
    )
    assert steps["progress"]["output"]["events"] == []
    assert steps["progress"]["output"]["status"] == "not_started"
    with sqlite3.connect(snapshot["artifacts"]["database"]) as db:
        assert db.execute("SELECT COUNT(*) FROM progress_events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM progress_evidence").fetchone()[0] == 0
    assert "Authorization" not in path.read_text(encoding="utf-8")
