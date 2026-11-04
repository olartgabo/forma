"""Export real engine preview fixtures; offline software data, no physical evidence."""

import json
import sys
import tempfile
from pathlib import Path

from forma_stability.geometry import project_nominal_geometry
from forma_stability.lab_construction import run_generation

from forma_api.muse_construction import MuseConstructionResult

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/api/tests"))
from test_stability_route import connected  # noqa: E402
from test_stability_runtime import authorized  # noqa: E402


def proposal(width, depth, height):
    result = run_generation(
        {
            "shape": {
                "kind": "box",
                "width_mm": width,
                "depth_mm": depth,
                "height_mm": height,
            },
            "resources": {
                "project_id": "browser-project",
                "inventory_revision_id": "browser-inventory",
            },
        }
    )
    return MuseConstructionResult.model_validate(
        {
            "project_id": "browser-project",
            "inventory_revision_id": "browser-inventory",
            "status": "needs_measurement",
            "questions": [],
            "candidates": [
                {
                    "candidate_id": "engine-box",
                    "title": "Proposed organizer",
                    "rationale": "Offline real engine fixture; no physical pass.",
                    "status": "needs_measurement",
                    "construction": result["construction"],
                    "fabrication_plan": None,
                    "fabrication_report": None,
                    "blockers": result["fabrication_blockers"],
                }
            ],
            "diagnostics": {
                "status": "ok",
                "model": "offline-browser-fixture",
                "elapsed_ms": 1,
                "model_rounds": 0,
                "tool_executions": 0,
                "usage": None,
            },
        }
    ).model_dump(mode="json")


def export(path):
    with tempfile.TemporaryDirectory() as directory:
        fixture = connected.__wrapped__(Path(directory))
        try:
            setup = next(fixture)
            saved = authorized(setup)
            legacy = project_nominal_geometry(saved.version.plan).model_dump(
                mode="json"
            )
            legacy_version = saved.version.model_dump(mode="json")
        finally:
            fixture.close()
    data = {
        "generic_one": proposal(200, 240, 100),
        "generic_two": proposal(140, 180, 160),
        "legacy": legacy,
        "legacy_version": legacy_version,
    }
    Path(path).write_text(json.dumps(data), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python project-preview-fixture.py OUTPUT.json")
    export(sys.argv[1])
