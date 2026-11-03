"""Export actual API responses from labeled analytic fixtures; no physical pass.

Usage: uv run --locked python apps/web/tests/stability-fixture.py <output.json>
"""

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Annotated

REPO = Path(__file__).resolve().parents[3]
SOURCES = {
    "forma_api": REPO / "apps/api/src",
    "forma_domain": REPO / "packages/domain/src",
    "forma_compiler": REPO / "packages/compiler/src",
    "forma_renderer": REPO / "packages/renderer/src",
    "forma_replanner": REPO / "packages/replanner/src",
    "forma_stability": REPO / "packages/stability/src",
}
for source in SOURCES.values():
    sys.path.insert(0, str(source))
sys.path.insert(0, str(REPO / "apps/api/tests"))


def provider_forbidden():
    raise AssertionError("synthetic fixture must not dispatch a model provider")


def main(output):
    with tempfile.TemporaryDirectory() as directory:
        os.environ["FORMA_DATA_DIR"] = directory
        os.environ.pop("FORMA_API_TOKENS", None)
        t = importlib.import_module("test_plans")
        analytic = importlib.import_module("test_stability_runtime").analytic
        route = importlib.import_module("forma_api.routes.stability")
        from fastapi import Header, HTTPException

        for name, source in SOURCES.items():
            path = Path(importlib.import_module(name).__file__).resolve()
            assert source.resolve() in path.parents, (name, path)
        for name in ("design", "diagnosis", "intake", "repair"):
            importlib.import_module(
                f"forma_api.{name}_runtime"
            ).default_gateway_factory = provider_forbidden

        def authenticate(authorization: Annotated[str | None, Header()] = None):
            if authorization == t.AUTH["Authorization"]:
                return "alice"
            raise HTTPException(401)

        store = t.ProjectStore(Path(directory))
        app = t.create_app(Path(directory), t.TOKENS)
        app.include_router(
            route.stability_router(store, authenticate, resolver=analytic),
            prefix="/analytic",
        )
        app.include_router(
            route.stability_router(
                store, authenticate, resolver=lambda s: analytic(s, unknown=True)
            ),
            prefix="/unknown",
        )
        with t.TestClient(app) as client:
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
            project = activated.json()["project"]
            readiness = client.get(base + "/designs/readiness", headers=t.AUTH)
            assert readiness.status_code == 200, readiness.text
            current = client.get(
                base + "/stability/context",
                params={"plan_version_id": version.version_id},
                headers=t.AUTH,
            )
            assert current.status_code == 200, current.text
            identity = current.json()
            payload = dict(
                plan_version_id=identity["plan_version_id"],
                expected_inventory_revision_id=identity["inventory_revision_id"],
                expected_last_event_id=identity["last_event_id"],
            )
            fixture = dict(
                project=project,
                version=version.model_dump(mode="json"),
                readiness=readiness.json(),
                fixture_label="SYNTHETIC ANALYTIC SOFTWARE VALIDATION ONLY; no physical pass",
            )
            for key, endpoint in [
                ("blocked_response", base),
                ("analytic_response", f"/analytic/{project['id']}"),
                ("unknown_response", f"/unknown/{project['id']}"),
            ]:
                response = client.post(
                    endpoint + "/stability/analyses", headers=t.AUTH, json=payload
                )
                assert response.status_code == 200, response.text
                fixture[key] = response.json()
            assert fixture["blocked_response"]["status"] == "needs_geometry"
            assert fixture["analytic_response"]["report"]["status"] == "modeled_pass"
            assert fixture["unknown_response"]["report"]["status"] != "modeled_pass"
        Path(output).write_text(json.dumps(fixture), encoding="utf-8")
    print("wrote labeled synthetic stability fixture from actual API responses")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
