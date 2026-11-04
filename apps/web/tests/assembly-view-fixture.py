"""Export actual canonical/API responses from synthetic compiler inputs only."""

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for source in (
    "apps/api/src",
    "apps/api/tests",
    "packages/domain/src",
    "packages/compiler/src",
    "packages/renderer/src",
    "packages/replanner/src",
    "packages/fabrication/src",
    "packages/stability/src",
):
    sys.path.insert(0, str(REPO / source))


def main(output):
    with tempfile.TemporaryDirectory() as directory:
        os.environ["FORMA_DATA_DIR"] = directory
        os.environ.pop("FORMA_API_TOKENS", None)
        t = importlib.import_module("test_plans")
        progress_test = importlib.import_module("test_progress")
        for name in ("design", "diagnosis", "intake", "repair"):

            def forbidden():
                raise AssertionError("Assembly fixture cannot call providers")

            importlib.import_module(
                f"forma_api.{name}_runtime"
            ).default_gateway_factory = forbidden
        store = t.ProjectStore(Path(directory))
        with t.TestClient(t.create_app(Path(directory), t.TOKENS)) as client:
            project, body, context = t.prepared(client)
            version = (
                t.PlanService(store, allow_synthetic=True)
                .compile_preview("alice", project["id"], body, **context)
                .version
            )
            base = f"/api/projects/{project['id']}"
            activated = client.post(
                base + f"/plans/{version.version_id}/activate",
                headers=t.AUTH,
                json=t.approval(project),
            )
            assert activated.status_code == 200, activated.text
            data = {
                "project": activated.json()["project"],
                "version": version.model_dump(mode="json"),
                "readiness": client.get(
                    base + "/designs/readiness", headers=t.AUTH
                ).json(),
            }
            params = {
                "plan_version_id": version.version_id,
                "expected_inventory_revision_id": project["revision_id"],
                "expected_last_event_id": "",
            }
            data["context"] = client.get(
                base + "/stability/context",
                params={"plan_version_id": version.version_id},
                headers=t.AUTH,
            ).json()
            result = client.get(base + "/assembly-view", params=params, headers=t.AUTH)
            assert result.status_code == 200, result.text
            data["view"] = result.json()
            data["progress"] = client.get(
                base + f"/versions/{version.version_id}/progress", headers=t.AUTH
            ).json()
            current = progress_test.complete(client, version, 0)
            params["expected_last_event_id"] = current["last_event_id"]
            data["partial_view"] = client.get(
                base + "/assembly-view", params=params, headers=t.AUTH
            ).json()
            data["partial_context"] = client.get(
                base + "/stability/context",
                params={"plan_version_id": version.version_id},
                headers=t.AUTH,
            ).json()
            for index, operation in enumerate(version.plan.operations):
                if index == 0:
                    continue
                if operation.type == "functional_test":
                    break
                current = progress_test.complete(client, version, index)
            params["expected_last_event_id"] = current["last_event_id"]
            data["assembled_view"] = client.get(
                base + "/assembly-view", params=params, headers=t.AUTH
            ).json()
            data["assembled_context"] = client.get(
                base + "/stability/context",
                params={"plan_version_id": version.version_id},
                headers=t.AUTH,
            ).json()
            assert data["view"]["status"] == "ready"
            assert data["partial_view"]["geometry"] is None
            assert data["assembled_view"]["geometry"]["stage"] == "reported_assembled"
    Path(output).write_text(json.dumps(data), encoding="utf-8")
    print(
        "Exported canonical planned, unsupported partial and reported assembled software fixtures"
    )


if __name__ == "__main__":
    main(sys.argv[1])
