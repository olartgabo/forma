"""Export actual #149 measurement-decision API responses for the browser check.

SYNTHETIC stock and profile evidence in a temporary database; no provider call
and nothing here is a physical result. Design settings come from the production
file resolver (FORMA_DESIGN_CONTEXT_PATH). The operator configures the first
revision only; later revisions get settings solely through the server's own
carry rule, never by rebinding here. The browser replays these responses.
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


def ruler(value):
    return {"value": value, "unit": "mm", "source": "user_ruler", "confirmed": True}


def fixture_function(fixture):
    """The plain generator behind a pytest fixture, for reuse outside pytest."""
    wrapped = getattr(fixture, "__pytest_wrapped__", None)
    if wrapped is not None:
        return wrapped.obj
    return getattr(fixture, "_get_wrapped_function", lambda: fixture.__wrapped__)()


def design_flow(t, directory):
    from forma_api.design_context import DesignContext

    manifest = Path(directory) / "design-context.json"
    os.environ["FORMA_DESIGN_CONTEXT_PATH"] = str(manifest)
    entries = []

    def configure(project, context):
        # The operator adds settings for exactly this revision.
        entries.append(
            DesignContext(
                project_id=project["id"],
                inventory_revision_id=project["revision_id"],
                **context,
            ).model_dump(mode="json")
        )
        manifest.write_text(json.dumps({"contexts": entries}), encoding="utf-8")

    app = t.create_app(Path(directory) / "design", t.TOKENS)
    with t.TestClient(app) as client:
        project, _, context = t.prepared(client)
        base = f"/api/projects/{project['id']}"
        state = {"project": project}

        def call(method, path, body=None, status=200):
            response = client.request(method, base + path, headers=t.AUTH, json=body)
            assert response.status_code == status, response.text
            return response.json()

        def save(stocks, key):
            result = call(
                "PUT",
                "/inventory",
                {
                    "expected_revision_id": state["project"]["revision_id"],
                    "idempotency_key": key,
                    "stocks": stocks,
                    "user_confirmed": True,
                },
            )
            state["project"] = result["project"]
            return result

        def identity(p):
            return {
                "expected_inventory_revision_id": p["revision_id"],
                "expected_active_version_id": None,
            }

        sheet, tape = project["stocks"]
        a = sheet | {"width_mm": UNKNOWN, "height_mm": UNKNOWN, "usable_regions": []}
        b = a | {"id": "synthetic-sheet-b"}
        before = save([a, b, tape], "inventory-unmeasured")["project"]
        configure(before, context)
        first = call("POST", "/measurement-decisions", identity(before))
        assert first["question"]["target"]["key"] == "stock:synthetic-sheet:width_mm"
        # The builder cannot measure sheet A: the next question is sheet B.
        declined = call(
            "POST",
            "/measurement-decisions/unavailable",
            identity(before)
            | {
                "expected_last_event_id": None,
                "question_id": first["question"]["question_id"],
                "target_key": first["question"]["target"]["key"],
                "idempotency_key": "unavailable-browser-1",
                "user_confirmed": True,
            },
        )
        assert declined["question"]["target"]["key"] == (
            "stock:synthetic-sheet-b:width_mm"
        )
        saved = save([a, b | {"width_mm": ruler(200)}, tape], "inventory-width")
        after = saved["project"]
        # No operator step for the new revision: the settings follow the
        # measured sheet through the production resolver.
        change = call(
            "POST",
            "/measurement-decisions/recalculate",
            identity(after) | {"baseline": declined},
        )
        assert change["after"]["question"]["target"]["key"] == (
            "stock:synthetic-sheet-b:height_mm"
        )
        assert before["revision_id"] in change["after"]["settings"][0]
        assert len(entries) == 1
        # A definite refusal: the inventory changed after the question.
        refused = client.put(
            base + "/inventory",
            headers=t.AUTH,
            json={
                "expected_revision_id": before["revision_id"],
                "idempotency_key": "inventory-stale-height",
                "stocks": [a, b, tape],
                "user_confirmed": True,
            },
        )
        assert refused.status_code == 409, refused.text
        return dict(
            before=before,
            after=after,
            saved=saved,
            first=first,
            declined=declined,
            change=change,
            refused=refused.json(),
            readiness=call("GET", "/designs/readiness"),
        )


def stand_flow(directory):
    route = importlib.import_module("test_stability_route")
    measurements = importlib.import_module("test_stability_measurements")
    t = importlib.import_module("test_plans")
    connected = fixture_function(route.connected)(Path(directory) / "stand")
    state = next(connected)
    client, url, payload, _ = state
    project_id = url.split("/")[2]
    base = f"/api/projects/{project_id}"
    project = client.get(base, headers=t.AUTH).json()
    request = {
        "expected_inventory_revision_id": project["revision_id"],
        "expected_active_version_id": project["active_version_id"],
    }
    body = measurements.capture_payload(state)
    question = client.post(
        base + "/measurement-decisions", headers=t.AUTH, json=request
    ).json()
    assert question["question"]["capture"] == "stability_measurements"
    # The builder records the values in the existing #146 form.
    recorded = client.post(measurements.measurement_url(url), headers=t.AUTH, json=body)
    assert recorded.status_code == 200, recorded.text
    change = client.post(
        base + "/measurement-decisions/recalculate",
        headers=t.AUTH,
        json=request | {"baseline": question},
    ).json()
    assert change["decision_changed"] is True
    plans = client.get(base + "/plans", headers=t.AUTH).json()
    stand = dict(
        project=client.get(base, headers=t.AUTH).json(),
        question=question,
        change=change,
        plans=plans,
    )
    connected.close()
    return stand


def main(output):
    with tempfile.TemporaryDirectory() as directory:
        os.environ["FORMA_DATA_DIR"] = directory
        os.environ.pop("FORMA_API_TOKENS", None)
        t = importlib.import_module("test_plans")
        from forma_api import synthesis_runtime

        synthesis_runtime.ALLOW_SYNTHETIC = True
        fixture = dict(
            label="SYNTHETIC software fixture; replayed server responses, no provider, no physical test",
            **design_flow(t, directory),
            stand=stand_flow(directory),
        )
    Path(output).write_text(json.dumps(fixture, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
