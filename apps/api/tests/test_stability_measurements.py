"""Synthetic user reports exercise the real measured adapter, not physical evidence."""

import copy
import sqlite3
from datetime import UTC, datetime

import pytest
from test_plans import AUTH, OTHER
from test_progress import complete
from test_stability_runtime import authorized

from forma_api.projects import ProjectStore
from forma_domain.models import EvidenceInvalidation, PhysicalEvent

pytest_plugins = ["test_stability_route"]


def capture_payload(connected, *, assembled=True):
    client, url, payload, _ = connected
    snap = authorized(connected)
    current = None
    if assembled:
        for index in range(6):
            current = complete(client, snap.version, index)

    def measured(mass, y, z):
        return dict(
            mass_kg=mass,
            center_of_mass_m=dict(x=0.0, y=y, z=z),
            mass_resolution_kg=0.001,
            position_resolution_m=0.001,
            method="Synthetic software scale/balance fixture; not physical observations",
        )

    width = snap.version.plan.parts[0].geometry.width / 1000
    base = next(p for p in snap.version.plan.parts if p.id == "stand-base")
    depth = base.geometry.height / 1000
    measurements = dict(
        stand=measured(0.1, depth / 2, 0.02),
        cases=[
            dict(
                orientation=o,
                device=measured(0.2, depth / 2, 0.08),
                pose_description="Synthetic fixed device position",
            )
            for o in ("portrait", "landscape")
        ],
        support=dict(
            x_min_m=-width / 2,
            x_max_m=width / 2,
            y_min_m=0.0,
            y_max_m=depth,
            resolution_m=0.001,
            method="Synthetic ruler contact rectangle",
        ),
        required_margin_m=0.002,
        stand_includes_all_parts_and_connectors=True,
        actual_contacts_confirmed=True,
        rigid_assembly_assumed=True,
        horizontal_surface_confirmed=True,
        stationary_device_assumed=True,
        gravity_only_assumed=True,
    )
    return payload | dict(
        expected_last_event_id=current["last_event_id"] if current else None,
        idempotency_key="measurements-001",
        user_confirmed=True,
        measurements=measurements,
    )


def measurement_url(url):
    return url.removesuffix("analyses") + "measurements"


def analyze(client, url, body, event_id):
    return client.post(
        url,
        headers=AUTH,
        json={k: body[k] for k in ("plan_version_id", "expected_inventory_revision_id")}
        | {"expected_last_event_id": event_id},
    )


def test_real_default_unknown_save_compute_edit_and_stale_reject(connected):
    client, url, _, directory = connected
    body = capture_payload(connected)
    missing = analyze(client, url, body, body["expected_last_event_id"])
    assert missing.json()["status"] == "needs_measurement"
    saved = client.post(measurement_url(url), headers=AUTH, json=body)
    assert saved.status_code == 200, saved.text
    result = saved.json()
    stale = analyze(client, url, body, body["expected_last_event_id"])
    assert stale.status_code == 409
    computed = analyze(client, url, body, result["last_event_id"])
    assert computed.status_code == 200, computed.text
    report = computed.json()["report"]
    assert report["status"] == "modeled_pass"
    assert {r["case_id"] for r in report["results"]} == {"portrait", "landscape"}
    assert len(report["overlays"]) == 2
    assert report["physical_evidence_ids"] == []
    assert any("not conservative" in w for w in report["input_warnings"])
    assert any("assumed" in a for a in report["assumption_ids"])
    changed = copy.deepcopy(body)
    changed.update(
        expected_last_event_id=result["last_event_id"],
        idempotency_key="measurements-002",
    )
    changed["measurements"]["cases"][1]["device"]["center_of_mass_m"]["x"] = 1.0
    saved2 = client.post(measurement_url(url), headers=AUTH, json=changed)
    assert saved2.status_code == 200, saved2.text
    failure = analyze(client, url, body, saved2.json()["last_event_id"]).json()[
        "report"
    ]
    assert failure["status"] == "modeled_fail"
    assert any(
        r["case_id"] == "landscape" and r["status"] == "modeled_fail"
        for r in failure["results"]
    )
    assert failure["cache_hash"] != report["cache_hash"]
    assert analyze(client, url, body, result["last_event_id"]).status_code == 409
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert (
            db.execute("SELECT count(*) FROM stability_measurements").fetchone()[0] == 2
        )
        assert (
            db.execute(
                "SELECT count(*) FROM progress_events WHERE json_extract(body,'$.kind')='measurement'"
            ).fetchone()[0]
            == 2
        )
        assert (
            db.execute(
                "SELECT count(*) FROM progress_events WHERE json_extract(body,'$.kind')='test'"
            ).fetchone()[0]
            == 0
        )


