"""Saved stability reports from synthetic software inputs; none is a physical pass."""

import copy
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated

import pytest
from fastapi import Header, HTTPException
from test_plans import AUTH, OTHER, TOKENS
from test_stability_measurements import analyze, capture_payload, measurement_url
from test_stability_runtime import analytic

from forma_api import stability_reports as reports
from forma_api.projects import ProjectStore
from forma_api.routes.stability import stability_router
from forma_domain.models import EvidenceInvalidation

pytest_plugins = ["test_stability_route"]


def reports_url(url):
    return url.removesuffix("analyses") + "reports"


def production(url):
    return url.replace("/test/", "/api/projects/")


def save(client, url, body, event_id, key, headers=AUTH):
    return client.post(
        reports_url(url),
        headers=headers,
        json={k: body[k] for k in ("plan_version_id", "expected_inventory_revision_id")}
        | {"expected_last_event_id": event_id, "idempotency_key": key},
    )


def measured(connected):
    """Assemble, record synthetic measurements and return (body, event_id)."""
    client, url, _, _ = connected
    body = capture_payload(connected)
    saved = client.post(measurement_url(url), headers=AUTH, json=body)
    assert saved.status_code == 200, saved.text
    return body, saved.json()["last_event_id"]


def rows(directory, table="stability_reports"):
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        return db.execute(f"SELECT id, body FROM {table}").fetchall()


def test_save_is_immutable_content_addressed_and_idempotent(connected):
    client, url, _, directory = connected
    body, event = measured(connected)
    first = save(client, url, body, event, "report-key-0001")
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "no-store"
    data = first.json()
    report = data["analysis"]["report"]
    saved = data["saved"]
    assert report["status"] == "modeled_pass"
    assert saved["report_id"] == "stability-report-" + report["cache_hash"]
    assert saved["freshness"] == {"current": True, "stale_reasons": []}
    assert saved["case_ids"] == ["portrait", "landscape"]
    assert data["cached"] is False and data["replayed"] is False
    replay = save(client, url, body, event, "report-key-0001").json()
    assert replay["replayed"] is True and replay["saved"] == saved
    again = save(client, url, body, event, "report-key-0002").json()
    assert again["cached"] is True
    assert again["saved"]["report_id"] == saved["report_id"]
    assert again["saved"]["created_at"] == saved["created_at"]
    stored = rows(directory)
    assert len(stored) == 1
    record = reports.SavedStabilityReport.model_validate_json(stored[0][1])
    assert record.report == reports.StabilityReport.model_validate(report)
    assert record.analysis_input.identity.history_cursor == event
    assert record.dependencies.engine == report["engine_version"]
    assert record.dependencies.numpy and record.dependencies.geos
    assert record.input_hash != report["cache_hash"]
    assert record.evidence_ids == (body_evidence(directory),)
    # Private evidence descriptions, media and provider text are never embedded.
    assert "User-reported typed assembled" not in stored[0][1]
    assert "asset" not in stored[0][1] and "media" not in stored[0][1]
    conflict = save(client, url, body, None, "report-key-0001")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


