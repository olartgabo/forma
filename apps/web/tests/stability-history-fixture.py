"""Export actual saved-report API responses for the browser check; no physical pass.

Synthetic user measurements in a temporary database; MetaMuse is an offline
scripted transport through the real gateway, never a provider call.
Usage: uv run --locked python apps/web/tests/stability-history-fixture.py <output.json>
"""

import copy
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Annotated

REPO = Path(__file__).resolve().parents[3]
for package in ("api", "domain", "compiler", "renderer", "replanner", "stability"):
    root = REPO / ("apps" if package == "api" else "packages") / package / "src"
    sys.path.insert(0, str(root))
sys.path.insert(0, str(REPO / "apps/api/tests"))


def provider_forbidden():
    raise AssertionError("synthetic fixture must not dispatch a model provider")


def main(output):
    with tempfile.TemporaryDirectory() as directory:
        os.environ["FORMA_DATA_DIR"] = directory
        os.environ.pop("FORMA_API_TOKENS", None)
        t = importlib.import_module("test_plans")
        m = importlib.import_module("test_stability_measurements")
        scripted = importlib.import_module("test_stability_muse").Scripted
        from fastapi import Header, HTTPException

        from forma_api.model_gateway import MetaGateway
        from forma_api.routes.stability_muse import stability_muse_router

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
            stability_muse_router(
                store,
                authenticate,
                gateway_factory=lambda: MetaGateway(scripted(), max_retries=0),
            ),
            prefix="/scripted",
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
            payload = dict(
                plan_version_id=version.version_id,
                expected_inventory_revision_id=project["revision_id"],
                expected_last_event_id=None,
            )
            measurement = m.capture_payload(
                (
                    client,
                    f"/test/{project['id']}/stability/analyses",
                    payload,
                    Path(directory),
                )
            )

            def post(path, json_body):
                response = client.post(base + path, headers=t.AUTH, json=json_body)
                assert response.status_code == 200, response.text
                return response.json()

            def get(path, **params):
                response = client.get(base + path, headers=t.AUTH, params=params)
                assert response.status_code == 200, response.text
                return response.json()

            first_event = post("/stability/measurements", measurement)["last_event_id"]
            identity = payload | {"expected_last_event_id": first_event}
            first = post(
                "/stability/reports", identity | {"idempotency_key": "fixture-r1"}
            )
            changed = copy.deepcopy(measurement)
            changed.update(
                expected_last_event_id=first_event,
                idempotency_key="fixture-measurement-2",
            )
            changed["measurements"]["cases"][1]["device"]["center_of_mass_m"]["y"] = (
                0.01
            )
            second_event = post("/stability/measurements", changed)["last_event_id"]
            identity = payload | {"expected_last_event_id": second_event}
            fixture = dict(
                fixture_label="SYNTHETIC SOFTWARE VALIDATION ONLY; offline scripted MetaMuse; no physical pass",
                project=project,
                version=version.model_dump(mode="json"),
                readiness=get("/designs/readiness"),
                progress=get(f"/versions/{version.version_id}/progress"),
                context=get("/stability/context", plan_version_id=version.version_id),
                save=post(
                    "/stability/reports", identity | {"idempotency_key": "fixture-r2"}
                ),
            )
            old_id = first["saved"]["report_id"]
            new_id = fixture["save"]["saved"]["report_id"]
            assert old_id != new_id
            fixture["history"] = get("/stability/reports")
            assert [
                r["freshness"]["current"] for r in fixture["history"]["reports"]
            ] == [
                True,
                False,
            ]
            fixture["old_detail"] = get(f"/stability/reports/{old_id}")
            fixture["comparison"] = get(
                "/stability/report-comparison", first=new_id, second=old_id
            )
            assert fixture["comparison"]["comparable"] is True
            muse = client.post(
                f"/scripted/{project['id']}/stability/muse-explanations",
                headers=t.AUTH,
                json=identity
                | dict(
                    idempotency_key="fixture-muse-1",
                    mode="analyze_current",
                    provider_context_consented=True,
                ),
            )
            assert muse.status_code == 200, muse.text
            fixture["muse"] = muse.json()
            assert fixture["muse"]["report"]["report_id"] == new_id
            fixture["new_detail"] = get(f"/stability/reports/{new_id}")
            report = fixture["new_detail"]["saved"]["report"]
            assert fixture["muse"]["explanation"]["summary"].startswith(
                f"Saved report status: {report['status']}."
            )
            assert all(
                row in report["results"] for row in fixture["muse"]["focused_results"]
            )
            # Another tab records changed measurements after the explanation.
            third = copy.deepcopy(changed)
            third.update(
                expected_last_event_id=second_event,
                idempotency_key="fixture-measurement-3",
            )
            third["measurements"]["stand"]["mass_kg"] = 0.12
            post("/stability/measurements", third)
            fixture["history_after_change"] = get("/stability/reports")
            assert not any(
                r["freshness"]["current"]
                for r in fixture["history_after_change"]["reports"]
            )
            # Retrying the completed request replays it without a provider call.
            replay = client.post(
                f"/scripted/{project['id']}/stability/muse-explanations",
                headers=t.AUTH,
                json=identity
                | dict(
                    idempotency_key="fixture-muse-1",
                    mode="analyze_current",
                    provider_context_consented=True,
                ),
            )
            assert replay.status_code == 200, replay.text
            fixture["muse_replay"] = replay.json()
            assert fixture["muse_replay"]["replayed"] is True
            assert fixture["muse_replay"]["report"]["freshness"]["current"] is False
        Path(output).write_text(json.dumps(fixture), encoding="utf-8")
    print("wrote labeled synthetic saved-report fixture from actual API responses")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
