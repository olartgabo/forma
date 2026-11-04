"""SYNTHETIC software checks for #149 measurement decisions; no physical pass."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_plans import AUTH, OTHER, TOKENS, prepared
from test_stability_measurements import capture_payload, measurement_url

from forma_api import synthesis_runtime
from forma_api.design_context import DesignContext, StaticDesignContextResolver
from forma_api.main import create_app

pytest_plugins = ["test_stability_route"]

UNKNOWN = {"value": None, "unit": "mm", "source": "unknown", "confirmed": False}


def ruler(value):
    return {"value": value, "unit": "mm", "source": "user_ruler", "confirmed": True}


@pytest.fixture
def design(tmp_path, monkeypatch):
    monkeypatch.setattr(synthesis_runtime, "ALLOW_SYNTHETIC", True)
    holder = {}

    def resolver():
        # The server context is keyed by inventory revision; follow saved changes.
        context = holder["context"]
        project = holder["project"]
        return StaticDesignContextResolver(
            context.model_copy(update={"inventory_revision_id": project["revision_id"]})
        )

    monkeypatch.setattr(synthesis_runtime, "default_context_resolver", resolver)
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        project, _, context = prepared(client)
        holder["context"] = DesignContext(
            project_id=project["id"],
            inventory_revision_id=project["revision_id"],
            **context,
        )
        sheet = project["stocks"][0]
        # An app-like unmeasured sheet: no dimensions and no usable region.
        unmeasured = sheet | {
            "width_mm": UNKNOWN,
            "height_mm": UNKNOWN,
            "usable_regions": [],
        }
        holder["project"] = project
        project = save(
            client, project, [unmeasured, project["stocks"][1]], "unmeasured"
        )
        holder["project"] = project
        yield client, project, holder, tmp_path


def save(client, project, stocks, key):
    response = client.put(
        f"/api/projects/{project['id']}/inventory",
        headers=AUTH,
        json={
            "expected_revision_id": project["revision_id"],
            "idempotency_key": "inventory-" + key,
            "stocks": stocks,
            "user_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["project"]


def request(project):
    return {
        "expected_inventory_revision_id": project["revision_id"],
        "expected_active_version_id": project.get("active_version_id"),
    }


def decide(client, project, headers=AUTH):
    return client.post(
        f"/api/projects/{project['id']}/measurement-decisions",
        headers=headers,
        json=request(project),
    )


def answer(client, holder, project, key, field, value):
    stocks = []
    for stock in project["stocks"]:
        if stock["id"] == "synthetic-sheet":
            stock = dict(stock)
            if field == "usable_region":
                stock["usable_regions"] = [
                    {
                        "id": "synthetic-sheet-whole",
                        "geometry": {
                            "x": 0,
                            "y": 0,
                            "width": stock["width_mm"]["value"],
                            "height": stock["height_mm"]["value"],
                            "rotation_deg": 0,
                        },
                    }
                ]
            else:
                stock[field] = ruler(value)
        stocks.append(stock)
    project = save(client, project, stocks, key)
    holder["project"] = project
    return project


def recalc(client, project, baseline):
    response = client.post(
        f"/api/projects/{project['id']}/measurement-decisions/recalculate",
        headers=AUTH,
        json=request(project) | {"baseline": baseline},
    )
    assert response.status_code == 200, response.text
    return response.json()


def counts(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("plans", "progress_events", "stability_measurements")
        }


def test_question_confirmed_record_and_recalculated_candidates(design):
    client, project, holder, directory = design
    first = decide(client, project).json()
    assert first["outcome"] == "question"
    assert first["question"]["target"]["key"] == "stock:synthetic-sheet:width_mm"
    assert first["question"]["threshold"]["lower"] == 78
    assert first["design"]["status"] != "candidates_found"
    project = answer(client, holder, project, "width", "width_mm", 200)
    change = recalc(client, project, first)
    assert change["changed_facts"] == ["stock:synthetic-sheet:width_mm: unknown → 200"]
    assert change["decision_changed"] is False
    second = change["after"]
    assert second["question"]["target"]["key"] == "stock:synthetic-sheet:height_mm"
    project = answer(client, holder, project, "height", "height_mm", 550)
    third = recalc(client, project, second)["after"]
    assert third["question"]["target"]["key"] == "stock:synthetic-sheet:usable_region"
    project = answer(client, holder, project, "region", "usable_region", None)
    final = recalc(client, project, third)
    assert final["decision_changed"] is True
    assert final["after"]["outcome"] == "physical_test_required"
    assert final["after"]["design"]["status"] == "candidates_found"
    assert len(final["after"]["design"]["candidate_ids"]) == 2
    assert "candidates_found" in final["explanation"]
    # Nothing was activated, built or measured by deciding or recalculating.
    current = client.get(f"/api/projects/{project['id']}", headers=AUTH).json()
    assert current["active_version_id"] is None
    assert counts(directory) == {
        "plans": 0,
        "progress_events": 0,
        "stability_measurements": 0,
    }


def test_insufficient_confirmed_value_keeps_the_decision_and_says_why(design):
    client, project, holder, _ = design
    first = decide(client, project).json()
    project = answer(client, holder, project, "narrow", "width_mm", 60)
    change = recalc(client, project, first)
    assert change["after"]["outcome"] == "no_feasible_candidate"
    assert change["decision_changed"] is True
    assert "78" in change["after"]["reasons"][0]
    # The height of a sheet already too narrow is never asked.
    assert change["after"]["question"] is None


def test_identical_requests_decide_identically_and_write_nothing(design):
    client, project, _, directory = design
    before = counts(directory)
    a, b = decide(client, project).json(), decide(client, project).json()
    assert a == b
    assert counts(directory) == before


def test_stale_and_foreign_requests_are_rejected(design):
    client, project, _, _ = design
    stale = request(project) | {"expected_inventory_revision_id": "inventory-old"}
    response = client.post(
        f"/api/projects/{project['id']}/measurement-decisions",
        headers=AUTH,
        json=stale,
    )
    assert response.status_code == 409
    assert decide(client, project, OTHER).status_code == 404
    baseline = decide(client, project).json()
    foreign = client.post(
        f"/api/projects/{project['id']}/measurement-decisions/recalculate",
        headers=OTHER,
        json=request(project) | {"baseline": baseline},
    )
    assert foreign.status_code == 404


def unavailable(client, project, decision, key="unavailable-0001"):
    return client.post(
        f"/api/projects/{project['id']}/measurement-decisions/unavailable",
        headers=AUTH,
        json=request(project)
        | {
            "expected_last_event_id": decision["identity"]["last_event_id"],
            "question_id": decision["question"]["question_id"],
            "target_key": decision["question"]["target"]["key"],
            "idempotency_key": key,
            "user_confirmed": True,
        },
    )


def test_unavailable_is_recorded_once_and_replays_after_a_change(design):
    client, project, holder, directory = design
    first = decide(client, project).json()
    response = unavailable(client, project, first)
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["identity"]["declined_target_keys"] == [
        "stock:synthetic-sheet:width_mm"
    ]
    # The only sheet cannot be measured, so no design can be made.
    assert after["outcome"] == "no_feasible_candidate" and after["question"] is None
    project = save(client, project, project["stocks"], "after-decline")
    holder["project"] = project
    replay = unavailable(
        client,
        project | {"revision_id": first["identity"]["inventory_revision_id"]},
        first,
    )
    assert replay.status_code == 200, replay.text
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        rows = connection.execute(
            "SELECT COUNT(*) FROM requests WHERE scope LIKE '%:measurement-unavailable'"
        ).fetchone()[0]
    assert rows == 1
    other = unavailable(client, project, first, key="unavailable-0002")
    assert other.status_code == 409


def test_built_stand_question_capture_and_recalculation(connected):
    client, _, payload, directory = connected
    project_id = payload["plan_version_id"] and connected[1].split("/")[2]
    project = client.get(f"/api/projects/{project_id}", headers=AUTH).json()
    unbuilt = decide(client, project).json()
    assert unbuilt["outcome"] == "physical_test_required"
    body = capture_payload(connected)
    built = decide(client, project).json()
    assert built["outcome"] == "question"
    question = built["question"]
    assert question["capture"] == "stability_measurements"
    assert question["affected_case_ids"] == ["portrait", "landscape"]
    assert {p["display_name"] for p in question["target"]["pieces"]} == {
        "Support panel",
        "Base panel",
        "Rear brace",
    }
    saved = client.post(measurement_url(connected[1]), headers=AUTH, json=body)
    assert saved.status_code == 200, saved.text
    change = recalc(client, project, built)
    after = change["after"]
    assert change["decision_changed"] is True
    assert "assembled-stand measurement records: 0 → 1" in change["changed_facts"]
    assert after["outcome"] in ("none_needed", "unsupported")
    assert after["stability"]["analysis_status"] == "complete"
    assert all(m is not None for _, m in after["stability"]["case_margins_m"])
    current = client.get(f"/api/projects/{project_id}", headers=AUTH).json()
    assert current["active_version_id"] == payload["plan_version_id"]


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    """The production file resolver: settings exist only for listed revisions."""
    monkeypatch.setattr(synthesis_runtime, "ALLOW_SYNTHETIC", True)
    path = tmp_path / "design-context.json"
    monkeypatch.setenv("FORMA_DESIGN_CONTEXT_PATH", str(path))
    entries = []

    def configure(project, context):
        # An explicit operator step: add settings for exactly this revision.
        entries.append(
            DesignContext(
                project_id=project["id"],
                inventory_revision_id=project["revision_id"],
                **context,
            ).model_dump(mode="json")
        )
        path.write_text(json.dumps({"contexts": entries}), encoding="utf-8")

    with TestClient(create_app(tmp_path / "data", TOKENS)) as client:
        project, _, context = prepared(client)
        sheet = project["stocks"][0]
        unmeasured = sheet | {
            "width_mm": UNKNOWN,
            "height_mm": UNKNOWN,
            "usable_regions": [],
        }
        project = save(
            client, project, [unmeasured, project["stocks"][1]], "unmeasured"
        )
        configure(project, context)
        yield client, project, context, configure


def test_new_revisions_need_operator_settings_and_say_so(manifest):
    client, project, context, configure = manifest
    first = decide(client, project).json()
    assert first["question"]["target"]["key"] == "stock:synthetic-sheet:width_mm"
    project = answer(client, {}, project, "width", "width_mm", 200)
    # The measurement is saved, but this revision has no settings yet.
    blocked = recalc(client, project, first)
    after = blocked["after"]
    assert after["outcome"] == "unsupported" and after["question"] is None
    assert any(project["revision_id"] in reason for reason in after["reasons"])
    assert any(
        "does not carry them forward" in c for c in after["missing_capabilities"]
    )
    assert "stock:synthetic-sheet:width_mm: unknown → 200" in blocked["changed_facts"]
    assert blocked["decision_changed"] is True
    # Nothing was carried over automatically.
    assert decide(client, project).json()["outcome"] == "unsupported"
    configure(project, context)
    ready = recalc(client, project, first)
    assert ready["after"]["question"]["target"]["key"] == (
        "stock:synthetic-sheet:height_mm"
    )
    assert ready["changed_facts"] == ["stock:synthetic-sheet:width_mm: unknown → 200"]