def body_evidence(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        return db.execute(
            "SELECT json_extract(body, '$.evidence_id') FROM stability_measurements"
        ).fetchone()[0]


def test_blocked_analysis_saves_nothing_and_stale_requests_are_rejected(connected):
    client, url, payload, directory = connected
    blocked = save(client, url, payload, None, "blocked-key-01")
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["analysis"]["status"] == "needs_measurement"
    assert blocked.json()["saved"] is None
    assert rows(directory) == []
    body, event = measured(connected)
    stale = save(client, url, body, None, "stale-key-0001")
    assert stale.status_code == 409 and stale.json()["code"] == "stale_version"
    wrong_inventory = dict(body, expected_inventory_revision_id="inventory-old")
    assert (
        save(client, url, wrong_inventory, event, "stale-key-0002").status_code == 409
    )
    assert rows(directory) == []


def test_history_keeps_old_reports_readable_and_marks_them_stale(connected):
    client, url, _, _ = connected
    body, event = measured(connected)
    old = save(client, url, body, event, "history-key-01").json()["saved"]
    changed = copy.deepcopy(body)
    changed.update(expected_last_event_id=event, idempotency_key="measurements-002")
    changed["measurements"]["cases"][1]["device"]["center_of_mass_m"]["x"] = 1.0
    second = client.post(measurement_url(url), headers=AUTH, json=changed)
    assert second.status_code == 200, second.text
    event2 = second.json()["last_event_id"]
    new = save(client, url, body, event2, "history-key-02").json()
    assert new["analysis"]["report"]["status"] == "modeled_fail"
    history = client.get(reports_url(production(url)), headers=AUTH)
    assert history.status_code == 200, history.text
    listed = history.json()
    assert listed["last_event_id"] == event2
    assert [r["report_id"] for r in listed["reports"]] == [
        new["saved"]["report_id"],
        old["report_id"],
    ]
    assert listed["reports"][0]["freshness"]["current"] is True
    assert listed["reports"][1]["freshness"] == {
        "current": False,
        "stale_reasons": ["history_changed"],
    }
    limited = client.get(
        reports_url(production(url)), headers=AUTH, params={"limit": 1}
    ).json()
    assert len(limited["reports"]) == 1
    detail = client.get(
        reports_url(production(url)) + "/" + old["report_id"], headers=AUTH
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["freshness"]["stale_reasons"] == ["history_changed"]
    assert detail.json()["saved"]["report"]["status"] == "modeled_pass"
    # A stale report cannot be re-saved against the current identity.
    assert save(client, url, body, event, "history-key-03").status_code == 409


def test_cross_owner_missing_and_deleted_context(connected):
    client, url, _, directory = connected
    body, event = measured(connected)
    saved = save(client, url, body, event, "owner-key-0001").json()["saved"]
    base = reports_url(production(url))
    detail_url = base + "/" + saved["report_id"]
    compare_url = production(url).removesuffix("analyses") + "report-comparison"
    assert client.get(base, headers=OTHER).status_code == 404
    assert client.get(detail_url, headers=OTHER).status_code == 404
    assert (
        client.get(
            compare_url,
            headers=OTHER,
            params={"first": saved["report_id"], "second": saved["report_id"]},
        ).status_code
        == 404
    )
    assert save(client, url, body, event, "owner-key-0002", OTHER).status_code == 404
    assert client.get(base, headers={}).status_code == 401
    missing = client.get(base + "/stability-report-" + "0" * 64, headers=AUTH)
    assert missing.status_code == 404
    project_id = url.split("/")[2]
    deleted = client.delete(
        "/api/projects/" + project_id,
        headers=AUTH | {"Idempotency-Key": "delete-project-1"},
    )
    assert deleted.status_code == 200, deleted.text
    assert client.get(base, headers=AUTH).status_code == 404
    assert client.get(detail_url, headers=AUTH).status_code == 404
    assert rows(directory) == []
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert not db.execute(
            "SELECT 1 FROM requests WHERE scope=?", (project_id + ":stability-reports",)
        ).fetchall()


def test_invalidated_measurement_evidence_marks_report_stale(connected):
    client, url, _, directory = connected
    body, event = measured(connected)
    saved = save(client, url, body, event, "invalid-key-001").json()["saved"]
    project_id = url.split("/")[2]
    with ProjectStore(directory).transaction() as db:
        invalid = EvidenceInvalidation(
            id="invalid-saved-report",
            evidence_id=body_evidence(directory),
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
    detail = client.get(
        reports_url(production(url)) + "/" + saved["report_id"], headers=AUTH
    ).json()
    assert detail["freshness"] == {
        "current": False,
        "stale_reasons": ["evidence_invalidated"],
    }


def test_plan_and_inventory_changes_are_named_stale_reasons(connected):
    client, url, _, directory = connected
    body, event = measured(connected)
    saved_id = save(client, url, body, event, "fresh-key-0001").json()["saved"][
        "report_id"
    ]
    store = ProjectStore(directory)
    with store.transaction() as db:
        state = reports.ProjectState(db, store, "alice", url.split("/")[2])
        saved = reports.read_record(db, state.project.id, saved_id)
    moved = state.project.model_copy(
        update={"active_version_id": "other-plan", "revision_id": "inventory-new"}
    )
    fresh = reports.freshness(saved, moved, state.cursor, state.invalidated)
    assert fresh.stale_reasons == ("plan_changed", "inventory_changed")
    assert reports.freshness(saved, state.project, None, ()).stale_reasons == (
        "history_changed",
    )


@pytest.fixture
def resolved(connected):
    """Same store with analytic resolvers: known, unknown and budget-limited."""
    client, url, payload, directory = connected
    store = ProjectStore(directory)

    def authenticate(authorization: Annotated[str | None, Header()] = None):
        for owner, token in TOKENS.items():
            if authorization == "Bearer " + token:
                return owner
        raise HTTPException(401)

    def limited(snapshot):
        result = analytic(snapshot)
        second = result.analysis.cases[0].model_copy(
            update={"case_id": "analytic-second"}
        )
        analysis = result.analysis.model_copy(
            update={"cases": result.analysis.cases + (second,)}
        )
        policy = result.policy.model_copy(update={"evaluation_budget": 1})
        return replace(result, analysis=analysis, policy=policy)

    def wider_margin(snapshot):
        result = analytic(snapshot)
        return replace(
            result, policy=result.policy.model_copy(update={"required_margin_m": 0.5})
        )

    app = client.app
    for prefix, resolver in (
        ("/known", analytic),
        ("/unknown", lambda s: analytic(s, unknown=True)),
        ("/limited", limited),
        ("/policy", wider_margin),
    ):
        app.include_router(
            stability_router(store, authenticate, resolver=resolver), prefix=prefix
        )
    project_id = url.split("/")[2]

    def post(prefix, key):
        response = client.post(
            f"{prefix}/{project_id}/stability/reports",
            headers=AUTH,
            json=payload | {"idempotency_key": key},
        )
        assert response.status_code == 200, response.text
        return response.json()

    return client, project_id, post


def test_failed_partial_and_budget_exhausted_reports_are_saved_honestly(resolved):
    client, project_id, post = resolved
    limited = post("/limited", "limited-key-01")
    report = limited["analysis"]["report"]
    assert report["status"] == "indeterminate"
    assert any(r["computation"] == "budget_exhausted" for r in report["results"])
    assert limited["saved"]["report_status"] == "indeterminate"
    assert limited["saved"]["analysis_status"] == "unsupported"
    unknown = post("/unknown", "unknown-key-01")
    assert unknown["saved"]["report_status"] != "modeled_pass"
    detail = client.get(
        f"/api/projects/{project_id}/stability/reports/{limited['saved']['report_id']}",
        headers=AUTH,
    ).json()
    assert any(
        r["computation"] == "budget_exhausted"
        for r in detail["saved"]["report"]["results"]
    )


def test_comparison_is_per_check_and_refuses_fabricated_ranking(resolved):
    client, project_id, post = resolved
    known = post("/known", "compare-key-01")["saved"]["report_id"]
    unknown = post("/unknown", "compare-key-02")["saved"]["report_id"]
    policy = post("/policy", "compare-key-03")["saved"]["report_id"]
    limited = post("/limited", "compare-key-04")["saved"]["report_id"]
    url = f"/api/projects/{project_id}/stability/report-comparison"

    def compare(first, second):
        response = client.get(
            url, headers=AUTH, params={"first": first, "second": second}
        )
        assert response.status_code == 200, response.text
        return response.json()

    same = compare(known, unknown)
    assert same["comparable"] is True
    assert {row["outcome"] for row in same["rows"]} == {"unknown"}
    assert "ranking" not in same and "winner" not in same
    mismatch = compare(known, policy)
    assert mismatch["comparable"] is False
    assert any("policies" in m for m in mismatch["mismatches"])
    assert {row["outcome"] for row in mismatch["rows"]} == {"not_comparable"}
    cases = compare(known, limited)
    assert cases["comparable"] is False
    assert any("load cases" in m for m in cases["mismatches"])
    assert (
        client.get(
            url, headers=AUTH, params={"first": known, "second": known}
        ).status_code
        == 422
    )


def test_measured_comparison_reports_margins_without_a_winner(connected):
    client, url, _, _ = connected
    body, event = measured(connected)
    first = save(client, url, body, event, "margin-key-0001").json()["saved"]
    changed = copy.deepcopy(body)
    changed.update(expected_last_event_id=event, idempotency_key="measurements-003")
    changed["measurements"]["cases"][1]["device"]["center_of_mass_m"]["y"] = 0.01
    event2 = client.post(measurement_url(url), headers=AUTH, json=changed).json()[
        "last_event_id"
    ]
    second = save(client, url, body, event2, "margin-key-0002").json()["saved"]
    result = client.get(
        production(url).removesuffix("analyses") + "report-comparison",
        headers=AUTH,
        params={"first": first["report_id"], "second": second["report_id"]},
    ).json()
    assert result["comparable"] is True
    assert result["second"]["freshness"]["current"] is True
    assert result["first"]["freshness"]["current"] is False
    tips = {row["case_id"]: row for row in result["rows"] if row["check_type"] == "tip"}
    assert tips["portrait"]["outcome"] == "equal_within_tolerance"
    assert tips["landscape"]["first_margin_m"] is not None
    assert tips["landscape"]["outcome"] in (
        "first_larger_margin",
        "second_larger_margin",
    )
    supports = [row for row in result["rows"] if row["check_type"] == "support"]
    assert supports and all(row["first_margin_m"] is None for row in supports)


def test_existing_analysis_endpoint_remains_read_only(connected):
    client, url, _, directory = connected
    body, event = measured(connected)
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        before = tuple(db.iterdump())
    response = analyze(client, url, body, event)
    assert response.status_code == 200
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert tuple(db.iterdump()) == before


def test_replay_after_measurement_change_reports_current_staleness(connected):
    client, url, _, directory = connected
    body, event = measured(connected)
    first = save(client, url, body, event, "replay-fresh-01").json()
    stored_before = rows(directory)
    changed = copy.deepcopy(body)
    changed.update(expected_last_event_id=event, idempotency_key="measurements-004")
    changed["measurements"]["stand"]["mass_kg"] = 0.12
    moved = client.post(measurement_url(url), headers=AUTH, json=changed)
    assert moved.status_code == 200, moved.text
    replay = save(client, url, body, event, "replay-fresh-01")
    assert replay.status_code == 200, replay.text
    data = replay.json()
    assert data["replayed"] is True
    # The original calculation is returned unchanged ...
    assert data["analysis"] == first["analysis"]
    assert data["saved"]["report_id"] == first["saved"]["report_id"]
    assert data["saved"]["created_at"] == first["saved"]["created_at"]
    # ... but its freshness is judged now, matching the detail route.
    assert data["saved"]["freshness"] == {
        "current": False,
        "stale_reasons": ["history_changed"],
    }
    detail = client.get(
        reports_url(production(url)) + "/" + first["saved"]["report_id"],
        headers=AUTH,
    ).json()
    assert detail["freshness"] == data["saved"]["freshness"]
    assert rows(directory) == stored_before


@pytest.mark.parametrize("component", ["engine", "numpy", "shapely", "geos"])
def test_dependency_upgrade_marks_history_detail_and_replay_stale(
    connected, monkeypatch, component
):
    client, url, _, directory = connected
    body, event = measured(connected)
    first = save(client, url, body, event, "dependency-fresh-01").json()
    saved_id = first["saved"]["report_id"]
    stored_before = rows(directory)
    current = reports.dependencies()
    monkeypatch.setattr(
        reports,
        "dependencies",
        lambda: current.model_copy(update={component: "synthetic-next-version"}),
    )
    base = reports_url(production(url))
    history = client.get(base, headers=AUTH)
    detail = client.get(base + "/" + saved_id, headers=AUTH)
    replay = save(client, url, body, event, "dependency-fresh-01")
    assert history.status_code == detail.status_code == replay.status_code == 200
    expected = {"current": False, "stale_reasons": ["engine_changed"]}
    assert history.json()["reports"][0]["freshness"] == expected
    assert detail.json()["freshness"] == expected
    assert replay.json()["saved"]["freshness"] == expected
    assert replay.json()["analysis"] == first["analysis"]
    assert rows(directory) == stored_before