def test_idempotency_replays_exact_request_without_duplicate_evidence(connected):
    client, url, _, directory = connected
    body = capture_payload(connected)
    first = client.post(measurement_url(url), headers=AUTH, json=body)
    second = client.post(measurement_url(url), headers=AUTH, json=body)
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json() | {"replayed": True}
    changed = copy.deepcopy(body)
    changed["measurements"]["required_margin_m"] = 0.003
    assert (
        client.post(measurement_url(url), headers=AUTH, json=changed).status_code == 409
    )
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert (
            db.execute("SELECT count(*) FROM stability_measurements").fetchone()[0] == 1
        )


@pytest.mark.parametrize(
    "change",
    [
        "single_case",
        "duplicate_case",
        "no_connector_confirmation",
        "forged_confirmation",
        "bad_support",
        "bad_mass",
        "foreign_version",
        "stale_history",
        "stale_inventory",
    ],
)
def test_invalid_or_stale_capture_rejected_without_writes(connected, change):
    client, url, _, directory = connected
    body = capture_payload(connected)
    expected = 422
    if change == "single_case":
        body["measurements"]["cases"].pop()
    elif change == "duplicate_case":
        body["measurements"]["cases"][1]["orientation"] = "portrait"
    elif change == "no_connector_confirmation":
        body["measurements"]["stand_includes_all_parts_and_connectors"] = False
    elif change == "forged_confirmation":
        body["user_confirmed"] = 1
    elif change == "bad_support":
        body["measurements"]["support"]["x_max_m"] = 100.0
    elif change == "bad_mass":
        body["measurements"]["stand"]["mass_kg"] = -1.0
    elif change == "foreign_version":
        body["plan_version_id"] = "foreign"
        expected = 404
    elif change == "stale_history":
        body["expected_last_event_id"] = "stale"
        expected = 409
    elif change == "stale_inventory":
        body["expected_inventory_revision_id"] = "stale"
        expected = 409
    response = client.post(measurement_url(url), headers=AUTH, json=body)
    assert response.status_code == expected, response.text
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert (
            db.execute("SELECT count(*) FROM stability_measurements").fetchone()[0] == 0
        )


def test_capture_requires_actual_reported_assembly_and_authentication(connected):
    client, url, _, _ = connected
    body = capture_payload(connected, assembled=False)
    assert client.post(measurement_url(url), json=body).status_code == 401
    assert (
        client.post(measurement_url(url), headers=OTHER, json=body).status_code == 404
    )
    response = client.post(measurement_url(url), headers=AUTH, json=body)
    assert response.status_code == 422
    assert "Record assembly" in response.text


def test_new_history_requires_recapture_and_does_not_reuse_measurements(connected):
    client, url, _, directory = connected
    body = capture_payload(connected)
    saved = client.post(measurement_url(url), headers=AUTH, json=body).json()
    project_id = url.split("/")[2]
    with ProjectStore(directory).transaction() as db:
        event = PhysicalEvent(
            id="later-observation",
            project_id=project_id,
            version_id=body["plan_version_id"],
            kind="observation",
            actor="user",
            observation="Synthetic changed conditions",
            verification_state="unknown",
            recorded_at=datetime.now(UTC),
        )
        db.execute(
            "INSERT INTO progress_events VALUES (?,?,?,?)",
            (event.id, project_id, body["plan_version_id"], event.model_dump_json()),
        )
    assert analyze(client, url, body, saved["last_event_id"]).status_code == 409
    result = analyze(client, url, body, event.id)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "needs_measurement"
    assert result.json()["report"] is None


