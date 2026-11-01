"""Synthetic software integration checks; no physical attempt or pass."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from forma_compiler import CutProcess
from forma_renderer import StandParameters

from forma_api.main import create_app
from forma_api.plans import CompilePreview, PlanService
from forma_api.projects import ProjectError, ProjectStore
from forma_domain import models as m

TOKENS = {"alice": "a" * 40, "bob": "b" * 40}
AUTH = {"Authorization": "Bearer " + TOKENS["alice"]}
OTHER = {"Authorization": "Bearer " + TOKENS["bob"]}


def measured(value, unit="mm"):
    return m.Measurement(value=value, unit=unit, source="calculated", confirmed=True)


def stand_inputs(project_id):
    now = datetime(2026, 11, 1, tzinfo=UTC)
    unknown = m.Measurement(value=None, unit="mm", source="unknown", confirmed=False)
    evidence = tuple(
        m.Evidence(
            id=name,
            project_id=project_id,
            version_id="synthetic-v1",
            kind="measurement",
            provenance="synthetic_fixture",
            recorded_at=now,
            description="SYNTHETIC software fixture only; no physical test",
            verification_state="unknown",
        )
        for name in ("synthetic-process", "synthetic-tape", "synthetic-fold")
    )
    stocks = (
        m.Stock(
            id="synthetic-sheet",
            kind="sheet",
            material="cardboard",
            condition="usable",
            width_mm=measured(200),
            height_mm=measured(550),
            thickness_mm=measured(2),
            remaining_length_mm=unknown,
            usable_regions=(
                m.Region(
                    id="synthetic-region",
                    geometry=m.Rect(x=0, y=0, width=200, height=550),
                ),
            ),
        ),
        m.Stock(
            id="synthetic-tape-stock",
            kind="tape",
            material="other_supported",
            condition="usable",
            width_mm=measured(30),
            height_mm=unknown,
            thickness_mm=unknown,
            remaining_length_mm=measured(500),
        ),
    )
    profiles = tuple(
        m.JointProfile(
            id=f"synthetic-{name}-profile",
            strategy=strategy,
            status="tested",
            material="cardboard",
            thickness_min_mm=1,
            thickness_max_mm=3,
            tolerated_error_mm=1,
            test_evidence_ids=(f"synthetic-{name}",),
            limitations=("SYNTHETIC only",),
        )
        for name, strategy in (("tape", "tape"), ("fold", "fold_brace"))
    )
    constraints = m.Constraints(
        device_mass_g=measured(180, "g"),
        support_angle_deg=measured(60, "deg"),
        max_footprint_width_mm=measured(120),
        max_footprint_height_mm=measured(180),
    )
    candidate = m.DesignCandidate(
        id="synthetic-candidate",
        family="tabletop_fixture_v1",
        support_angle_deg=60,
        part_width_mm=80,
        part_height_mm=150,
        panel_count=3,
        stock_ids=tuple(stock.id for stock in stocks),
        profile_ids=tuple(profile.id for profile in profiles),
        assumptions=("SYNTHETIC software fixture only",),
    )
    parameters = StandParameters(
        footprint_depth_mm=measured(140),
        lip_mm=measured(15),
        device_width_mm=measured(70),
        device_thickness_mm=measured(8),
        device_contact_height_mm=measured(100),
        tape_overlap_mm=measured(10),
        tools_confirmed=True,
        joint_access_confirmed=True,
        device_label="SYNTHETIC phone",
        test_duration_seconds=60,
        test_surface="SYNTHETIC desk",
        test_pass_criteria=("No slip or tip",),
        profile_evidence=evidence[1:],
    )
    process = CutProcess(kerf_min_mm=2, edge_margin_min_mm=4, evidence=evidence[:1])
    return stocks, constraints, candidate, parameters, process, profiles


def prepared(client):
    project = client.post(
        "/api/projects",
        json={"goal": "SYNTHETIC stand", "idempotency_key": "create-001"},
        headers=AUTH,
    ).json()["project"]
    stocks, constraints, candidate, parameters, process, profiles = stand_inputs(
        project["id"]
    )
    project = client.put(
        "/api/projects/" + project["id"] + "/inventory",
        headers=AUTH,
        json={
            "expected_revision_id": project["revision_id"],
            "idempotency_key": "inventory-001",
            "stocks": [stock.model_dump(mode="json") for stock in stocks],
            "user_confirmed": True,
            "requirements": {
                "tools": ["Synthetic ruler"],
                "constraints": constraints.model_dump(mode="json"),
            },
        },
    ).json()["project"]
    body = CompilePreview(
        expected_revision_id=project["revision_id"],
        idempotency_key="preview-001",
        candidate=candidate,
    )
    context = dict(
        parameters=parameters,
        process=process,
        joint_profiles=profiles,
        kerf_mm=2,
        edge_margin_mm=4,
    )
    return project, body, context


@pytest.fixture
def setup(tmp_path):
    store = ProjectStore(tmp_path)
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        project, body, context = prepared(client)
        yield client, project, body, context, PlanService(store, allow_synthetic=True)


def compile_one(setup):
    client, project, body, context, service = setup
    result = service.compile_preview("alice", project["id"], body, **context)
    assert result.status == "accepted", result.model_dump()
    return result.version


def approval(project, key="activate-001"):
    return dict(
        expected_revision_id=project["revision_id"],
        idempotency_key=key,
        user_approved=True,
    )


def test_compile_read_activate_and_restart_keep_original_bytes(setup, tmp_path):
    client, project, body, context, service = setup
    version = compile_one(setup)
    base = "/api/projects/" + project["id"]
    manual = client.get(base + "/manual/" + version.version_id, headers=AUTH)
    assert manual.status_code == 200
    assert manual.headers["Cache-Control"] == "no-store"
    assert len(manual.json()["panels"]) == 8
    assert all(
        "SYNTHETIC" in panel["svg"] and panel["instruction"]
        for panel in manual.json()["panels"]
    )
    assert manual.json()["physical_verification"] == "not_attempted"
    assert client.get(base, headers=AUTH).json()["active_version_id"] is None
    activation = client.post(
        base + "/plans/" + version.version_id + "/activate",
        headers=AUTH,
        json=approval(project),
    )
    assert activation.status_code == 200, activation.text
    assert activation.json()["project"]["active_version_id"] == version.version_id
    assert activation.json()["project"]["stocks"] == project["stocks"]
    assert (
        client.get(base + "/manual/" + version.version_id, headers=AUTH).content
        == manual.content
    )
    assert client.get(
        base + "/versions/" + version.version_id, headers=AUTH
    ).json() == version.model_dump(mode="json")
    with TestClient(create_app(tmp_path, TOKENS)) as restarted:
        assert (
            restarted.get(base + "/manual/" + version.version_id, headers=AUTH).content
            == manual.content
        )
        assert (
            restarted.get(base, headers=AUTH).json()["active_version_id"]
            == version.version_id
        )
    with service.store.transaction() as connection:
        row = connection.execute("SELECT process,parameters FROM plans").fetchone()
    assert json.loads(row[0]) == context["process"].model_dump(mode="json")
    assert json.loads(row[1]) == context["parameters"].model_dump(mode="json")


def test_scope_unknown_versions_and_no_http_compile_injection(setup):
    client, project, body, context, service = setup
    version = compile_one(setup)
    base = "/api/projects/" + project["id"]
    for suffix in (
        "/plans",
        "/versions/" + version.version_id,
        "/manual/" + version.version_id,
    ):
        assert client.get(base + suffix, headers=OTHER).status_code == 404
        assert client.get(base + suffix).status_code == 401
    assert client.get(base + "/versions/missing", headers=AUTH).status_code == 404
    other = client.post(
        "/api/projects",
        json={"goal": "Other", "idempotency_key": "create-002"},
        headers=AUTH,
    ).json()["project"]
    assert (
        client.get(
            "/api/projects/" + other["id"] + "/manual/" + version.version_id,
            headers=AUTH,
        ).status_code
        == 404
    )
    assert (
        client.post(
            base + "/compile", headers=AUTH, json=version.plan.model_dump(mode="json")
        ).status_code
        == 404
    )
    assert (
        client.post(
            base + "/plans/" + version.version_id + "/activate",
            headers=OTHER,
            json=approval(project),
        ).status_code
        == 404
    )
    with pytest.raises(ProjectError) as error:
        service.compile_preview("bob", project["id"], body, **context)
    assert error.value.status == 404


def test_compile_retries_caps_and_changed_key_payload(setup):
    client, project, body, context, service = setup
    version = compile_one(setup)
    retry = service.compile_preview("alice", project["id"], body, **context)
    assert retry.replayed is True
    assert retry.version == version
    second = body.model_copy(update={"idempotency_key": "preview-002"})
    assert (
        service.compile_preview("alice", project["id"], second, **context).status
        == "accepted"
    )
    with pytest.raises(ProjectError) as error:
        service.compile_preview(
            "alice",
            project["id"],
            body.model_copy(
                update={
                    "candidate": body.candidate.model_copy(update={"id": "different"})
                }
            ),
            **context,
        )
    assert error.value.envelope.code == "idempotency_conflict"
    with pytest.raises(ProjectError) as error:
        service.compile_preview(
            "alice",
            project["id"],
            body.model_copy(update={"idempotency_key": "preview-003"}),
            **context,
        )
    assert error.value.envelope.code == "blocked"
    assert (
        len(
            client.get(
                "/api/projects/" + project["id"] + "/plans", headers=AUTH
            ).json()["plans"]
        )
        == 2
    )


def test_activation_retries_conflicts_and_explicit_approval(setup):
    client, project, body, context, service = setup
    version = compile_one(setup)
    path = (
        "/api/projects/" + project["id"] + "/plans/" + version.version_id + "/activate"
    )
    first = client.post(path, headers=AUTH, json=approval(project))
    assert first.status_code == 200
    assert client.post(path, headers=AUTH, json=approval(project)).json() == {
        **first.json(),
        "replayed": True,
    }
    assert (
        client.post(
            path, headers=AUTH, json=approval(project, "activate-002")
        ).status_code
        == 409
    )
    changed = {**approval(project), "expected_revision_id": "different"}
    assert (
        client.post(path, headers=AUTH, json=changed).json()["code"]
        == "idempotency_conflict"
    )
    assert (
        client.post(
            path,
            headers=AUTH,
            json={**approval(project, "activate-003"), "user_approved": False},
        ).status_code
        == 422
    )
    assert (
        client.post(
            path,
            headers=AUTH,
            json={
                **approval(project, "activate-004"),
                "plan": version.plan.model_dump(mode="json"),
            },
        ).status_code
        == 422
    )


def test_stale_preview_cannot_activate_and_compiler_rechecks_snapshot(
    setup, monkeypatch
):
    import forma_api.plans as plans

    client, project, body, context, service = setup
    version = compile_one(setup)
    base = "/api/projects/" + project["id"]

    def change_inventory():
        return client.put(
            base + "/inventory",
            headers=AUTH,
            json={
                "expected_revision_id": project["revision_id"],
                "idempotency_key": "inventory-002",
                "stocks": project["stocks"],
                "user_confirmed": True,
            },
        )

    original = plans.compile_stand

    def interleaved(*args, **kwargs):
        assert change_inventory().status_code == 200
        return original(*args, **kwargs)

    monkeypatch.setattr(plans, "compile_stand", interleaved)
    with pytest.raises(ProjectError) as error:
        service.compile_preview(
            "alice",
            project["id"],
            body.model_copy(update={"idempotency_key": "preview-002"}),
            **context,
        )
    assert error.value.envelope.code == "stale_version"
    assert (
        client.post(
            base + "/plans/" + version.version_id + "/activate",
            headers=AUTH,
            json=approval(project),
        ).status_code
        == 409
    )
    assert client.get(base, headers=AUTH).json()["active_version_id"] is None
    assert len(client.get(base + "/plans", headers=AUTH).json()["plans"]) == 1


def test_competing_activations_have_one_winner(setup):
    client, project, body, context, service = setup
    first = compile_one(setup)
    second = service.compile_preview(
        "alice",
        project["id"],
        body.model_copy(update={"idempotency_key": "preview-002"}),
        **context,
    ).version

    def activate(item):
        version, key = item
        return client.post(
            "/api/projects/"
            + project["id"]
            + "/plans/"
            + version.version_id
            + "/activate",
            headers=AUTH,
            json=approval(project, key),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(
            pool.map(activate, [(first, "activate-001"), (second, "activate-002")])
        ) == [200, 409]


def test_rollback_and_project_deletion_purge_plan_snapshots(
    setup, monkeypatch, tmp_path
):
    client, project, body, context, service = setup
    original = ProjectStore.remember

    def fail(*args):
        raise sqlite3.OperationalError("synthetic receipt failure")

    monkeypatch.setattr(ProjectStore, "remember", staticmethod(fail))
    with pytest.raises(sqlite3.OperationalError):
        service.compile_preview("alice", project["id"], body, **context)
    base = "/api/projects/" + project["id"]
    assert client.get(base + "/plans", headers=AUTH).json()["plans"] == []
    monkeypatch.setattr(ProjectStore, "remember", staticmethod(original))
    version = compile_one(setup)
    monkeypatch.setattr(ProjectStore, "remember", staticmethod(fail))
    with pytest.raises(sqlite3.OperationalError):
        client.post(
            base + "/plans/" + version.version_id + "/activate",
            headers=AUTH,
            json=approval(project),
        )
    assert client.get(base, headers=AUTH).json()["active_version_id"] is None
    monkeypatch.setattr(ProjectStore, "remember", staticmethod(original))
    assert (
        client.post(
            base + "/plans/" + version.version_id + "/activate",
            headers=AUTH,
            json=approval(project),
        ).status_code
        == 200
    )
    assert (
        client.delete(
            base, headers={**AUTH, "Idempotency-Key": "delete-001"}
        ).status_code
        == 200
    )
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0
        receipts = connection.execute("SELECT response FROM requests").fetchall()
    assert all("SYNTHETIC" not in row[0] and "<svg" not in row[0] for row in receipts)
    assert (
        client.get(base + "/manual/" + version.version_id, headers=AUTH).status_code
        == 404
    )
    with pytest.raises(ProjectError):
        service.compile_preview("alice", project["id"], body, **context)


def test_default_rejects_synthetic_context_and_missing_inputs(setup):
    client, project, body, context, service = setup
    default = PlanService(service.store)
    result = default.compile_preview("alice", project["id"], body, **context)
    assert result.status == "blocked"
    assert result.version is None
    assert result.blockers[0].code == "unsupported_profile"
    missing = default.compile_preview(
        "alice",
        project["id"],
        body,
        process=None,
        parameters=None,
        joint_profiles=(),
        kerf_mm=None,
        edge_margin_mm=None,
    )
    assert missing.status == "needs_measurement"
    assert len(missing.blockers) == 5
    assert (
        client.get("/api/projects/" + project["id"] + "/plans", headers=AUTH).json()[
            "plans"
        ]
        == []
    )


def test_real_compiler_blocks_oversized_candidate_without_saving(setup):
    client, project, body, context, service = setup
    oversized = body.model_copy(
        update={"candidate": body.candidate.model_copy(update={"part_width_mm": 999})}
    )
    result = service.compile_preview("alice", project["id"], oversized, **context)
    assert result.status == "blocked"
    assert result.version is None
    assert result.blockers
    assert (
        client.get("/api/projects/" + project["id"] + "/plans", headers=AUTH).json()[
            "plans"
        ]
        == []
    )


def test_concurrent_compile_retries_save_one_version(setup):
    client, project, body, context, service = setup

    def compile_once(_):
        return service.compile_preview("alice", project["id"], body, **context)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compile_once, range(2)))
    assert results[0].version == results[1].version
    assert sorted(result.replayed for result in results) == [False, True]
    assert (
        len(
            client.get(
                "/api/projects/" + project["id"] + "/plans", headers=AUTH
            ).json()["plans"]
        )
        == 1
    )


def test_empty_project_and_active_project_do_not_gain_previews(setup):
    client, project, body, context, service = setup
    other = client.post(
        "/api/projects",
        headers=AUTH,
        json={"goal": "Empty", "idempotency_key": "create-002"},
    ).json()["project"]
    result = service.compile_preview(
        "alice",
        other["id"],
        body.model_copy(update={"expected_revision_id": other["revision_id"]}),
        process=None,
        parameters=None,
        joint_profiles=(),
        kerf_mm=None,
        edge_margin_mm=None,
    )
    assert result.status == "needs_measurement"
    assert len(result.blockers) == 7
    version = compile_one(setup)
    base = "/api/projects/" + project["id"]
    assert (
        client.post(
            base + "/plans/" + version.version_id + "/activate",
            headers=AUTH,
            json=approval(project),
        ).status_code
        == 200
    )
    with pytest.raises(ProjectError) as error:
        service.compile_preview(
            "alice",
            project["id"],
            body.model_copy(update={"idempotency_key": "preview-002"}),
            **context,
        )
    assert error.value.envelope.code == "blocked"


@pytest.mark.parametrize("field", ["kerf_mm", "edge_margin_mm"])
@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf"), True, False])
def test_selected_cut_settings_reject_invalid_values(setup, field, invalid):
    client, project, body, context, service = setup
    result = service.compile_preview(
        "alice", project["id"], body, **{**context, field: invalid}
    )
    assert result.status == "blocked"
    assert result.version is None
    assert [blocker.code for blocker in result.blockers] == ["invalid_reference"]
    assert (
        client.get("/api/projects/" + project["id"] + "/plans", headers=AUTH).json()[
            "plans"
        ]
        == []
    )


@pytest.mark.parametrize("field", ["kerf_mm", "edge_margin_mm"])
def test_selected_cut_settings_remain_unknown_when_missing(setup, field):
    client, project, body, context, service = setup
    result = service.compile_preview(
        "alice", project["id"], body, **{**context, field: None}
    )
    assert result.status == "needs_measurement"
    assert len(result.blockers) == 1
    assert result.blockers[0].code == "missing_measurement"
    assert result.version is None


def test_selected_cut_settings_above_process_minimum_remain_in_plan(setup):
    client, project, body, context, service = setup
    result = service.compile_preview(
        "alice", project["id"], body, **{**context, "kerf_mm": 3, "edge_margin_mm": 5}
    )
    assert result.status == "accepted", result.model_dump()
    cuts = [
        operation
        for operation in result.version.plan.operations
        if operation.type == "cut_rect"
    ]
    assert cuts
    assert all(
        operation.args.kerf_mm == 3 and operation.args.edge_margin_mm == 5
        for operation in cuts
    )


@pytest.mark.parametrize(
    "changed", ["cut_settings", "parameters", "process", "profiles"]
)
def test_compile_retry_fingerprints_complete_trusted_context(setup, changed):
    client, project, body, context, service = setup
    version = compile_one(setup)
    altered = dict(context)
    if changed == "cut_settings":
        altered.update(kerf_mm=3, edge_margin_mm=5)
    elif changed == "parameters":
        altered["parameters"] = context["parameters"].model_copy(
            update={"lip_mm": measured(16)}
        )
    elif changed == "process":
        altered["process"] = context["process"].model_copy(update={"kerf_min_mm": 3})
    else:
        altered["joint_profiles"] = (
            context["joint_profiles"][0].model_copy(
                update={"limitations": ("Different synthetic limit",)}
            ),
            context["joint_profiles"][1],
        )
    with pytest.raises(ProjectError) as error:
        service.compile_preview("alice", project["id"], body, **altered)
    assert error.value.envelope.code == "idempotency_conflict"
    exact_retry = service.compile_preview("alice", project["id"], body, **context)
    assert exact_retry.replayed is True
    assert exact_retry.version == version
    base = "/api/projects/" + project["id"]
    assert client.get(
        base + "/versions/" + version.version_id, headers=AUTH
    ).json() == version.model_dump(mode="json")
    assert len(client.get(base + "/plans", headers=AUTH).json()["plans"]) == 1
