"""SYNTHETIC software checks for #148 design search; no physical attempt or pass."""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_adapt import report
from test_plans import AUTH, OTHER, TOKENS, approval, prepared

from forma_api import adapt, synthesis_runtime
from forma_api.design_context import DesignContext, StaticDesignContextResolver
from forma_api.main import create_app
from forma_api.plans import PlanVersion


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(synthesis_runtime, "ALLOW_SYNTHETIC", True)
    monkeypatch.setattr(adapt, "ALLOW_SYNTHETIC", True)
    holder = {}
    monkeypatch.setattr(
        synthesis_runtime,
        "default_context_resolver",
        lambda: StaticDesignContextResolver(holder.get("context")),
    )
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        project, _, context = prepared(client)
        holder["context"] = DesignContext(
            project_id=project["id"],
            inventory_revision_id=project["revision_id"],
            **context,
        )
        yield client, project, tmp_path, holder


def identity(project, last_event_id=None, **extra):
    return dict(
        expected_inventory_revision_id=project["revision_id"],
        expected_active_version_id=project.get("active_version_id"),
        expected_last_event_id=last_event_id,
        **extra,
    )


def post(client, project, path, body, headers=AUTH):
    return client.post(
        f"/api/projects/{project['id']}/synthesis/{path}", json=body, headers=headers
    )


def state(directory):
    """Every persisted row; searching or probing must not change any of it."""
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            table: connection.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            ).fetchall()
            for table in tables
        }


def search(client, project, **extra):
    response = post(client, project, "search", identity(project, **extra))
    assert response.status_code == 200, response.text
    return response.json()


def test_search_and_probe_are_deterministic_and_write_nothing(setup):
    client, project, directory, _ = setup
    before = state(directory)
    first, second = search(client, project), search(client, project)
    assert first == second
    assert first["status"] == "candidates_found" and len(first["candidates"]) == 2
    assert first["physical_verification"] == "not_attempted"
    base = first["candidates"][0]
    depths = next(d for d in first["domains"] if d["parameter"] == "footprint_depth_mm")
    value = depths["lower_mm"] + depths["step_mm"] * (depths["count"] - 1)
    probed = post(
        client,
        project,
        "probe",
        identity(
            project,
            search_id=first["search_id"],
            design=base["design"],
            parameter="footprint_depth_mm",
            value_mm=value,
        ),
    )
    assert probed.status_code == 200, probed.text
    result = probed.json()
    assert result["status"] == "evaluated"
    assert set(result["changed_piece_ids"]) == {"stand-base", "stand-brace"}
    assert state(directory) == before


def test_stale_and_foreign_requests_are_rejected(setup):
    client, project, _, _ = setup
    result = search(client, project)
    for override in (
        {"expected_inventory_revision_id": "inventory-old"},
        {"expected_active_version_id": "version-other"},
        {"expected_last_event_id": "event-other"},
    ):
        response = post(client, project, "search", identity(project) | override)
        assert response.status_code == 409, response.text
    assert post(client, project, "search", identity(project), OTHER).status_code == 404
    select = identity(
        project,
        search_id=result["search_id"],
        design=result["candidates"][0]["design"],
        idempotency_key="select-foreign",
        user_selected=True,
    )
    assert post(client, project, "select", select, OTHER).status_code == 404
    changed_budget = select | {"budget": {"max_nodes": 7, "max_seconds": 5}}
    stale = post(client, project, "select", changed_budget)
    assert stale.status_code == 409 and "Search inputs changed" in stale.text


def test_missing_context_needs_input_without_candidates(setup):
    client, project, _, holder = setup
    holder["context"] = None
    result = search(client, project)
    assert result["status"] == "needs_input" and not result["candidates"]
    assert result["blockers"]


