"""Saved engine geometry reads only; software fixtures, no provider or physical pass."""

import json
import sqlite3

import pytest
from forma_stability.geometry import project_nominal_geometry
from test_plans import AUTH, OTHER
from test_stability_runtime import authorized

from forma_api.projects import ProjectStore

pytest_plugins = ["test_stability_route", "test_muse_construction_runtime"]


def endpoint(connected):
    _, _, body, _ = connected
    snap = authorized(connected)
    return (
        f"/api/projects/{snap.project.id}/versions/{snap.version.version_id}/geometry",
        {"expected_inventory_revision_id": body["expected_inventory_revision_id"]},
    )


def test_saved_geometry_matches_engine_and_never_writes(connected, monkeypatch):
    client, _, _, directory = connected
    url, params = endpoint(connected)
    snap = authorized(connected)
    from forma_api import design_runtime, stability_runtime

    monkeypatch.setattr(
        stability_runtime, "analyze", lambda *a, **k: pytest.fail("analysis called")
    )
    monkeypatch.setattr(
        design_runtime,
        "default_gateway_factory",
        lambda: pytest.fail("provider called"),
    )
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        before = tuple(db.iterdump())
    response = client.get(url, params=params, headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == project_nominal_geometry(snap.version.plan).model_dump(
        mode="json"
    )
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert tuple(db.iterdump()) == before


def test_geometry_auth_scope_revision_and_version(connected):
    client, _, _, _ = connected
    url, params = endpoint(connected)
    assert client.get(url, params=params).status_code == 401
    assert client.get(url, params=params, headers=OTHER).status_code == 404
    assert (
        client.get(
            url, params={"expected_inventory_revision_id": "stale"}, headers=AUTH
        ).status_code
        == 409
    )
    snap = authorized(connected)
    assert (
        client.get(
            url.replace(snap.version.version_id, "foreign-version"),
            params=params,
            headers=AUTH,
        ).status_code
        == 404
    )


def test_unsupported_plan_does_not_return_stand_fallback(connected, monkeypatch):
    from forma_stability.geometry import UnsupportedGeometry

    from forma_api.routes import stability

    def unsupported(*a, **k):
        raise UnsupportedGeometry("Unsupported saved model")

    monkeypatch.setattr(stability, "project_nominal_geometry", unsupported)
    client, _, _, _ = connected
    url, params = endpoint(connected)
    response = client.get(url, params=params, headers=AUTH)
    assert response.status_code == 422
    assert "facets" not in response.json()


def test_generic_completed_receipt_uses_actual_engine_facets(
    inputs, tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient
    from test_muse_construction_runtime import candidate, response, run
    from test_plans import TOKENS
    from test_projects import create

    from forma_api import design_runtime
    from forma_api.main import create_app

    result, _ = run(inputs, response(candidate()))
    monkeypatch.setattr(
        design_runtime,
        "default_gateway_factory",
        lambda: pytest.fail("provider called"),
    )
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        p = create(client)
        saved = result.model_copy(
            update={"project_id": p["id"], "inventory_revision_id": p["revision_id"]}
        )
        store = ProjectStore(tmp_path)

        def receipt(key, value):
            with store.transaction() as db:
                db.execute(
                    "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                    (
                        "alice",
                        p["id"] + ":construction-proposal",
                        key,
                        "test-digest",
                        value,
                    ),
                )

        url = f"/api/projects/{p['id']}/construction/preview"
        params = {"expected_inventory_revision_id": p["revision_id"]}
        assert client.get(url, params=params, headers=AUTH).status_code == 404
        receipt(
            "foreign-project",
            saved.model_copy(update={"project_id": "foreign"}).model_dump_json(),
        )
        assert client.get(url, params=params, headers=AUTH).status_code == 409
        receipt(
            "stale-revision",
            saved.model_copy(
                update={"inventory_revision_id": "stale"}
            ).model_dump_json(),
        )
        assert client.get(url, params=params, headers=AUTH).status_code == 409
        receipt("completed", saved.model_dump_json())
        with sqlite3.connect(tmp_path / "projects.sqlite3") as db:
            before = tuple(db.iterdump())
        fetched = client.get(url, params=params, headers=AUTH)
        assert fetched.status_code == 200, fetched.text
        assert fetched.headers["cache-control"] == "no-store"
        assert (
            fetched.json()["candidates"][0]["construction"]["steps"][-1]["analysis"][
                "facets"
            ]
            == result.model_dump(mode="json")["candidates"][0]["construction"]["steps"][
                -1
            ]["analysis"]["facets"]
        )
        assert client.get(url, params=params).status_code == 401
        assert client.get(url, params=params, headers=OTHER).status_code == 404
        assert (
            client.get(
                url, params={"expected_inventory_revision_id": "stale"}, headers=AUTH
            ).status_code
            == 409
        )
        with sqlite3.connect(tmp_path / "projects.sqlite3") as db:
            assert tuple(db.iterdump()) == before
        receipt("unknown-latest", json.dumps({"pending": True, "uncertain": True}))
        assert client.get(url, params=params, headers=AUTH).status_code == 409
