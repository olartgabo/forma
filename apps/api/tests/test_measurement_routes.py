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
    """The production file resolver with settings for the first revision only.

    Nothing here rebinds settings to later revisions: they reach a new revision
    only through the server's own carry rule.
    """
    monkeypatch.setattr(synthesis_runtime, "ALLOW_SYNTHETIC", True)
    path = tmp_path / "design-context.json"
    monkeypatch.setenv("FORMA_DESIGN_CONTEXT_PATH", str(path))
    entries = {}

    def configure(project, context):
        # An explicit operator step for exactly this revision.
        entries[project["revision_id"]] = DesignContext(
            project_id=project["id"],
            inventory_revision_id=project["revision_id"],
            **context,
        ).model_dump(mode="json")
        path.write_text(
            json.dumps({"contexts": list(entries.values())}), encoding="utf-8"
        )

    with TestClient(create_app(tmp_path / "data", TOKENS)) as client:
        project, _, context = prepared(client)
        sheet, tape = project["stocks"]
        a = sheet | {"width_mm": UNKNOWN, "height_mm": UNKNOWN, "usable_regions": []}
        b = a | {"id": "synthetic-sheet-b"}
        project = save(client, project, [a, b, tape], "unmeasured")
        configure(project, context)
        yield client, project, context, configure, entries, tmp_path / "data"


def stock(project, stock_id):
    return next(s for s in project["stocks"] if s["id"] == stock_id)


def put(client, project, stocks, key, requirements=None):
    body = {
        "expected_revision_id": project["revision_id"],
        "idempotency_key": "inventory-" + key,
        "stocks": stocks,
        "user_confirmed": True,
    }
    if requirements is not None:
        body["requirements"] = requirements
    return client.put(
        f"/api/projects/{project['id']}/inventory", headers=AUTH, json=body
    )


def measure(client, project, stock_id, field, value, key):
    stocks = []
    for item in project["stocks"]:
        if item["id"] == stock_id:
            item = dict(item)
            if field == "usable_region":
                item["usable_regions"] = [
                    {
                        "id": stock_id + "-whole",
                        "geometry": {
                            "x": 0,
                            "y": 0,
                            "width": item["width_mm"]["value"],
                            "height": item["height_mm"]["value"],
                            "rotation_deg": 0,
                        },
                    }
                ]
            else:
                item[field] = ruler(value)
        stocks.append(item)
    return save(client, project, stocks, key)


