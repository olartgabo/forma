"""Saved modeled overlays are optional reads, never solver runs or physical work."""

import json
import sqlite3

import pytest
from test_plans import AUTH, OTHER
from test_stability_reports import measured, save

pytest_plugins = ["test_stability_route"]


def saved_view(connected):
    client, url, _, _ = connected
    body, cursor = measured(connected)
    saved = save(client, url, body, cursor, "assembly-overlay-report")
    assert saved.status_code == 200, saved.text
    project_id = saved.json()["analysis"]["project_id"]
    params = {
        key: body[key] for key in ("plan_version_id", "expected_inventory_revision_id")
    }
    params["expected_last_event_id"] = cursor
    return f"/api/projects/{project_id}/assembly-view", params, saved.json(), body


def test_current_overlay_is_scoped_read_only_and_never_recalculates(
    connected, monkeypatch
):
    client, _, _, directory = connected
    path, params, saved, _ = saved_view(connected)

    def forbidden(*args, **kwargs):
        raise AssertionError("Opening an assembly must not run stability analysis")

    monkeypatch.setattr("forma_api.stability_runtime.evaluate", forbidden)
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        before = tuple(db.iterdump())
    response = client.get(path, params=params, headers=AUTH)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["overlay_coverage"] == "available"
    assert view["overlay_report_id"] == saved["saved"]["report_id"]
    assert view["overlay_report"] == saved["analysis"]["report"]
    assert client.get(path, params=params, headers=OTHER).status_code == 404
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert tuple(db.iterdump()) == before


@pytest.mark.parametrize(
    "field",
    [
        "project_id",
        "plan_version_id",
        "inventory_revision",
        "history_cursor",
        "canonical_geometry_hash",
        "evidence_hash",
        "profile_hash",
    ],
)
def test_foreign_or_changed_saved_identity_is_not_displayed(connected, field):
    client, _, _, directory = connected
    path, params, _, _ = saved_view(connected)
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        row = db.execute("SELECT id, body FROM stability_reports").fetchone()
        record = json.loads(row[1])
        value = "f" * 64 if field.endswith("hash") else "different-state"
        record["report"]["identity"][field] = value
        record["analysis_input"]["identity"][field] = value
        db.execute(
            "UPDATE stability_reports SET body=? WHERE id=?",
            (json.dumps(record), row[0]),
        )
    response = client.get(path, params=params, headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"
    assert response.json()["overlay_coverage"] == "unavailable"


def test_new_measurements_hide_saved_overlays_without_blocking_geometry(connected):
    client, url, _, _ = connected
    path, params, _, body = saved_view(connected)
    changed = client.post(
        url.removesuffix("analyses") + "measurements",
        headers=AUTH,
        json=body
        | {
            "expected_last_event_id": params["expected_last_event_id"],
            "idempotency_key": "assembly-new-measurements",
        },
    )
    assert changed.status_code == 200, changed.text
    response = client.get(
        path,
        headers=AUTH,
        params=params | {"expected_last_event_id": changed.json()["last_event_id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"
    assert response.json()["overlay_coverage"] == "unavailable"


@pytest.mark.parametrize("mismatch", ["orientation", "dependencies", "producer"])
def test_saved_case_and_producer_must_match_current_snapshot(connected, mismatch):
    client, _, _, directory = connected
    path, params, _, _ = saved_view(connected)
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        row = db.execute("SELECT id, body FROM stability_reports").fetchone()
        record = json.loads(row[1])
        if mismatch == "orientation":
            record["report"]["overlays"][0]["orientation"] = "unrelated pose"
        elif mismatch == "dependencies":
            record["dependencies"]["engine"] = "old-engine"
        else:
            record["report"]["geometry_version"] = "old-producer"
        db.execute(
            "UPDATE stability_reports SET body=? WHERE id=?",
            (json.dumps(record), row[0]),
        )
    response = client.get(path, params=params, headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json()["overlay_coverage"] == "unavailable"
