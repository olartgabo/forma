"""Saved-material proposal boundary; all evidence records below are test data."""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from forma_compiler import CutProcess
from forma_stability.generic_examples import assembly_example
from test_plans import AUTH, OTHER, TOKENS, stand_inputs
from test_projects import create

from forma_api import design_context, design_runtime
from forma_api.design_context import DesignContext, StaticDesignContextResolver
from forma_api.main import create_app
from forma_api.projects import ProjectStore


def db_state(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        names = [
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        return {
            name: connection.execute(
                f'SELECT * FROM "{name}" ORDER BY rowid'
            ).fetchall()
            for name in names
        }


def request(project, **changes):
    target = assembly_example("box").model_dump(mode="json")
    target["assembly"]["project_id"] = target["snapshot"]["project_id"] = project["id"]
    target["snapshot"]["inventory_revision"] = project["revision_id"]
    for part in target["assembly"]["parts"]:
        for facet in part["facets"]:
            for p in facet["vertices_local"]:
                p["x"] *= 0.4
                p["y"] /= 3
                p["z"] *= 0.5
    body = {
        "expected_inventory_revision_id": project["revision_id"],
        "target": target,
        "piece_annotations": [
            {"part_id": "deck", "display_name": "Base panel", "source": "model"}
        ],
        "joints": [
            {
                "joint_id": j["joint_id"],
                "profile_id": "synthetic-tape-profile",
                "stock_id": "synthetic-tape-stock",
                "length_mm": 20,
                "confirmed_accessible": True,
            }
            for j in target["assembly"]["joints"]
        ],
        "joint_access_user_confirmed": True,
    }
    return {**body, **changes}


def post(client, project, body=None, auth=AUTH):
    return client.post(
        f"/api/projects/{project['id']}/construction/generate",
        json=body or request(project),
        headers=auth,
    )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def no_gateway():
        raise AssertionError("Read-only construction must not call a provider")

    monkeypatch.setattr(design_runtime, "default_gateway_factory", no_gateway)
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        project = create(client)
        stocks, constraints, _, parameters, process, profiles = stand_inputs(
            project["id"]
        )
        result = client.put(
            f"/api/projects/{project['id']}/inventory",
            headers=AUTH,
            json={
                "expected_revision_id": project["revision_id"],
                "idempotency_key": "inventory-construction",
                "stocks": [s.model_dump(mode="json") for s in stocks],
                "user_confirmed": True,
                "requirements": {
                    "tools": ["Ruler", "Scissors"],
                    "constraints": constraints.model_dump(mode="json"),
                },
            },
        )
        assert result.status_code == 200, result.text
        project = result.json()["project"]
        # Test-only records exercise production validation. They are never real
        # observations, persisted progress evidence, or synthetic-mode bypasses.
        process = CutProcess.model_validate(
            {
                **process.model_dump(),
                "evidence": [
                    e.model_copy(
                        update={
                            "provenance": "user",
                            "verification_state": "user_confirmed",
                            "description": "Test-only supplied process record; no physical observation",
                        }
                    )
                    for e in process.evidence
                ],
            }
        )
        parameters = parameters.model_copy(
            update={
                "profile_evidence": tuple(
                    e.model_copy(
                        update={
                            "provenance": "user",
                            "kind": "physical_test",
                            "verification_state": "user_confirmed",
                            "description": "Test-only profile record; no physical observation",
                        }
                    )
                    for e in parameters.profile_evidence
                )
            }
        )
        context = DesignContext(
            project_id=project["id"],
            inventory_revision_id=project["revision_id"],
            process=process,
            parameters=parameters,
            joint_profiles=profiles,
            kerf_mm=2,
            edge_margin_mm=4,
        )
        monkeypatch.setattr(
            design_context,
            "default_context_resolver",
            lambda: StaticDesignContextResolver(context),
        )
        yield client, project, context, tmp_path, monkeypatch


def test_saved_materials_and_names_generate_without_mutating_any_database_record(setup):
    client, project, _, directory, _ = setup
    before = db_state(directory)
    response = post(client, project)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()
    assert data["fabrication_blockers"] == []
    assert data["fabrication_report"]["status"] == "ready", data["fabrication_report"][
        "blockers"
    ]
    assert data["fabrication_plan"]["stocks"] == project["stocks"]
    assert (
        data["fabrication_report"]["snapshot"]["inventory_revision_id"]
        == project["revision_id"]
    )
    assert all(
        o["status"] != "completed" for o in data["fabrication_report"]["operations"]
    )
    assert data["fabrication_report"]["attached_joint_ids"] == []
    base = next(
        p for p in data["construction"]["piece_catalog"] if p["part_id"] == "deck"
    )
    assert (
        base["display_name"] == "Base panel" and base["annotation"]["source"] == "model"
    )
    assert all(
        not step["analysis"]["physical_evidence_ids"]
        for step in data["construction"]["steps"]
    )
    assert post(client, project).json() == data
    assert db_state(directory) == before


def test_auth_owner_revision_and_active_plan_guards(setup):
    client, project, _, directory, _ = setup
    assert post(client, project, auth={}).status_code == 401
    assert post(client, project, auth=OTHER).status_code == 404
    assert (
        post(
            client, project, request(project, expected_inventory_revision_id="outdated")
        ).status_code
        == 409
    )
    body = request(project)
    body["target"]["snapshot"]["inventory_revision"] = "foreign"
    assert post(client, project, body).status_code == 422
    store = ProjectStore(directory)
    with store.transaction() as connection:
        saved = store.read(connection, "alice", project["id"])
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?",
            (
                saved.model_copy(
                    update={"active_version_id": "existing-build"}
                ).model_dump_json(),
                project["id"],
            ),
        )
    assert post(client, project).status_code == 409


@pytest.mark.parametrize(
    "injection",
    [
        {"stocks": []},
        {"resources": {}},
        {"profile_evidence": []},
        {"allow_synthetic": True},
        {"joint_profiles": []},
    ],
)
def test_client_cannot_supply_stock_evidence_profiles_or_synthetic_override(
    setup, injection
):
    client, project, _, _, _ = setup
    assert post(client, project, request(project, **injection)).status_code == 422


def test_missing_context_returns_explicit_blockers_and_missing_joint_access_stays_unknown(
    setup,
):
    client, project, _, _, monkeypatch = setup
    body = request(project, joint_access_user_confirmed=False)
    assert post(client, project, body).status_code == 422
    for joint in body["joints"]:
        joint["confirmed_accessible"] = None
    response = post(client, project, body)
    assert response.status_code == 200, response.text
    assert response.json()["fabrication_report"]["status"] != "ready"
    monkeypatch.setattr(
        design_context,
        "default_context_resolver",
        lambda: StaticDesignContextResolver(None),
    )
    data = post(client, project).json()
    assert data["construction"]["steps"]
    assert data["fabrication_plan"] is data["fabrication_report"] is None
    assert data["fabrication_blockers"]


def test_synthetic_server_evidence_is_not_accepted_as_production_validation(setup):
    client, project, context, _, monkeypatch = setup
    _, _, _, parameters, process, profiles = stand_inputs(project["id"])
    synthetic = context.model_copy(
        update={
            "process": process,
            "parameters": parameters,
            "joint_profiles": profiles,
        }
    )
    monkeypatch.setattr(
        design_context,
        "default_context_resolver",
        lambda: StaticDesignContextResolver(synthetic),
    )
    response = post(client, project)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["fabrication_report"]["status"] != "ready"
    assert data["fabrication_report"]["blockers"]


def test_resolver_inventory_race_rejects_stale_result(setup):
    client, project, context, directory, monkeypatch = setup
    store = ProjectStore(directory)

    def resolver(pid, revision):
        with store.transaction() as connection:
            saved = store.read(connection, "alice", pid)
            connection.execute(
                "UPDATE projects SET body=? WHERE id=?",
                (
                    saved.model_copy(
                        update={"revision_id": "new-inventory"}
                    ).model_dump_json(),
                    pid,
                ),
            )
        return StaticDesignContextResolver(context)(pid, revision)

    monkeypatch.setattr(design_context, "default_context_resolver", lambda: resolver)
    response = post(client, project)
    assert response.status_code == 409
    assert response.json()["code"] == "stale_version"


def test_saved_tool_names_do_not_invent_tool_safety_confirmation(setup):
    client, project, context, _, monkeypatch = setup
    unconfirmed = context.model_copy(
        update={
            "parameters": context.parameters.model_copy(
                update={"tools_confirmed": False}
            )
        }
    )
    monkeypatch.setattr(
        design_context,
        "default_context_resolver",
        lambda: StaticDesignContextResolver(unconfirmed),
    )
    response = post(client, project)
    assert response.status_code == 200, response.text
    report = response.json()["fabrication_report"]
    assert report["status"] != "ready"
    assert report["blockers"]


def test_unsaved_inventory_produces_no_fabrication_stock_or_operations(setup):
    client, _, _, _, _ = setup
    project = create(client, key="new-empty-project")
    response = post(client, project)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["construction"]["steps"]
    assert data["fabrication_plan"] is data["fabrication_report"] is None
    assert any("inventory" in blocker for blocker in data["fabrication_blockers"])


def test_model_target_cannot_claim_physical_work_or_foreign_project(setup):
    client, project, _, _, _ = setup
    for field, value in (
        ("basis", "observed"),
        ("completed_operation_ids", ["done-cut"]),
    ):
        body = request(project)
        body["target"]["snapshot"][field] = value
        assert post(client, project, body).status_code == 422
    body = request(project)
    body["target"]["assembly"]["project_id"] = "foreign-project"
    assert post(client, project, body).status_code == 422
