"""Export actual #149 measurement-decision API responses for the browser check.

SYNTHETIC stock and profile evidence in a temporary database; no provider call
and nothing here is a physical result. The browser replays these responses;
the inventory confirmation is the real route's response to the same stocks.
Usage: uv run --locked python apps/web/tests/active-measurement-fixture.py <output.json>
"""

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps/api/tests"))

UNKNOWN = {"value": None, "unit": "mm", "source": "unknown", "confirmed": False}


def main(output):
    with tempfile.TemporaryDirectory() as directory:
        os.environ["FORMA_DATA_DIR"] = directory
        os.environ.pop("FORMA_API_TOKENS", None)
        t = importlib.import_module("test_plans")
        from forma_api import synthesis_runtime
        from forma_api.design_context import (
            DesignContext,
            StaticDesignContextResolver,
        )

        synthesis_runtime.ALLOW_SYNTHETIC = True
        holder = {}
        synthesis_runtime.default_context_resolver = lambda: (
            StaticDesignContextResolver(
                holder["context"].model_copy(
                    update={"inventory_revision_id": holder["project"]["revision_id"]}
                )
            )
        )
        app = t.create_app(Path(directory), t.TOKENS)
        with t.TestClient(app) as client:
            project, _, context = t.prepared(client)
            holder["context"] = DesignContext(
                project_id=project["id"],
                inventory_revision_id=project["revision_id"],
                **context,
            )
            base = f"/api/projects/{project['id']}"

            def call(method, path, body=None):
                response = client.request(
                    method, base + path, headers=t.AUTH, json=body
                )
                assert response.status_code == 200, response.text
                return response.json()

            def save(stocks, key):
                result = call(
                    "PUT",
                    "/inventory",
                    {
                        "expected_revision_id": holder["project"]["revision_id"],
                        "idempotency_key": key,
                        "stocks": stocks,
                        "user_confirmed": True,
                    },
                )
                holder["project"] = result["project"]
                return result

            def identity(p):
                return {
                    "expected_inventory_revision_id": p["revision_id"],
                    "expected_active_version_id": None,
                }

            holder["project"] = project
            sheet, tape = project["stocks"]
            unmeasured = sheet | {
                "width_mm": UNKNOWN,
                "height_mm": UNKNOWN,
                "usable_regions": [],
            }
            before = save([unmeasured, tape], "inventory-unmeasured")["project"]
            first = call("POST", "/measurement-decisions", identity(before))
            assert first["question"]["target"]["key"].endswith(":width_mm")
            width = unmeasured | {
                "width_mm": {
                    "value": 200,
                    "unit": "mm",
                    "source": "user_ruler",
                    "confirmed": True,
                }
            }
            saved = save([width, tape], "inventory-width")
            after = saved["project"]
            change = call(
                "POST",
                "/measurement-decisions/recalculate",
                identity(after) | {"baseline": first},
            )
            second = change["after"]
            assert second["question"]["target"]["key"].endswith(":height_mm")
            unavailable = call(
                "POST",
                "/measurement-decisions/unavailable",
                identity(after)
                | {
                    "expected_last_event_id": None,
                    "question_id": second["question"]["question_id"],
                    "target_key": second["question"]["target"]["key"],
                    "idempotency_key": "unavailable-browser-1",
                    "user_confirmed": True,
                },
            )
            assert unavailable["outcome"] == "no_feasible_candidate"
            fixture = dict(
                label="SYNTHETIC software fixture; replayed server responses, no provider, no physical test",
                before=before,
                after=after,
                saved=saved,
                first=first,
                change=change,
                unavailable=unavailable,
                readiness=call("GET", "/designs/readiness"),
            )
    Path(output).write_text(json.dumps(fixture, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
