"""Offline browser fixture: real geometry checks, no provider or physical evidence."""

import json
import sys
from pathlib import Path

from forma_stability.lab_construction import run_generation

from forma_api.muse_construction import MuseConstructionResult

result = run_generation(
    {
        "shape": {"kind": "box", "width_mm": 200, "depth_mm": 240, "height_mm": 100},
        "resources": {
            "project_id": "browser-project",
            "inventory_revision_id": "browser-inventory",
        },
        "piece_annotations": [
            {
                "part_id": "deck",
                "display_name": '<img src=x onerror="window.injected=true"> Base panel',
                "source": "model",
                "role": "base",
            }
        ],
    }
)
proposal = MuseConstructionResult.model_validate(
    {
        "project_id": "browser-project",
        "inventory_revision_id": "browser-inventory",
        "status": "needs_measurement",
        "questions": ["Measure the sheet thickness before cutting."],
        "candidates": [
            {
                "candidate_id": "candidate-one",
                "title": "Proposed organizer",
                "rationale": "Named panels based on the supplied target; this is an offline browser fixture.",
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
            "model_rounds": 1,
            "tool_executions": 0,
            "usage": None,
        },
    }
)
unknown = {"value": None, "unit": "mm", "source": "unknown", "confirmed": False}
project = {
    "id": "browser-project",
    "goal": "A desk organizer from my cardboard",
    "revision_id": "browser-inventory",
    "active_version_id": None,
    "inventory_confirmed": True,
    "requirements": None,
    "stocks": [
        {
            "id": "sheet-one",
            "kind": "sheet",
            "material": "cardboard",
            "width_mm": unknown,
            "height_mm": unknown,
            "thickness_mm": unknown,
            "remaining_length_mm": unknown,
            "condition": "uncertain",
            "usable_regions": [],
            "image_ids": [],
            "allowed_rotations_deg": [0, 90],
        }
    ],
}
Path(sys.argv[1]).write_text(
    json.dumps({"project": project, "result": proposal.model_dump(mode="json")}),
    encoding="utf-8",
)
