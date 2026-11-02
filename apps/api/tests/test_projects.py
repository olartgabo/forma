import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from forma_api.main import create_app
from forma_domain.fixtures import synthetic_inventory_a

TOKENS = {"alice": "a" * 40, "bob": "b" * 40}
AUTH = {"Authorization": "Bearer " + TOKENS["alice"]}
OTHER = {"Authorization": "Bearer " + TOKENS["bob"]}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        yield client


def create(client, key="create-001"):
    response = client.post(
        "/api/projects",
        json={"goal": "A phone stand", "idempotency_key": key},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    return response.json()["project"]


def update(project, key="inventory-001"):
    return {
        "expected_revision_id": project["revision_id"],
        "idempotency_key": key,
        "stocks": [s.model_dump(mode="json") for s in synthetic_inventory_a()],
        "user_confirmed": True,
    }


def requirements():
    def measurement(value, unit):
        return {
            "value": value,
            "unit": unit,
            "source": "unknown" if value is None else "user_ruler",
            "confirmed": value is not None,
            "evidence_ids": [],
        }

    return {
        "tools": ["Ruler", "Scissors"],
        "device_description": "Test phone",
        "constraints": {
            "device_mass_g": measurement(None, "g"),
            "support_angle_deg": measurement(60, "deg"),
            "max_footprint_width_mm": measurement(200, "mm"),
            "max_footprint_height_mm": measurement(None, "mm"),
            "allowed_profile_ids": [],
            "allow_purchases": False,
        },
    }


def requirements_update(project, key="inventory-001"):
    return {**update(project, key), "requirements": requirements()}


def test_credentials_and_owner_scope(client):
    assert (
        client.post(
            "/api/projects", json={"goal": "stand", "idempotency_key": "create-001"}
        ).status_code
        == 401
    )
    project = create(client)
    path = "/api/projects/" + project["id"]
    assert client.get(path, headers=OTHER).status_code == 404
    assert (
        client.put(path + "/inventory", json=update(project), headers=OTHER).status_code
        == 404
    )
    assert (
        client.delete(
            path, headers={**OTHER, "Idempotency-Key": "delete-001"}
        ).status_code
        == 404
    )
    assert (
        client.get(path, headers={"Authorization": "Bearer forged"}).status_code == 401
    )
    assert client.get(path, headers=AUTH).status_code == 200


def create_as(client, headers, key, goal="A phone stand"):
    response = client.post(
        "/api/projects",
        json={"goal": goal, "idempotency_key": key},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["project"]


def test_list_projects_empty_owner_and_auth(client):
    assert client.get("/api/projects").status_code == 401
    assert (
        client.get(
            "/api/projects", headers={"Authorization": "Bearer forged"}
        ).status_code
        == 401
    )
    assert client.get("/api/projects", headers=OTHER).json() == {
        "projects": [],
        "next_cursor": None,
    }
    create(client)
    # Bob still sees an empty owner-scoped list.
    assert client.get("/api/projects", headers=OTHER).json() == {
        "projects": [],
        "next_cursor": None,
    }


def test_list_projects_pagination_no_duplicates_and_summary_only(client):
    created = [create_as(client, AUTH, f"list-{index:03d}") for index in range(5)]
    create_as(client, OTHER, "list-other-001", goal="Bob project")
    create_as(client, OTHER, "list-other-002", goal="Bob project")
    # Reflect a confirmed inventory in exactly one summary.
    target = created[0]
    updated = client.put(
        "/api/projects/" + target["id"] + "/inventory",
        json=update(target),
        headers=AUTH,
    )
    assert updated.status_code == 200, updated.text
    expected_by_id = {project["id"]: project for project in created}
    expected_by_id[target["id"]] = updated.json()["project"]

    seen = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/api/projects", params=params, headers=AUTH)
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {"projects", "next_cursor"}
        assert len(body["projects"]) <= 2
        for summary in body["projects"]:
            assert set(summary) == {
                "id",
                "goal",
                "revision_id",
                "inventory_confirmed",
                "active_version_id",
            }
            expected = expected_by_id[summary["id"]]
            assert summary == {
                "id": expected["id"],
                "goal": expected["goal"],
                "revision_id": expected["revision_id"],
                "inventory_confirmed": expected["inventory_confirmed"],
                "active_version_id": expected["active_version_id"],
            }
        seen.extend(summary["id"] for summary in body["projects"])
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
        # More owned rows must remain whenever a cursor is offered.
        assert cursor == body["projects"][-1]["id"]
        assert len(seen) < len(created)
        assert pages < 10

    assert seen == sorted(expected_by_id)
    assert len(seen) == len(set(seen)) == 5
    assert pages == 3
    # Listing is read-only and does not change the stored project.
    assert client.get("/api/projects", headers=AUTH).status_code == 200
    assert (
        client.get("/api/projects/" + target["id"], headers=AUTH).json()
        == expected_by_id[target["id"]]
    )
    # Default limit returns all five with no cursor (well under 20).
    default = client.get("/api/projects", headers=AUTH).json()
    assert [p["id"] for p in default["projects"]] == sorted(expected_by_id)
    assert default["next_cursor"] is None


def test_list_projects_cross_owner_and_foreign_cursor(client):
    own = [create_as(client, AUTH, f"ownkey-{index:03d}") for index in range(3)]
    foreign = create_as(client, OTHER, "foreign-001", goal="Bob secret goal")
    body = client.get("/api/projects", headers=AUTH).json()
    assert {p["id"] for p in body["projects"]} == {p["id"] for p in own}
    assert all(p["goal"] != "Bob secret goal" for p in body["projects"])
    # A foreign project's ID used as a cursor is only an ID threshold for
    # the caller: it can never surface the other owner's rows.
    response = client.get(
        "/api/projects", params={"cursor": foreign["id"]}, headers=AUTH
    )
    assert response.status_code == 200, response.text
    leaked = response.json()
    assert all(p["id"] in {p["id"] for p in own} for p in leaked["projects"])
    assert all(p["id"] > foreign["id"] for p in leaked["projects"])
    assert foreign["id"] not in {p["id"] for p in leaked["projects"]}
    # Bob likewise cannot see Alice's projects through her cursor.
    bob = client.get(
        "/api/projects", params={"cursor": own[0]["id"]}, headers=OTHER
    ).json()
    assert {p["id"] for p in bob["projects"]} <= {foreign["id"]}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": -1},
        {"limit": 51},
        {"limit": "abc"},
        {"limit": 2.5},
        {"cursor": "!!!"},
        {"cursor": ""},
        {"cursor": "' OR '1'='1"},
        {"cursor": "x" * 200},
    ],
)
def test_list_projects_invalid_cursor_and_limit_are_safe(client, params):
    project = create(client)
    foreign = create_as(client, OTHER, "foreign-safe", goal="Bob secret goal")
    response = client.get("/api/projects", params=params, headers=AUTH)
    assert response.status_code == 422, response.text
    assert foreign["goal"] not in response.text
    assert project["id"] not in response.text
    # State is unchanged and a valid bounded request still works.
    assert client.get("/api/projects/" + project["id"], headers=AUTH).json() == project
    assert (
        client.get("/api/projects", params={"limit": 1}, headers=AUTH).json()[
            "projects"
        ][0]["id"]
        == project["id"]
    )
    assert (
        client.get("/api/projects", params={"limit": 50}, headers=AUTH).status_code
        == 200
    )


