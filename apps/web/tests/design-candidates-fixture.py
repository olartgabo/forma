"""Export actual #148 design-search API responses for the browser check.

SYNTHETIC stock and profile evidence in a temporary database; no model provider
is called and nothing here is a physical result.
Usage: uv run --locked python apps/web/tests/design-candidates-fixture.py <output.json>
"""

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps/api/tests"))


def provider_forbidden():
    raise AssertionError("synthetic fixture must not dispatch a model provider")


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

        for name in ("design", "diagnosis", "intake", "repair"):
            importlib.import_module(
                f"forma_api.{name}_runtime"
            ).default_gateway_factory = provider_forbidden
        synthesis_runtime.ALLOW_SYNTHETIC = True
        holder = {}
        synthesis_runtime.default_context_resolver = lambda: (
            StaticDesignContextResolver(holder["context"])
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

            def get(path):
                response = client.get(base + path, headers=t.AUTH)
                assert response.status_code == 200, response.text
                return response.json()

            def post(path, body):
                response = client.post(base + path, headers=t.AUTH, json=body)
                assert response.status_code == 200, response.text
                return response.json()

            identity = dict(
                expected_inventory_revision_id=project["revision_id"],
                expected_active_version_id=None,
                expected_last_event_id=None,
            )
            search = post("/synthesis/search", identity)
            assert search["status"] == "candidates_found"
            assert len(search["candidates"]) == 2
            first, second = search["candidates"]
            depths = next(
                d
                for d in search["domains"]
                if d["parameter"] == "footprint_depth_mm"
                and d["sheet_stock_id"] == first["design"]["sheet_stock_id"]
            )
            deeper = depths["lower_mm"] + depths["step_mm"] * (depths["count"] - 1)
            probe = post(
                "/synthesis/probe",
                identity
                | dict(
                    search_id=search["search_id"],
                    design=first["design"],
                    parameter="footprint_depth_mm",
                    value_mm=deeper,
                ),
            )
            assert probe["status"] == "evaluated"
            plans_before = get("/plans")
            readiness = get("/designs/readiness")
            select = post(
                "/synthesis/select",
                identity
                | dict(
                    search_id=search["search_id"],
                    design=second["design"],
                    idempotency_key="browser-select-key",
                    user_selected=True,
                ),
            )
            assert select["status"] == "accepted"
            version_id = select["version"]["version_id"]
            fixture = dict(
                label="SYNTHETIC software fixture; replayed server responses, no provider, no physical test",
                project=project,
                readiness=readiness,
                search=search,
                probe=probe,
                probe_value=deeper,
                select=select,
                plans_before=plans_before,
                plans_after=get("/plans"),
                version=get(f"/versions/{version_id}"),
                activation=dict(
                    project=project | {"active_version_id": version_id},
                    replayed=False,
                ),
            )
    Path(output).write_text(json.dumps(fixture, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
