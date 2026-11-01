"""FastAPI design-generation boundary checks; fake transport, no provider."""

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_plans import AUTH, OTHER, TOKENS, prepared

from forma_api import design_runtime
from forma_api.design_context import DesignContext, StaticDesignContextResolver
from forma_api.main import create_app
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.plans import CompilePreview, PlanService
from forma_api.projects import ProjectStore


class Fake:
    def __init__(self, *responses, on_final=None):
        self.responses = list(responses)
        self.calls = []
        self.on_final = on_final

    def post(self, path, payload, timeout):
        self.calls.append((path, json.loads(json.dumps(payload)), timeout))
        if len(self.calls) == 2 and self.on_final:
            self.on_final()
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def tool_call(project_id, revision_id):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "get_project_snapshot",
                                "arguments": json.dumps(
                                    {
                                        "project_id": project_id,
                                        "inventory_revision_id": revision_id,
                                    }
                                ),
                            },
                        }
                    ]
                },
            }
        ]
    }


def final(payload):
    return {
        "choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps(payload)}}
        ]
    }


def context_for(project, context, **overrides):
    values = dict(
        project_id=project["id"],
        inventory_revision_id=project["revision_id"],
        process=context["process"],
        parameters=context["parameters"],
        joint_profiles=context["joint_profiles"],
        kerf_mm=context["kerf_mm"],
        edge_margin_mm=context["edge_margin_mm"],
    )
    values.update(overrides)
    return DesignContext(**values)


def install(monkeypatch, fake, design_context, synthetic=True):
    counter = {"factory": 0}

    def factory():
        counter["factory"] += 1
        return MetaGateway(fake)

    monkeypatch.setattr(design_runtime, "default_gateway_factory", factory)
    monkeypatch.setattr(
        design_runtime,
        "default_context_resolver",
        lambda: StaticDesignContextResolver(design_context),
    )
    if synthetic:
        monkeypatch.setattr(
            design_runtime,
            "default_plan_service",
            lambda store: PlanService(store, allow_synthetic=True),
        )
    return counter


def body(project, **overrides):
    value = {
        "expected_revision_id": project["revision_id"],
        "user_notes": "Prefer a compact stand",
        "idempotency_key": "design-001",
        "provider_context_consented": True,
    }
    value.update(overrides)
    return value


def generate(client, project, payload=None, auth=AUTH):
    return client.post(
        f"/api/projects/{project['id']}/designs/generate",
        json=payload or body(project),
        headers=auth,
    )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        project, preview, context = prepared(client)
        candidate = preview.candidate
        yield client, project, candidate, context, monkeypatch, tmp_path


def success_fake(project, candidate, **kwargs):
    return Fake(
        tool_call(project["id"], project["revision_id"]),
        final({"candidates": [candidate.model_dump(mode="json")], "questions": []}),
        **kwargs,
    )


def test_success_compiles_saved_preview_replay_and_changed_context(setup):
    client, project, candidate, context, monkeypatch, _ = setup
    fake = success_fake(project, candidate)
    counter = install(monkeypatch, fake, context_for(project, context))
    assert counter["factory"] == 0
    spec = client.get("/openapi.json")
    assert "/api/projects/{project_id}/designs/generate" in spec.json()["paths"]
    response = generate(client, project)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "proposed"
    assert result["project_id"] == project["id"]
    assert result["inventory_revision_id"] == project["revision_id"]
    assert result["candidates"][0]["status"] == "accepted"
    version_id = result["candidates"][0]["version"]["version_id"]
    assert result["diagnostics"]["tool_executions"] == 1
    assert result["diagnostics"]["model_rounds"] == 2
    plans = client.get(f"/api/projects/{project['id']}/plans", headers=AUTH).json()
    assert [plan["version_id"] for plan in plans["plans"]] == [version_id]
    manual = client.get(
        f"/api/projects/{project['id']}/manual/{version_id}", headers=AUTH
    )
    assert manual.status_code == 200 and len(manual.json()["panels"]) == 8
    assert (
        client.get(f"/api/projects/{project['id']}", headers=AUTH).json()[
            "active_version_id"
        ]
        is None
    )
    replay = generate(client, project)
    assert replay.json()["replayed"] is True
    assert len(fake.calls) == 2 and counter["factory"] == 1
    # Changed notes with the same key conflict before another provider call.
    changed = generate(client, project, body(project, user_notes="different"))
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_conflict"
    # Changed resolved context with the same key also conflicts.
    install(
        monkeypatch,
        fake,
        context_for(project, context, kerf_mm=3),
    )
    conflict = generate(client, project)
    assert conflict.status_code == 409
    assert len(fake.calls) == 2


def test_gates_have_zero_dispatch(setup):
    client, project, candidate, context, monkeypatch, _ = setup
    fake = success_fake(project, candidate)
    counter = install(monkeypatch, fake, context_for(project, context))
    path_payload = body(project)
    assert (
        client.post(
            f"/api/projects/{project['id']}/designs/generate", json=path_payload
        ).status_code
        == 401
    )
    assert generate(client, project, auth=OTHER).status_code == 404
    for payload, status, code in (
        (body(project, provider_context_consented=False), 422, "consent_required"),
        (body(project, expected_revision_id="inventory-stale"), 409, "stale_version"),
    ):
        response = generate(client, project, payload)
        assert (response.status_code, response.json()["code"]) == (status, code)
    for payload in (
        body(project, provider_context_consented="true"),
        body(project, stocks=[]),
        body(project, process=None),
        {k: v for k, v in body(project).items() if k != "provider_context_consented"},
    ):
        response = generate(client, project, payload)
        assert response.status_code == 422, response.text
        assert response.json()["code"] in ("validation_error", "consent_required")
        if response.json()["code"] == "validation_error":
            assert response.json()["message"] == "Request validation failed"
    assert counter["factory"] == 0 and fake.calls == []