def test_invalidation_cannot_promote_measurement_to_report(connected):
    client, url, _, directory = connected
    body = capture_payload(connected)
    saved = client.post(measurement_url(url), headers=AUTH, json=body).json()
    project_id = url.split("/")[2]
    with ProjectStore(directory).transaction() as db:
        invalid = EvidenceInvalidation(
            id="invalid-measurement",
            evidence_id=saved["evidence_id"],
            invalidated_for_version_id=body["plan_version_id"],
            reason="Synthetic invalidation",
            recorded_at=datetime.now(UTC),
        )
        db.execute(
            "INSERT INTO evidence_invalidations VALUES (?,?,?,?,?)",
            (
                invalid.id,
                project_id,
                invalid.evidence_id,
                body["plan_version_id"],
                invalid.model_dump_json(),
            ),
        )
    result = analyze(client, url, body, saved["last_event_id"]).json()
    assert result["report"] is None
    assert result["status"] == "needs_measurement"
    fresh = copy.deepcopy(body)
    fresh.update(
        expected_last_event_id=saved["last_event_id"],
        idempotency_key="after-invalidation",
    )
    saved2 = client.post(measurement_url(url), headers=AUTH, json=fresh)
    assert saved2.status_code == 200, saved2.text
    # Invalidated old typed evidence must not block a newly captured valid batch.
    assert (
        analyze(client, url, body, saved2.json()["last_event_id"]).json()["report"][
            "status"
        ]
        == "modeled_pass"
    )


def test_project_delete_purges_typed_measurements_and_replay(connected):
    client, url, _, directory = connected
    body = capture_payload(connected)
    assert client.post(measurement_url(url), headers=AUTH, json=body).status_code == 200
    project_id = url.split("/")[2]
    response = client.delete(
        "/api/projects/" + project_id,
        headers=AUTH | {"Idempotency-Key": "delete-measured-project"},
    )
    assert response.status_code == 200, response.text
    assert client.post(measurement_url(url), headers=AUTH, json=body).status_code == 404
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert (
            db.execute("SELECT count(*) FROM stability_measurements").fetchone()[0] == 0
        )
        assert (
            db.execute(
                "SELECT count(*) FROM requests WHERE scope=?",
                (project_id + ":stability-measurements",),
            ).fetchone()[0]
            == 0
        )


def test_typed_evidence_reference_cannot_hide_construction_invalidation(connected):
    client, url, _, directory = connected
    body = capture_payload(connected)
    saved = client.post(measurement_url(url), headers=AUTH, json=body).json()
    project_id = url.split("/")[2]
    with ProjectStore(directory).transaction() as db:
        row = db.execute(
            "SELECT id, body FROM progress_events WHERE project_id=? AND json_extract(body,'$.kind')='operation_confirmed' ORDER BY rowid LIMIT 1",
            (project_id,),
        ).fetchone()
        event = PhysicalEvent.model_validate_json(row[1]).model_copy(
            update={"evidence_ids": (saved["evidence_id"],)}
        )
        db.execute(
            "UPDATE progress_events SET body=? WHERE id=?",
            (event.model_dump_json(), row[0]),
        )
        invalid = EvidenceInvalidation(
            id="invalid-construction-alias",
            evidence_id=saved["evidence_id"],
            invalidated_for_version_id=body["plan_version_id"],
            reason="Synthetic construction alias regression",
            recorded_at=datetime.now(UTC),
        )
        db.execute(
            "INSERT INTO evidence_invalidations VALUES (?,?,?,?,?)",
            (
                invalid.id,
                project_id,
                invalid.evidence_id,
                body["plan_version_id"],
                invalid.model_dump_json(),
            ),
        )
    result = analyze(client, url, body, saved["last_event_id"])
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "unsupported"
    assert result.json()["report"] is None
    recapture = body | {
        "expected_last_event_id": saved["last_event_id"],
        "idempotency_key": "invalid-construction-recapture",
    }
    assert (
        client.post(measurement_url(url), headers=AUTH, json=recapture).status_code
        == 422
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("geometry_basis_hash", "0" * 64),
        ("inventory_revision_id", "foreign"),
        ("source_part_ids", ["foreign-part"]),
    ],
)
def test_stored_batch_must_match_actual_geometry_inventory_and_parts(
    connected, field, value
):
    import json

    client, url, _, directory = connected
    body = capture_payload(connected)
    saved = client.post(measurement_url(url), headers=AUTH, json=body).json()
    with ProjectStore(directory).transaction() as db:
        raw = json.loads(
            db.execute(
                "SELECT body FROM stability_measurements WHERE id=?",
                (saved["measurement_id"],),
            ).fetchone()[0]
        )
        raw[field] = value
        db.execute(
            "UPDATE stability_measurements SET body=? WHERE id=?",
            (json.dumps(raw), saved["measurement_id"]),
        )
    result = analyze(client, url, body, saved["last_event_id"])
    assert result.status_code == 200, result.text
    assert result.json()["report"] is None
    assert result.json()["status"] == "needs_measurement"