def receipts(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        return connection.execute(
            "SELECT owner, scope, key, digest, response FROM requests ORDER BY rowid"
        ).fetchall()


def test_settings_follow_measurements_to_candidates_without_operator(manifest):
    client, project, _, _, entries, _ = manifest
    first_revision = project["revision_id"]
    first = decide(client, project).json()
    assert first["question"]["target"]["key"] == "stock:synthetic-sheet:width_mm"
    assert first["settings"] == []
    project = measure(client, project, "synthetic-sheet", "width_mm", 200, "w")
    change = recalc(client, project, first)
    after = change["after"]
    assert after["question"]["target"]["key"] == "stock:synthetic-sheet:height_mm"
    assert first_revision in after["settings"][0]
    assert "no evidence is renewed" in after["settings"][0]
    # The question identity moved with the inventory: the old one is stale.
    assert after["question"]["question_id"] != first["question"]["question_id"]
    assert unavailable(client, project, first).status_code == 409
    project = measure(client, project, "synthetic-sheet", "height_mm", 550, "h")
    third = recalc(client, project, after)["after"]
    assert third["question"]["target"]["key"] == ("stock:synthetic-sheet:usable_region")
    project = measure(client, project, "synthetic-sheet", "usable_region", None, "r")
    final = recalc(client, project, third)
    assert final["after"]["design"]["status"] == "candidates_found"
    assert final["decision_changed"] is True
    # Sheet B could still give a better proposal, so it is asked next.
    assert final["after"]["question"]["target"]["stock_id"] == "synthetic-sheet-b"
    # The #148 search agrees: same carried settings, same candidates.
    search = client.post(
        f"/api/projects/{project['id']}/synthesis/search",
        headers=AUTH,
        json=request(project) | {"expected_last_event_id": None},
    ).json()
    assert search["status"] == "candidates_found"
    assert search["search_id"] == final["after"]["design"]["search_id"]
    # The operator configured one revision only.
    assert list(entries) == [first_revision]


def test_changed_material_new_and_readded_stock_need_attention(manifest):
    client, project, _, _, _, _ = manifest
    a, b, tape = project["stocks"]
    changed = put(
        client,
        project,
        [a, b | {"material": "paperboard"}, tape, a | {"id": "synthetic-sheet-c"}],
        "material",
    )
    assert changed.status_code == 200, changed.text
    project = changed.json()["project"]
    decision = decide(client, project).json()
    # Only the unchanged sheet is asked about.
    assert decision["question"]["target"]["stock_id"] == "synthetic-sheet"
    notes = " ".join(decision["settings"])
    assert "synthetic-sheet-b changed from cardboard sheet to paperboard sheet" in notes
    assert "synthetic-sheet-c was added" in notes
    # Removed, then added again under the same ID: a different item.
    project = save(client, project, [a, tape], "remove-a-only")
    project = save(client, project, [a, b, tape], "readd-b")
    notes = " ".join(decide(client, project).json()["settings"])
    assert "synthetic-sheet-b was removed and added again" in notes


def test_removed_stock_keeps_the_settings_for_the_rest(manifest):
    client, project, _, _, _, _ = manifest
    a, _, tape = project["stocks"]
    project = save(client, project, [a, tape], "remove-b")
    decision = decide(client, project).json()
    assert decision["question"]["target"]["key"] == "stock:synthetic-sheet:width_mm"
    assert any("synthetic-sheet-b was removed" in n for n in decision["settings"])


def test_only_uncovered_stock_left_is_unsupported_not_infeasible(manifest):
    client, project, _, _, _, _ = manifest
    a, b, tape = project["stocks"]
    project = save(
        client,
        project,
        [a | {"material": "paperboard"}, b | {"material": "paperboard"}, tape],
        "all-paperboard",
    )
    decision = decide(client, project).json()
    assert decision["outcome"] == "unsupported" and decision["question"] is None
    assert any("paperboard" in r for r in decision["reasons"])


def test_stale_evidence_is_carried_as_recorded_never_renewed(manifest):
    client, project, context, configure, entries, _ = manifest
    first_revision = project["revision_id"]
    project = measure(client, project, "synthetic-sheet", "width_mm", 200, "w")
    # After review, the operator marks the cutting evidence invalidated.
    process = context["process"]
    stale = process.model_copy(
        update={
            "evidence": tuple(
                e.model_copy(update={"verification_state": "invalidated"})
                for e in process.evidence
            )
        }
    )
    configure(
        {"id": project["id"], "revision_id": first_revision},
        context | {"process": stale},
    )
    decision = decide(client, project).json()
    assert decision["outcome"] == "unsupported" and decision["question"] is None
    assert any("verified cutting process" in r for r in decision["reasons"])
    assert any("recorded as invalidated" in n for n in decision["settings"])
    # The source entry is unchanged and nothing was written for the new revision.
    assert list(entries) == [first_revision]
    states = {
        e["verification_state"] for e in entries[first_revision]["process"]["evidence"]
    }
    assert states == {"invalidated"}


def test_changed_tools_drop_only_the_tool_confirmation(manifest):
    client, project, _, _, _, _ = manifest
    requirements = project["requirements"] | {
        "tools": ["Synthetic ruler", "Synthetic awl"]
    }
    saved = put(client, project, project["stocks"], "tools", requirements)
    assert saved.status_code == 200, saved.text
    decision = decide(client, saved.json()["project"]).json()
    assert decision["outcome"] == "unsupported"
    assert any("Tool and hinge-access" in r for r in decision["reasons"])
    assert any("tool confirmation is not carried" in n for n in decision["settings"])


def test_interrupted_saves_replay_and_receipts_stay_unchanged(manifest):
    client, project, _, _, _, directory = manifest
    first = decide(client, project).json()
    stocks = [
        s | {"width_mm": ruler(200)} if s["id"] == "synthetic-sheet" else s
        for s in project["stocks"]
    ]
    sent = put(client, project, stocks, "lost-response")
    assert sent.status_code == 200
    # The response was lost; the browser retries with the same key and body.
    retried = put(client, project, stocks, "lost-response")
    assert retried.status_code == 200 and retried.json()["replayed"] is True
    project = retried.json()["project"]
    assert project["revision_id"] == sent.json()["project"]["revision_id"]
    before = receipts(directory)
    change = recalc(client, project, first)
    assert change["after"]["question"]["target"]["key"] == (
        "stock:synthetic-sheet:height_mm"
    )
    decide(client, project)
    # Deciding and carrying settings read the receipts; they never change them.
    assert receipts(directory) == before
    # An identity from before the save is still refused.
    stale = request(project) | {
        "expected_inventory_revision_id": first["identity"]["inventory_revision_id"]
    }
    assert (
        client.post(
            f"/api/projects/{project['id']}/measurement-decisions",
            headers=AUTH,
            json=stale,
        ).status_code
        == 409
    )


def test_own_settings_for_a_revision_take_precedence(manifest):
    client, project, context, configure, _, _ = manifest
    project = measure(client, project, "synthetic-sheet", "width_mm", 200, "w")
    configure(project, context)
    decision = decide(client, project).json()
    assert decision["settings"] == []
    assert decision["question"]["target"]["key"] == "stock:synthetic-sheet:height_mm"


def test_replacing_full_inventory_keeps_all_settings_names(manifest):
    client, project, context, configure, _, _ = manifest
    sheet = project["stocks"][0]
    old = [sheet | {"id": f"old-sheet-{i}"} for i in range(32)]
    project = save(client, project, old, "full-old-inventory")
    configure(project, context)
    new = [sheet | {"id": f"new-sheet-{i}"} for i in range(32)]
    project = save(client, project, new, "full-new-inventory")
    response = decide(client, project)
    assert response.status_code == 200, response.text
    decision = response.json()
    assert decision["outcome"] == "unsupported"
    assert decision["question"] is None
    assert len(decision["settings"]) <= 48
    assert all(len(note) <= 2000 for note in decision["settings"])
    notes = "\n".join(decision["settings"])
    for item in old:
        assert f"Stock {item['id']} was removed" in notes
    for item in new:
        assert f"Stock {item['id']} was added" in notes
