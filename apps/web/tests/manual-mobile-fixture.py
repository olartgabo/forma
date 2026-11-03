"""Export the synthetic compiled-manual fixture used by manual-mobile.browser.mjs.

Runs the existing apps/api/tests/test_plans.py inputs through the real FastAPI
app and offline compiler/renderer. It uses no provider, secret or physical result.

Usage: python manual-mobile-fixture.py <output JSON path outside tracked source>
"""

import importlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SOURCES = {
    "forma_api": REPO / "apps/api/src",
    "forma_domain": REPO / "packages/domain/src",
    "forma_compiler": REPO / "packages/compiler/src",
    "forma_renderer": REPO / "packages/renderer/src",
    "forma_replanner": REPO / "packages/replanner/src",
    "forma_fabrication": REPO / "packages/fabrication/src",
}
# A shared virtual environment may install another checkout in editable mode.
for source in SOURCES.values():
    sys.path.insert(0, str(source))


def provider_forbidden():
    raise AssertionError("fixture export must not dispatch a model provider")


def main(output):
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    with tempfile.TemporaryDirectory() as directory:
        # Importing forma_api.main builds its default app; keep its data off the checkout.
        os.environ["FORMA_DATA_DIR"] = directory
        os.environ.pop("FORMA_API_TOKENS", None)
        spec = importlib.util.spec_from_file_location(
            "test_plans", REPO / "apps/api/tests/test_plans.py"
        )
        t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t)
        for name, source in SOURCES.items():
            module_path = Path(importlib.import_module(name).__file__).resolve()
            assert source.resolve() in module_path.parents, (name, module_path)
        for name in ("design", "diagnosis", "intake", "repair"):
            runtime = importlib.import_module(f"forma_api.{name}_runtime")
            runtime.default_gateway_factory = provider_forbidden
        data = Path(directory)
        with t.TestClient(t.create_app(data, t.TOKENS)) as client:
            project, body, context = t.prepared(client)
            version = (
                t.PlanService(t.ProjectStore(data), allow_synthetic=True)
                .compile_preview("alice", project["id"], body, **context)
                .version
            )
            response = client.get(
                f"/api/projects/{project['id']}/designs/readiness", headers=t.AUTH
            )
            assert response.status_code == 200, response.status_code
            readiness = response.json()
            assert readiness["project_id"] == project["id"]
            assert readiness["inventory_revision_id"] == project["revision_id"]
            assert isinstance(readiness["missing_inputs"], list)
            assert isinstance(readiness["blockers"], list)
            assert len(version.manual.panels) == 8, len(version.manual.panels)
            assert all(
                panel.svg.lstrip().startswith("<svg") for panel in version.manual.panels
            )
            # UI-only reference so the web client loads the manual; not a real activation.
            project["active_version_id"] = version.version_id
            fixture = {
                "project": project,
                "version": version.model_dump(mode="json"),
                "readiness": readiness,
            }
    Path(output).write_text(json.dumps(fixture), encoding="utf-8")
    print(f"wrote fixture with {len(fixture['version']['manual']['panels'])} panels")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) == 2 else None)
