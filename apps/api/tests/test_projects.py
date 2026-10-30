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
            json=update(project),
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
    body = update(project)
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
        client.put(path, json=update(project, "inventory-003"), headers=AUTH).json()[
            "code"
        ]
        == "stale_version"
    )
    body["stocks"][0]["condition"] = "damaged"
    assert (
        client.put(path, json=body, headers=AUTH).json()["code"]
        == "idempotency_conflict"
    )


def test_concurrent_updates_have_one_winner(client):
    project = create(client)
    path = "/api/projects/" + project["id"] + "/inventory"

    def write(key):
        return client.put(path, json=update(project, key), headers=AUTH).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ["parallel-001", "parallel-002"])) == [200, 409]


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
        client.put(path + "/inventory", json=update(project), headers=AUTH).status_code
        == 200
    )


def test_delete_purges_data_and_replays(client, tmp_path):
    project = create(client)
    path = "/api/projects/" + project["id"]
    assert (
        client.put(path + "/inventory", json=update(project), headers=AUTH).status_code
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
        client.put(path + "/inventory", json=update(project), headers=AUTH)
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
