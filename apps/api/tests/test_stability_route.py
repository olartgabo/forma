"""Synthetic adapter checks; none are physical evidence."""

import sqlite3
from datetime import UTC, datetime
from typing import Annotated

import pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient
from test_plans import AUTH, OTHER, TOKENS, approval, prepared

from forma_api.main import create_app
from forma_api.plans import PlanService
from forma_api.projects import ProjectStore
from forma_api.routes.stability import stability_router
from forma_domain.models import PhysicalEvent


@pytest.fixture
def connected(tmp_path):
    app = create_app(tmp_path, TOKENS)
    store = ProjectStore(tmp_path)

    def authenticate(authorization: Annotated[str | None, Header()] = None):
        for owner, token in TOKENS.items():
            if authorization == "Bearer " + token:
                return owner
        raise HTTPException(401)

    # Separate prefix exercises the factory without relying on production registration.
    app.include_router(stability_router(store, authenticate), prefix="/test")
    with TestClient(app) as client:
        project, body, context = prepared(client)
        version = (
            PlanService(store, allow_synthetic=True)
            .compile_preview("alice", project["id"], body, **context)
            .version
        )
        base = "/api/projects/" + project["id"]
        assert (
            client.post(
                base + "/plans/" + version.version_id + "/activate",
                headers=AUTH,
                json=approval(project),
            ).status_code
            == 200
        )
        payload = dict(
            plan_version_id=version.version_id,
            expected_inventory_revision_id=project["revision_id"],
            expected_last_event_id=None,
        )
        yield (
            client,
            "/test/" + project["id"] + "/stability/analyses",
            payload,
            tmp_path,
        )


def test_default_is_blocked_and_read_only(connected):
    client, url, payload, directory = connected
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        before = tuple(db.iterdump())
    response = client.post(url, headers=AUTH, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["status"] == "needs_measurement"
    assert response.json()["report"] is None
    assert response.json()["geometry_preview"]["stage"] == "planned_preview"
    assert len(response.json()["blockers"]) == 4
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert tuple(db.iterdump()) == before


def test_production_routes_registered_and_authenticated(connected):
    client, url, payload, _ = connected
    production = url.replace("/test/", "/api/projects/")
    context_url = production.removesuffix("analyses") + "context"
    params = {"plan_version_id": payload["plan_version_id"]}
    assert client.get(context_url, params=params).status_code == 401
    assert client.post(production, json=payload).status_code == 401
    assert client.get(context_url, params=params, headers=OTHER).status_code == 404
    context = client.get(context_url, params=params, headers=AUTH)
    assert context.status_code == 200, context.text
    response = client.post(production, json=payload, headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "needs_measurement"
    assert response.json()["report"] is None
    assert (
        response.json()["geometry_preview"]["plan_version_id"]
        == payload["plan_version_id"]
    )


def test_owner_scope_and_authentication(connected):
    client, url, payload, _ = connected
    assert client.post(url, json=payload).status_code == 401
    assert client.post(url, headers=OTHER, json=payload).status_code == 404


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("expected_inventory_revision_id", "stale", 409),
        ("expected_last_event_id", "stale", 409),
        ("plan_version_id", "other-project-plan", 404),
    ],
)
def test_stale_or_foreign_snapshot_rejected(connected, field, value, status):
    client, url, payload, _ = connected
    assert (
        client.post(url, headers=AUTH, json=payload | {field: value}).status_code
        == status
    )


def test_required_cursor_and_no_client_physics(connected):
    client, url, payload, _ = connected
    missing = dict(payload)
    missing.pop("expected_last_event_id")
    assert client.post(url, headers=AUTH, json=missing).status_code == 422
    assert (
        client.post(url, headers=AUTH, json=payload | {"mass": 1.0}).status_code == 422
    )


def test_context_preserves_prior_version_cursor_and_owner_scope(connected):
    client, url, payload, directory = connected
    project_id = url.split("/")[2]
    event = PhysicalEvent(
        id="analytic-history",
        project_id=project_id,
        version_id="prior-version",
        kind="observation",
        recorded_at=datetime.now(UTC),
        actor="user",
        observation="Analytic history fixture only",
        verification_state="not_checked",
    )
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        db.execute(
            "INSERT INTO plans SELECT ?, project_id, inventory_revision_id, body, process, parameters FROM plans WHERE version_id=?",
            ("prior-version", payload["plan_version_id"]),
        )
        db.execute(
            "INSERT INTO progress_events VALUES (?,?,?,?)",
            (event.id, project_id, event.version_id, event.model_dump_json()),
        )
    context_url = url.removesuffix("analyses") + "context"
    params = {"plan_version_id": payload["plan_version_id"]}
    assert client.get(context_url, params=params, headers=OTHER).status_code == 404
    assert client.get(context_url, params=params).status_code == 401
    response = client.get(context_url, params=params, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["last_event_id"] == event.id
    assert response.headers["cache-control"] == "no-store"
    assert client.post(url, headers=AUTH, json=payload).status_code == 409
    assert (
        client.post(
            url, headers=AUTH, json=payload | {"expected_last_event_id": event.id}
        ).status_code
        == 200
    )
    assert (
        client.get(
            context_url, params={"plan_version_id": "prior-version"}, headers=AUTH
        ).status_code
        == 409
    )
    assert (
        client.post(
            url, headers=AUTH, json=payload | {"plan_version_id": "prior-version"}
        ).status_code
        == 409
    )
