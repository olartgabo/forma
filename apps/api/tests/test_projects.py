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