def test_restart_and_unknown_measurements(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        project = create(client)
        response = client.put(
            "/api/projects/" + project["id"] + "/inventory",
            json=requirements_update(project),
            headers=AUTH,
        )
        assert response.status_code == 200, response.text
        saved = response.json()["project"]
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        assert (
            client.get("/api/projects/" + project["id"], headers=AUTH).json() == saved
        )
    assert saved["stocks"][0]["thickness_mm"]["value"] is None
    assert saved["active_version_id"] is None
    assert saved["revision_id"] != project["revision_id"]
    assert saved["requirements"] == requirements()
    assert saved["requirements"]["constraints"]["device_mass_g"]["value"] is None


def test_replays_conflicts_and_stale_writes(client):
    project = create(client)
    assert create(client) == project
    conflicting = client.post(
        "/api/projects",
        json={"goal": "different", "idempotency_key": "create-001"},
        headers=AUTH,
    )
    assert conflicting.status_code == 409
    path = "/api/projects/" + project["id"] + "/inventory"
    body = requirements_update(project)
    first = client.put(path, json=body, headers=AUTH)
    assert first.status_code == 200
    newer = first.json()["project"]
    assert (
        client.put(path, json=update(newer, "inventory-002"), headers=AUTH).status_code
        == 200
    )
    replay = client.put(path, json=body, headers=AUTH)
    assert replay.json() == {**first.json(), "replayed": True}
    assert (
        client.put(
            path, json=requirements_update(project, "inventory-003"), headers=AUTH
        ).json()["code"]
        == "stale_version"
    )
    body["requirements"]["tools"] = ["Knife"]
    assert (
        client.put(path, json=body, headers=AUTH).json()["code"]
        == "idempotency_conflict"
    )


def test_concurrent_updates_have_one_winner(client):
    project = create(client)
    path = "/api/projects/" + project["id"] + "/inventory"

    def write(key):
        body = requirements_update(project, key)
        body["requirements"]["device_description"] = key
        body["stocks"][0]["condition"] = (
            "damaged" if key == "parallel-001" else "usable"
        )
        return client.put(path, json=body, headers=AUTH)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(write, ["parallel-001", "parallel-002"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(
        response.json()["project"]
        for response in responses
        if response.status_code == 200
    )
    assert client.get(path.removesuffix("/inventory"), headers=AUTH).json() == winner
    expected_condition = (
        "damaged"
        if winner["requirements"]["device_description"] == "parallel-001"
        else "usable"
    )
    assert winner["stocks"][0]["condition"] == expected_condition


@pytest.mark.parametrize(
    "invalid", ["duplicate", "image", "evidence", "unconfirmed", "extra"]
)
def test_reject_invalid_inventory_without_changing_state(client, invalid):
    project = create(client)
    body = update(project)
    if invalid == "duplicate":
        body["stocks"] *= 2
    elif invalid == "image":
        body["stocks"][0]["image_ids"] = ["foreign-image"]
    elif invalid == "evidence":
        body["stocks"][0]["width_mm"]["evidence_ids"] = ["foreign-evidence"]
    elif invalid == "unconfirmed":
        body["user_confirmed"] = False
    else:
        body["model_approved"] = True
    path = "/api/projects/" + project["id"]
    assert client.put(path + "/inventory", json=body, headers=AUTH).status_code == 422
    assert client.get(path, headers=AUTH).json() == project
    assert (
        client.put(
            path + "/inventory", json=requirements_update(project), headers=AUTH
        ).status_code
        == 200
    )


def test_delete_purges_data_and_replays(client, tmp_path):
    project = create(client)
    path = "/api/projects/" + project["id"]
    assert (
        client.put(
            path + "/inventory", json=requirements_update(project), headers=AUTH
        ).status_code
        == 200
    )
    headers = {**AUTH, "Idempotency-Key": "delete-001"}
    assert client.delete(path, headers=headers).status_code == 200
    assert client.delete(path, headers=headers).json()["replayed"] is True
    assert client.get(path, headers=AUTH).status_code == 404
    assert (
        client.put(path + "/inventory", json=update(project), headers=AUTH).status_code
        == 404
    )
    with sqlite3.connect(tmp_path / "projects.sqlite3") as db:
        rows = db.execute("SELECT response FROM requests").fetchall()
    assert len(rows) == 2
    assert all("A phone stand" not in row[0] and "stocks" not in row[0] for row in rows)
    assert all(
        "Test phone" not in row[0] and "requirements" not in row[0] for row in rows
    )
    assert (
        client.post(
            "/api/projects",
            json={"goal": "A phone stand", "idempotency_key": "create-001"},
            headers=AUTH,
        ).status_code
        == 404
    )


def test_unconfigured_auth_disables_access(tmp_path):
    with TestClient(create_app(tmp_path, {})) as client:
        assert (
            client.get("/api/projects/project-missing", headers=AUTH).status_code == 401
        )
    with pytest.raises(ValueError):
        create_app(tmp_path, {"owner": "short"})


def test_failed_receipt_write_rolls_back_inventory(client, monkeypatch):
    from forma_api.projects import ProjectStore

    project = create(client)
    path = "/api/projects/" + project["id"]
    original = ProjectStore.remember

    def fail(*args):
        raise sqlite3.OperationalError("simulated receipt write failure")

    monkeypatch.setattr(ProjectStore, "remember", staticmethod(fail))
    with pytest.raises(sqlite3.OperationalError):
        client.put(path + "/inventory", json=requirements_update(project), headers=AUTH)
    assert client.get(path, headers=AUTH).json() == project
    monkeypatch.setattr(ProjectStore, "remember", staticmethod(original))
    assert (
        client.put(path + "/inventory", json=update(project), headers=AUTH).status_code
        == 200
    )


def test_replay_is_scoped_to_owner_and_project(client):
    first = create(client)
    path = "/api/projects/" + first["id"] + "/inventory"
    body = update(first)
    assert client.put(path, json=body, headers=AUTH).status_code == 200
    assert client.put(path, json=body, headers=OTHER).status_code == 404
    second = create(client, "create-002")
    assert (
        client.put(
            "/api/projects/" + second["id"] + "/inventory",
            json=update(second),
            headers=AUTH,
        ).status_code
        == 200
    )
    own = client.post(
        "/api/projects",
        json={"goal": "Bob's stand", "idempotency_key": "create-001"},
        headers=OTHER,
    )
    assert own.status_code == 201
    assert own.json()["project"]["id"] not in {first["id"], second["id"]}


def test_requirements_omission_preserves_and_explicit_null_clears(client):
    project = create(client)
    path = "/api/projects/" + project["id"] + "/inventory"
    body = requirements_update(project)
    body["requirements"]["tools"] = [" Ruler ", "Scissors"]
    response = client.put(path, json=body, headers=AUTH)
    assert response.status_code == 200
    saved = response.json()["project"]
    assert saved["requirements"] == requirements()
    omitted = update(saved, "inventory-002")
    response = client.put(path, json=omitted, headers=AUTH)
    assert response.status_code == 200
    preserved = response.json()["project"]
    assert preserved["requirements"] == requirements()
    changed_retry = {**omitted, "requirements": None}
    assert (
        client.put(path, json=changed_retry, headers=AUTH).json()["code"]
        == "idempotency_conflict"
    )
    assert client.get(path.removesuffix("/inventory"), headers=AUTH).json() == preserved
    clear = {**update(preserved, "inventory-003"), "requirements": None}
    response = client.put(path, json=clear, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["project"]["requirements"] is None


@pytest.mark.parametrize(
    "tools", [[" "], ["Ruler", " ruler "], ["x" * 81], ["tool"] * 33]
)
def test_invalid_tools_do_not_change_saved_inventory(client, tools):
    project = create(client)
    path = "/api/projects/" + project["id"]
    body = requirements_update(project)
    body["requirements"]["tools"] = tools
    assert client.put(path + "/inventory", json=body, headers=AUTH).status_code == 422
    assert client.get(path, headers=AUTH).json() == project
    assert (
        client.put(
            path + "/inventory", json=requirements_update(project), headers=AUTH
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "field,value,confirmed",
    [
        ("device_mass_g", 0, True),
        ("device_mass_g", -1, True),
        ("device_mass_g", 200, False),
        ("support_angle_deg", 0, True),
        ("support_angle_deg", 90, True),
        ("support_angle_deg", 100, True),
        ("support_angle_deg", 60, False),
        ("max_footprint_width_mm", -1, True),
        ("max_footprint_width_mm", 200, False),
        ("max_footprint_height_mm", 0, True),
        ("max_footprint_height_mm", 200, False),
    ],
)
def test_invalid_requirement_measurements_leave_state_unchanged(
    client, field, value, confirmed
):
    project = create(client)
    path = "/api/projects/" + project["id"]
    body = requirements_update(project)
    body["requirements"]["constraints"][field].update(
        value=value, source="user_ruler", confirmed=confirmed
    )
    assert client.put(path + "/inventory", json=body, headers=AUTH).status_code == 422
    assert client.get(path, headers=AUTH).json() == project


@pytest.mark.parametrize("unresolved", ["profile", "evidence"])
def test_requirements_reject_unresolved_trusted_inputs(client, unresolved):
    project = create(client)
    path = "/api/projects/" + project["id"]
    body = requirements_update(project)
    constraints = body["requirements"]["constraints"]
    if unresolved == "profile":
        constraints["allowed_profile_ids"] = ["invented-profile"]
    else:
        constraints["support_angle_deg"]["evidence_ids"] = ["foreign-evidence"]
    assert client.put(path + "/inventory", json=body, headers=AUTH).status_code == 422
    assert client.get(path, headers=AUTH).json() == project


def test_active_plan_blocks_inventory_and_requirements_together(client, tmp_path):
    import json

    project = create(client)
    path = "/api/projects/" + project["id"]
    with sqlite3.connect(tmp_path / "projects.sqlite3") as db:
        project["active_version_id"] = "plan-v1"
        db.execute(
            "UPDATE projects SET body=? WHERE id=?",
            (json.dumps(project), project["id"]),
        )
    response = client.put(
        path + "/inventory", json=requirements_update(project), headers=AUTH
    )
    assert response.status_code == 409
    assert response.json()["code"] == "blocked"
    assert client.get(path, headers=AUTH).json() == project