def test_selection_saves_a_proposed_preview_and_approval_stays_separate(setup):
    client, project, directory, _ = setup
    result = search(client, project)
    chosen = result["candidates"][1]
    body = identity(
        project,
        search_id=result["search_id"],
        design=chosen["design"],
        idempotency_key="select-001",
        user_selected=True,
    )
    selected = post(client, project, "select", body)
    assert selected.status_code == 200, selected.text
    saved = selected.json()
    assert saved["status"] == "accepted" and not saved["replayed"]
    version = PlanVersion.model_validate(saved["version"])
    assert version.candidate_id == chosen["candidate_id"]
    parts = {p.id: p.geometry for p in version.plan.parts}
    pieces = {p["piece"]["part_id"]: p for p in chosen["pieces"]}
    for part_id, geometry in parts.items():
        assert geometry.height == pytest.approx(pieces[part_id]["height_mm"])
    current = client.get(f"/api/projects/{project['id']}", headers=AUTH).json()
    assert current["active_version_id"] is None
    replay = post(client, project, "select", body).json()
    assert replay["replayed"] and replay["version"] == saved["version"]
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 1
    activated = client.post(
        f"/api/projects/{project['id']}/plans/{version.version_id}/activate",
        headers=AUTH,
        json=approval(project),
    )
    assert activated.status_code == 200, activated.text
    project = activated.json()["project"]
    after = search(client, project)
    assert after["status"] == "active_build" and not after["candidates"]


def test_selection_rechecks_designs_on_the_server(setup):
    client, project, directory, _ = setup
    result = search(client, project)
    design = result["candidates"][0]["design"]
    supports = next(
        d for d in result["domains"] if d["parameter"] == "support_length_mm"
    )
    tallest = supports["lower_mm"] + supports["step_mm"] * (supports["count"] - 1)
    for changed, status in (
        ({"part_width_mm": design["part_width_mm"] + 1}, "blocked"),
        ({"lip_mm": 40.0}, "blocked"),
        ({"support_length_mm": tallest}, "blocked"),
    ):
        response = post(
            client,
            project,
            "select",
            identity(
                project,
                search_id=result["search_id"],
                design=design | changed,
                idempotency_key="select-" + next(iter(changed)).replace("_", "-"),
                user_selected=True,
            ),
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status, changed
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0


def test_active_build_probe_uses_repair_simulation_and_mutates_nothing(setup):
    client, project, directory, _ = setup
    result = search(client, project)
    chosen = result["candidates"][0]
    selected = post(
        client,
        project,
        "select",
        identity(
            project,
            search_id=result["search_id"],
            design=chosen["design"],
            idempotency_key="select-active",
            user_selected=True,
        ),
    ).json()
    version = PlanVersion.model_validate(selected["version"])
    project = client.post(
        f"/api/projects/{project['id']}/plans/{version.version_id}/activate",
        headers=AUTH,
        json=approval(project),
    ).json()["project"]
    plan = version.plan
    current = None
    for operation in plan.operations[:2]:  # the cut and its inspection
        current = report(client, project["id"], plan, operation.id)
    last = current["last_event_id"]
    active = search(client, project, last_event_id=last)
    assert active["status"] == "active_build"
    before = state(directory)
    depths = next(
        d for d in result["domains"] if d["parameter"] == "footprint_depth_mm"
    )
    deeper = depths["lower_mm"] + depths["step_mm"] * (depths["count"] - 1)
    probe = post(
        client,
        project,
        "probe",
        identity(
            project,
            last,
            search_id=active["search_id"],
            parameter="footprint_depth_mm",
            value_mm=deeper,
        ),
    )
    assert probe.status_code == 200, probe.text
    body = probe.json()
    assert body["status"] == "requires_repair"
    assert body["repair"]["target_part_id"] == "stand-base"
    assert body["report"] is None
    # The cut is completed: the existing replanner refuses rather than resizing.
    assert body["repair"]["status"] == "blocked"
    assert any(
        "completed cuts cannot be resized" in b["message"]
        for b in body["repair"]["blockers"]
    )
    width = post(
        client,
        project,
        "probe",
        identity(
            project,
            last,
            search_id=active["search_id"],
            parameter="part_width_mm",
            value_mm=chosen["design"]["part_width_mm"],
        ),
    ).json()
    assert width["status"] == "unsupported" and width["blockers"]
    assert state(directory) == before
    current_project = client.get(f"/api/projects/{project['id']}", headers=AUTH).json()
    assert current_project["active_version_id"] == version.version_id