def test_active_and_capacity_gates_have_zero_dispatch(setup):
    client, project, candidate, context, monkeypatch, tmp_path = setup
    store_service = PlanService(ProjectStore(tmp_path), allow_synthetic=True)
    preview = CompilePreview(
        expected_revision_id=project["revision_id"],
        idempotency_key="preview-001",
        candidate=candidate,
    )
    compile_context = dict(
        process=context["process"],
        parameters=context["parameters"],
        joint_profiles=context["joint_profiles"],
        kerf_mm=context["kerf_mm"],
        edge_margin_mm=context["edge_margin_mm"],
    )
    first = store_service.compile_preview(
        "alice", project["id"], preview, **compile_context
    )
    assert first.status == "accepted"
    store_service.compile_preview(
        "alice",
        project["id"],
        preview.model_copy(update={"idempotency_key": "preview-002"}),
        **compile_context,
    )
    fake = success_fake(project, candidate)
    counter = install(monkeypatch, fake, context_for(project, context))
    response = generate(client, project)
    assert response.status_code == 409
    assert counter["factory"] == 0 and fake.calls == []


def test_active_plan_gate_has_zero_dispatch(setup):
    client, project, candidate, context, monkeypatch, tmp_path = setup
    service = PlanService(ProjectStore(tmp_path), allow_synthetic=True)
    preview = CompilePreview(
        expected_revision_id=project["revision_id"],
        idempotency_key="preview-001",
        candidate=candidate,
    )
    version = service.compile_preview(
        "alice",
        project["id"],
        preview,
        process=context["process"],
        parameters=context["parameters"],
        joint_profiles=context["joint_profiles"],
        kerf_mm=context["kerf_mm"],
        edge_margin_mm=context["edge_margin_mm"],
    ).version
    activated = client.post(
        f"/api/projects/{project['id']}/plans/{version.version_id}/activate",
        headers=AUTH,
        json={
            "expected_revision_id": project["revision_id"],
            "idempotency_key": "activate-001",
            "user_approved": True,
        },
    )
    assert activated.status_code == 200
    fake = success_fake(project, candidate)
    counter = install(monkeypatch, fake, context_for(project, context))
    response = generate(client, project)
    assert response.status_code == 409
    assert counter["factory"] == 0 and fake.calls == []


def test_missing_context_questions_and_invalid_profile(setup):
    client, project, candidate, context, monkeypatch, _ = setup
    fake = Fake(
        tool_call(project["id"], project["revision_id"]),
        final({"candidates": [], "questions": ["Measure the sheet thickness."]}),
    )
    install(monkeypatch, fake, None)
    response = generate(client, project)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "needs_measurement"
    assert result["questions"] == ["Measure the sheet thickness."]
    assert result["candidates"] == []
    assert result["blockers"]
    assert (
        client.get(f"/api/projects/{project['id']}/plans", headers=AUTH).json()["plans"]
        == []
    )


def test_provider_error_is_safe_and_retryable_with_same_key(setup):
    client, project, candidate, context, monkeypatch, _ = setup
    fake = Fake(
        GatewayError("rate_limit"),
        tool_call(project["id"], project["revision_id"]),
        final({"candidates": [candidate.model_dump(mode="json")], "questions": []}),
    )
    install(monkeypatch, fake, context_for(project, context))
    first = generate(client, project)
    assert (first.status_code, first.json()["code"]) == (429, "rate_limit")
    assert "PRIVATE" not in first.text
    second = generate(client, project)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "proposed"


def test_revision_change_on_final_round_returns_stale_without_receipt(setup):
    client, project, candidate, context, monkeypatch, tmp_path = setup

    def mutate():
        with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
            row = connection.execute(
                "SELECT body FROM projects WHERE id=?", (project["id"],)
            ).fetchone()
            data = json.loads(row[0])
            data["revision_id"] = "inventory-changed"
            connection.execute(
                "UPDATE projects SET body=? WHERE id=?",
                (json.dumps(data), project["id"]),
            )

    fake = success_fake(project, candidate, on_final=mutate)
    install(monkeypatch, fake, context_for(project, context))
    response = generate(client, project)
    assert response.status_code == 409
    assert response.json()["code"] == "stale_version"
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM requests WHERE scope LIKE '%design-generation'"
            ).fetchone()[0]
            == 0
        )


def test_concurrent_same_request_starts_one_generation(setup):
    client, project, candidate, context, monkeypatch, _ = setup
    fake = Fake(
        tool_call(project["id"], project["revision_id"]),
        final({"candidates": [candidate.model_dump(mode="json")], "questions": []}),
        on_final=lambda: time.sleep(0.4),
    )
    install(monkeypatch, fake, context_for(project, context))

    def call(_):
        return generate(client, project).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(call, range(2)))
    assert statuses == [200, 409]
    assert len(fake.calls) == 2
    assert (
        len(
            client.get(f"/api/projects/{project['id']}/plans", headers=AUTH).json()[
                "plans"
            ]
        )
        == 1
    )


def test_project_deletion_purges_generation_receipt(setup):
    client, project, candidate, context, monkeypatch, tmp_path = setup
    fake = success_fake(project, candidate)
    install(monkeypatch, fake, context_for(project, context))
    assert generate(client, project).status_code == 200
    assert (
        client.delete(
            f"/api/projects/{project['id']}",
            headers={**AUTH, "Idempotency-Key": "delete-001"},
        ).status_code
        == 200
    )
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM requests WHERE scope LIKE '%design-generation'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0
