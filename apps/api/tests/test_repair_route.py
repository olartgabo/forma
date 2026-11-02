import json

import pytest
from fastapi.testclient import TestClient
from test_plans import AUTH, OTHER, TOKENS, prepared

from forma_api import adapt, repair_runtime
from forma_api.main import create_app
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.plans import PlanService
from forma_api.projects import ProjectStore


class Fake:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, path, payload, timeout):
        self.calls.append((path, json.loads(json.dumps(payload)), timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def final(candidates=None, questions=None):
    value = {"candidates": candidates or [], "questions": questions or []}
    return {
        "choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps(value)}}
        ]
    }


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        yield client


def install(monkeypatch, fake):
    counter = {"factory": 0}

    def factory():
        counter["factory"] += 1
        return MetaGateway(fake)

    monkeypatch.setattr(repair_runtime, "default_gateway_factory", factory)
    return counter


def active_project(client, tmp_path):
    project, preview, context = prepared(client)
    # Add spare stock like adapt tests so replace_part can be feasible.
    sheet = project["stocks"][0]
    spare = {
        **sheet,
        "id": "synthetic-spare",
        "usable_regions": [
            {**sheet["usable_regions"][0], "id": "synthetic-spare-region"}
        ],
    }
    saved = client.put(
        f"/api/projects/{project['id']}/inventory",
        headers=AUTH,
        json={
            "expected_revision_id": project["revision_id"],
            "idempotency_key": "inventory-spare",
            "stocks": project["stocks"] + [spare],
            "user_confirmed": True,
        },
    )
    assert saved.status_code == 200, saved.text
    project = saved.json()["project"]
    preview = preview.model_copy(
        update={"expected_revision_id": project["revision_id"]}
    )
    service = PlanService(ProjectStore(tmp_path), allow_synthetic=True)
    result = service.compile_preview("alice", project["id"], preview, **context)
    assert result.status == "accepted", result.model_dump()
    version = result.version
    activated = client.post(
        f"/api/projects/{project['id']}/plans/{version.version_id}/activate",
        headers=AUTH,
        json={
            "expected_revision_id": project["revision_id"],
            "idempotency_key": "activate-repair-1",
            "user_approved": True,
        },
    )
    assert activated.status_code == 200, activated.text
    return activated.json()["project"], version


def resize_candidate(plan):
    return {
        "id": "patch-resize-1",
        "base_version_id": plan.version_id,
        "kind": "resize_part",
        "target_id": plan.parts[0].id,
        "replacement_stock_id": None,
        "replacement_profile_id": None,
        "width_mm": 80,
        "height_mm": 150,
        "angle_deg": None,
        "rationale": "Resize part",
    }


def body(project, version, **overrides):
    plan = version.plan
    value = {
        "expected_version_id": plan.version_id,
        "expected_last_event_id": None,
        "reported_problem": "The slot tore",
        "diagnosis": {
            "visible_observations": ["A tear is visible"],
            "hypotheses": ["Slot may be weak"],
            "questions_or_measurements": [],
            "affected_ids": [plan.parts[0].id],
            "failure_type": "torn_slot",
        },
        "provider_context_consented": True,
    }
    value.update(overrides)
    return value


def call(client, project, payload, auth=AUTH):
    return client.post(
        f"/api/projects/{project['id']}/repairs/propose", json=payload, headers=auth
    )


def snapshots(client, project, version):
    pid = project["id"]
    proj = client.get(f"/api/projects/{pid}", headers=AUTH).json()
    prog = client.get(
        f"/api/projects/{pid}/versions/{version.version_id}/progress", headers=AUTH
    ).json()
    return proj, prog


def test_success_and_simulate_handoff(client, monkeypatch, tmp_path):
    monkeypatch.setattr(adapt, "ALLOW_SYNTHETIC", True)
    project, version = active_project(client, tmp_path)
    plan = version.plan
    replace = {
        "id": "replace-brace",
        "base_version_id": plan.version_id,
        "kind": "replace_part",
        "target_id": "stand-brace",
        "replacement_stock_id": "synthetic-spare",
        "replacement_profile_id": None,
        "width_mm": None,
        "height_mm": None,
        "angle_deg": None,
        "rationale": "Replace damaged brace from spare",
    }
    fake = Fake(final(candidates=[replace]))
    install(monkeypatch, fake)
    before = snapshots(client, project, version)
    response = call(client, project, body(project, version))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["base_version_id"] == plan.version_id
    assert result["base_last_event_id"] is None
    assert [c["id"] for c in result["candidates"]] == ["replace-brace"]
    assert result["diagnostics"]["status"] == "ok"
    assert len(fake.calls) == 1
    assert snapshots(client, project, version) == before
    # Hand-off: candidates consumed unchanged by adapt/simulate.
    simulate = client.post(
        f"/api/projects/{project['id']}/adapt/simulate",
        headers=AUTH,
        json={
            "expected_version_id": plan.version_id,
            "expected_last_event_id": None,
            "idempotency_key": "simulate-repair-1",
            "candidates": result["candidates"],
            "connector_measurements": [],
            "remaining_confirmed": True,
        },
    )
    assert simulate.status_code == 200, simulate.text
    assert simulate.json()["previews"][0]["patch"]["id"] == "replace-brace"


def test_question_only_success(client, monkeypatch, tmp_path):
    project, version = active_project(client, tmp_path)
    fake = Fake(final(questions=["Measure the brace width?"]))
    install(monkeypatch, fake)
    response = call(client, project, body(project, version))
    assert response.status_code == 200, response.text
    assert response.json()["candidates"] == []
    assert response.json()["questions"] == ["Measure the brace width?"]


def test_gates_no_provider_call(client, monkeypatch, tmp_path):
    project, version = active_project(client, tmp_path)
    fake = Fake(final(candidates=[resize_candidate(version.plan)]))
    counter = install(monkeypatch, fake)
    # other owner 404
    assert call(client, project, body(project, version), OTHER).status_code == 404
    # stale version
    r = call(
        client, project, body(project, version, expected_version_id="version-other")
    )
    assert (r.status_code, r.json()["code"]) == (409, "stale_version")
    # stale last event
    r = call(client, project, body(project, version, expected_last_event_id="event-x"))
    assert (r.status_code, r.json()["code"]) == (409, "stale_version")
    # foreign diagnosis IDs
    bad_diag = {
        **body(project, version)["diagnosis"],
        "affected_ids": ["part-invented"],
    }
    r = call(client, project, body(project, version, diagnosis=bad_diag))
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    # empty diagnosis
    empty_diag = {
        "visible_observations": [],
        "hypotheses": [],
        "questions_or_measurements": [],
        "affected_ids": [],
        "failure_type": "unknown",
    }
    r = call(client, project, body(project, version, diagnosis=empty_diag))
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    # consent missing
    r = call(client, project, body(project, version, provider_context_consented=False))
    assert (r.status_code, r.json()["code"]) == (422, "consent_required")
    payload = body(project, version)
    del payload["provider_context_consented"]
    r = call(client, project, payload)
    assert (r.status_code, r.json()["code"]) == (422, "consent_required")
    assert counter["factory"] == 0 and fake.calls == []


def test_no_active_plan(client, monkeypatch):
    project = client.post(
        "/api/projects",
        headers=AUTH,
        json={"goal": "stand", "idempotency_key": "project-001"},
    ).json()["project"]
    fake = Fake(final())
    counter = install(monkeypatch, fake)
    payload = {
        "expected_version_id": "version-1",
        "expected_last_event_id": None,
        "reported_problem": "tore",
        "diagnosis": {
            "visible_observations": ["tear"],
            "hypotheses": [],
            "questions_or_measurements": [],
            "affected_ids": [],
            "failure_type": "unknown",
        },
        "provider_context_consented": True,
    }
    r = client.post(
        f"/api/projects/{project['id']}/repairs/propose", json=payload, headers=AUTH
    )
    assert r.status_code == 409 and r.json()["code"] == "stale_version"
    assert counter["factory"] == 0


def test_provider_not_configured(client, monkeypatch, tmp_path):
    project, version = active_project(client, tmp_path)

    def factory():
        raise ValueError("missing key")

    monkeypatch.setattr(repair_runtime, "default_gateway_factory", factory)
    before = snapshots(client, project, version)
    r = call(client, project, body(project, version))
    assert (r.status_code, r.json()["code"]) == (503, "provider_not_configured")
    assert snapshots(client, project, version) == before


@pytest.mark.parametrize(
    "gateway_code,status,code",
    [
        ("timeout", 504, "timeout"),
        ("rate_limit", 429, "rate_limit"),
        ("invalid_proposal", 502, "invalid_response"),
    ],
)
def test_provider_errors_redacted(
    client, monkeypatch, tmp_path, gateway_code, status, code
):
    project, version = active_project(client, tmp_path)
    # Inject raw provider text into the exception passed to Fake. The
    # gateway code stays stable, but str(exc) now carries the marker, so
    # any route that echoes the exception/provider body would leak it.
    provider_error = GatewayError(gateway_code)
    provider_error.args = (gateway_code, "SECRET_PROVIDER_BODY")
    assert "SECRET_PROVIDER_BODY" in str(provider_error)
    fake = Fake(provider_error)
    install(monkeypatch, fake)
    before = snapshots(client, project, version)
    r = call(client, project, body(project, version))
    assert (r.status_code, r.json()["code"]) == (status, code)
    assert "SECRET_PROVIDER_BODY" not in r.text
    assert snapshots(client, project, version) == before


def test_provider_invalid_json_redacted(client, monkeypatch, tmp_path):
    project, version = active_project(client, tmp_path)
    fake = Fake(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "SECRET_PROVIDER_BODY not json"},
                }
            ]
        }
    )
    install(monkeypatch, fake)
    r = call(client, project, body(project, version))
    assert (r.status_code, r.json()["code"]) == (502, "invalid_response")
    assert "SECRET_PROVIDER_BODY" not in r.text


def test_invalid_candidate_from_provider_is_502(client, monkeypatch, tmp_path):
    project, version = active_project(client, tmp_path)
    bad = resize_candidate(version.plan)
    bad["target_id"] = "part-invented"
    fake = Fake(final(candidates=[bad]))
    install(monkeypatch, fake)
    before = snapshots(client, project, version)
    r = call(client, project, body(project, version))
    assert (r.status_code, r.json()["code"]) == (502, "invalid_response")
    assert snapshots(client, project, version) == before
