"""Synthetic repair previews and approvals; no real physical attempt or pass."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_plans import AUTH, OTHER, TOKENS, approval, prepared

from forma_api import adapt
from forma_api.main import create_app
from forma_api.plans import PlanService
from forma_api.projects import ProjectStore
from forma_domain import models as m

SYNTHETIC = "SYNTHETIC software action; no actual physical result"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(adapt, "ALLOW_SYNTHETIC", True)
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        project, body, context = prepared(client)
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
        # The spare stays unallocated inventory in the plan, ready for repair.
        body = body.model_copy(update={"expected_revision_id": project["revision_id"]})
        compiled = PlanService(
            ProjectStore(tmp_path), allow_synthetic=True
        ).compile_preview("alice", project["id"], body, **context)
        assert compiled.status == "accepted", compiled.blockers
        version = compiled.version
        activated = client.post(
            f"/api/projects/{project['id']}/plans/{version.version_id}/activate",
            headers=AUTH,
            json=approval(project),
        )
        assert activated.status_code == 200, activated.text
        yield client, version, tmp_path


def progress(client, project_id, version_id):
    response = client.get(
        f"/api/projects/{project_id}/versions/{version_id}/progress", headers=AUTH
    )
    assert response.status_code == 200, response.text
    return response.json()


def report(client, project_id, plan, operation_id, result=None, key=None):
    current = progress(client, project_id, plan.version_id)
    operation = next(op for op in plan.operations if op.id == operation_id)
    response = client.post(
        f"/api/projects/{project_id}/events",
        headers=AUTH,
        json=dict(
            expected_version_id=plan.version_id,
            expected_last_event_id=current["last_event_id"],
            idempotency_key=key or f"report-{operation_id}",
            operation_id=operation_id,
            result=result
            or (
                "passed"
                if operation.type in {"inspect", "functional_test"}
                else "completed"
            ),
            observation=SYNTHETIC,
            user_confirmed=True,
            checks_confirmed=True,
            photo_ids=[],
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()["progress"]


def patch(plan, patch_id="replace-brace", **overrides):
    values = dict(
        id=patch_id,
        base_version_id=plan.version_id,
        kind="replace_part",
        target_id="stand-brace",
        replacement_stock_id="synthetic-spare",
        replacement_profile_id=None,
        width_mm=None,
        height_mm=None,
        angle_deg=None,
        rationale="SYNTHETIC replacement of a damaged brace from the spare sheet.",
    )
    values.update(overrides)
    return values


def simulate(client, plan, current, candidates, key="simulate-001", tape=260):
    return client.post(
        f"/api/projects/{plan.project_id}/adapt/simulate",
        headers=AUTH,
        json=dict(
            expected_version_id=plan.version_id,
            expected_last_event_id=current["last_event_id"],
            idempotency_key=key,
            candidates=candidates,
            connector_measurements=[]
            if tape is None
            else [{"stock_id": "synthetic-tape-stock", "remaining_length_mm": tape}],
            remaining_confirmed=True,
        ),
    )


def commit(client, plan, current, preview_id, key="commit-001", headers=AUTH):
    return client.post(
        f"/api/projects/{plan.project_id}/adapt/commit",
        headers=headers,
        json=dict(
            expected_version_id=plan.version_id,
            expected_last_event_id=current["last_event_id"],
            preview_id=preview_id,
            idempotency_key=key,
            user_approved=True,
        ),
    )


def joined(client, version):
    plan = version.plan
    for operation in plan.operations[:6]:
        current = report(client, plan.project_id, plan, operation.id)
    return current


def active(client, project_id):
    return client.get(f"/api/projects/{project_id}", headers=AUTH).json()[
        "active_version_id"
    ]


def test_attached_brace_repair_previews_then_activates_atomically(setup):
    client, version, directory = setup
    plan = version.plan
    current = joined(client, version)
    response = simulate(client, plan, current, [patch(plan)])
    assert response.status_code == 200, response.text
    preview = response.json()["previews"][0]
    simulation = preview["simulation"]
    assert preview["rank"] == 1 and simulation["status"] == "feasible"
    assert len(simulation["required_undo_operation_ids"]) == 2
    assert simulation["lost_part_ids"] == ["stand-brace"]
    assert set(simulation["lost_operation_ids"]) == {
        "stand-joint-rear-attach",
        "stand-joint-apex-attach",
    }
    assert "stand-inspect-fit-check" in simulation["invalidated_checkpoint_ids"]
    assert simulation["cost"]["complete_estimate"] is False
    diff = preview["panel_diff"]
    assert diff["unchanged"] == [0, 1, 2, 3, 4, 5]
    assert diff["added"] and diff["changed"]
    assert preview["version"]["manual"]["physical_verification"] == "not_attempted"
    # A preview changes no active state or history.
    assert active(client, plan.project_id) == plan.version_id
    assert progress(client, plan.project_id, plan.version_id) == current

    approved = commit(client, plan, current, preview["preview_id"])
    assert approved.status_code == 200, approved.text
    revision = approved.json()["revision"]
    new_id = revision["version_id"]
    assert approved.json()["project"]["active_version_id"] == new_id
    assert active(client, plan.project_id) == new_id
    assert revision["carried_completed_operation_ids"] == [
        op.id for op in plan.operations[:6]
    ]
    retry = commit(client, plan, current, preview["preview_id"])
    assert retry.status_code == 200 and retry.json()["replayed"] is True

    after = progress(client, plan.project_id, new_id)
    assert after["status"] == "building"
    assert after["carried_operation_ids"] == revision["carried_completed_operation_ids"]
    assert after["events"] == [] and after["last_event_id"] is None
    tape = next(
        s
        for s in after["expected_remaining_stock"]
        if s["id"] == "synthetic-tape-stock"
    )
    assert tape["remaining_length_mm"]["value"] == 260
    # The original version and its history stay readable and unchanged.
    assert progress(client, plan.project_id, plan.version_id) == current
    new_plan = m.BuildPlan.model_validate(preview["version"]["plan"])
    peel = simulation["required_undo_operation_ids"][0]
    report(client, plan.project_id, new_plan, peel)
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM plan_revisions").fetchone() == (
            1,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM plans WHERE version_id=?", (new_id,)
        ).fetchone() == (1,)


def test_preview_before_joins_preserves_only_the_cut(setup):
    client, version, _ = setup
    plan = version.plan
    current = report(client, plan.project_id, plan, "stand-cut-panels")
    response = simulate(client, plan, current, [patch(plan)], tape=None)
    assert response.status_code == 200, response.text
    simulation = response.json()["previews"][0]["simulation"]
    assert simulation["status"] == "feasible"
    assert simulation["preserved_operation_ids"] == ["stand-cut-panels"]
    assert simulation["required_undo_operation_ids"] == []


def test_stale_history_and_active_version_return_409(setup):
    client, version, _ = setup
    plan = version.plan
    current = report(client, plan.project_id, plan, "stand-cut-panels")
    preview = simulate(client, plan, current, [patch(plan)], tape=None).json()[
        "previews"
    ][0]
    newer = report(client, plan.project_id, plan, "stand-inspect-cuts")
    stale = commit(client, plan, current, preview["preview_id"])
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_version")
    # Even with the current cursor, a preview simulated on older history is stale.
    drifted = commit(client, plan, newer, preview["preview_id"], key="commit-002")
    assert (drifted.status_code, drifted.json()["code"]) == (409, "stale_version")
    assert active(client, plan.project_id) == plan.version_id
    old_cursor = simulate(client, plan, current, [patch(plan)], "simulate-2", None)
    assert old_cursor.status_code == 409


def test_concurrent_approvals_activate_one_revision(setup):
    client, version, directory = setup
    plan = version.plan
    current = report(client, plan.project_id, plan, "stand-cut-panels")
    previews = simulate(
        client,
        plan,
        current,
        [patch(plan), patch(plan, "replace-brace-2", rationale="SYNTHETIC second")],
        tape=None,
    ).json()["previews"]
    assert [p["rank"] for p in previews] == [1, 2]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda item: commit(
                    client, plan, current, item[1]["preview_id"], f"commit-{item[0]}"
                ),
                enumerate(previews),
            )
        )
    assert sorted(r.status_code for r in responses) == [200, 409]
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM plan_revisions").fetchone() == (
            1,
        )


def test_connector_measurement_is_required_and_mismatch_blocks(setup):
    client, version, _ = setup
    plan = version.plan
    current = joined(client, version)
    missing = simulate(client, plan, current, [patch(plan)], tape=None)
    assert (missing.status_code, missing.json()["code"]) == (422, "validation_error")
    short = simulate(client, plan, current, [patch(plan)], "simulate-short", 200)
    assert short.status_code == 200, short.text
    preview = short.json()["previews"][0]
    assert preview["simulation"]["status"] == "blocked"
    assert preview["rank"] is None and preview["version"] is None
    assert any(
        b["code"] == "stock_exhausted" for b in preview["simulation"]["blockers"]
    )
    refused = commit(client, plan, current, preview["preview_id"])
    assert (refused.status_code, refused.json()["code"]) == (409, "blocked")
    assert active(client, plan.project_id) == plan.version_id


def test_blocked_candidates_rank_after_feasible_and_unknown_measurements_reject(
    setup,
):
    client, version, _ = setup
    plan = version.plan
    current = report(client, plan.project_id, plan, "stand-cut-panels")
    response = simulate(
        client,
        plan,
        current,
        [
            patch(plan, "missing-stock", replacement_stock_id="not-in-plan"),
            patch(plan),
        ],
        tape=None,
    )
    previews = response.json()["previews"]
    assert [p["patch"]["id"] for p in previews] == ["replace-brace", "missing-stock"]
    assert previews[1]["simulation"]["status"] == "blocked"
    extra = simulate(client, plan, current, [patch(plan)], "simulate-extra", 100)
    assert (extra.status_code, extra.json()["code"]) == (422, "validation_error")


def test_other_owner_and_unknown_preview_are_not_found(setup):
    client, version, _ = setup
    plan = version.plan
    current = report(client, plan.project_id, plan, "stand-cut-panels")
    preview = simulate(client, plan, current, [patch(plan)], tape=None).json()[
        "previews"
    ][0]
    foreign = commit(client, plan, current, preview["preview_id"], headers=OTHER)
    assert foreign.status_code == 404
    unknown = commit(client, plan, current, "preview-unknown", key="commit-unknown")
    assert unknown.status_code == 404


def test_project_deletion_purges_previews_and_revisions(setup):
    client, version, directory = setup
    plan = version.plan
    current = report(client, plan.project_id, plan, "stand-cut-panels")
    preview = simulate(client, plan, current, [patch(plan)], tape=None).json()[
        "previews"
    ][0]
    assert commit(client, plan, current, preview["preview_id"]).status_code == 200
    deleted = client.delete(
        f"/api/projects/{plan.project_id}",
        headers={**AUTH, "Idempotency-Key": "delete-001"},
    )
    assert deleted.status_code == 200, deleted.text
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        for table in ("adapt_previews", "plan_revisions", "evidence_invalidations"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (
                0,
            )
        assert connection.execute(
            "SELECT COUNT(*) FROM requests WHERE scope LIKE ?",
            (plan.project_id + ":adapt-%",),
        ).fetchone() == (0,)


def test_failed_fit_check_is_resolved_only_by_an_approved_revision(setup):
    client, version, directory = setup
    plan = version.plan
    joined(client, version)
    failed = report(client, plan.project_id, plan, "stand-inspect-fit", "failed")
    assert failed["status"] == "needs_review"
    response = simulate(client, plan, failed, [patch(plan)])
    assert response.status_code == 200, response.text
    preview = response.json()["previews"][0]
    simulation = preview["simulation"]
    assert simulation["status"] == "feasible", simulation["blockers"]
    failed_evidence = {e["id"] for e in failed["evidence"]}
    assert failed_evidence & set(simulation["invalidated_evidence_ids"])
    approved = commit(client, plan, failed, preview["preview_id"])
    assert approved.status_code == 200, approved.text
    invalidated = {i["evidence_id"] for i in approved.json()["invalidations"]}
    assert invalidated == set(simulation["invalidated_evidence_ids"])
    new_id = approved.json()["revision"]["version_id"]
    after = progress(client, plan.project_id, new_id)
    assert after["failed_operation_ids"] == []
    assert after["status"] == "building"
    # The failure stays true for the original version.
    assert progress(client, plan.project_id, plan.version_id) == failed
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        rows = connection.execute(
            "SELECT evidence_id FROM evidence_invalidations"
        ).fetchall()
    assert {row[0] for row in rows} == invalidated


def report_damage(client, plan, current, part_id="stand-brace", *, part_ids=None):
    response = client.post(
        f"/api/projects/{plan.project_id}/damage",
        headers=AUTH,
        json=dict(
            expected_version_id=plan.version_id,
            expected_last_event_id=current["last_event_id"],
            idempotency_key="damage-brace",
            operation_id="stand-joint-apex-attach",
            part_ids=part_ids if part_ids is not None else [part_id],
            observation=SYNTHETIC,
            user_confirmed=True,
            photo_ids=[],
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()["progress"]


def test_reported_damage_leads_to_a_replacement_revision(setup):
    client, version, _ = setup
    plan = version.plan
    damaged = report_damage(client, plan, joined(client, version))
    assert damaged["status"] == "needs_review"
    assert damaged["damaged_part_ids"] == ["stand-brace"]
    response = simulate(client, plan, damaged, [patch(plan)])
    assert response.status_code == 200, response.text
    preview = response.json()["previews"][0]
    assert preview["simulation"]["status"] == "feasible", preview["simulation"]
    assert preview["simulation"]["lost_part_ids"] == ["stand-brace"]
    approved = commit(client, plan, damaged, preview["preview_id"])
    assert approved.status_code == 200, approved.text
    revised = approved.json()["project"]["active_version_id"]
    assert revised != plan.version_id
    # The damage stays in the original version's history; the revision starts clean.
    assert progress(client, plan.project_id, plan.version_id) == damaged
    fresh = progress(client, plan.project_id, revised)
    assert fresh["damaged_part_ids"] == [] and fresh["status"] != "needs_review"


def test_reported_damage_blocks_repairs_that_keep_the_damaged_part(setup):
    client, version, _ = setup
    plan = version.plan
    damaged = report_damage(client, plan, joined(client, version))
    resize = patch(
        plan,
        "resize-base",
        kind="resize_part",
        target_id="stand-base",
        replacement_stock_id=None,
        width_mm=80,
        height_mm=160,
        rationale="SYNTHETIC base extension that keeps the damaged brace.",
    )
    response = simulate(client, plan, damaged, [resize])
    assert response.status_code == 200, response.text
    simulation = response.json()["previews"][0]["simulation"]
    assert simulation["status"] == "blocked"
    assert {
        (b["code"], b["message"])
        for b in simulation["blockers"]
        if damaged["events"][-1]["id"] in b["target_ids"]
    } == {
        (
            "needs_confirmation",
            "Damage requires a confirmed scoped replacement or explicit physical repair plan.",
        )
    }


def report_material(client, plan, current, key, **fields):
    return client.post(
        f"/api/projects/{plan.project_id}/materials",
        headers=AUTH,
        json=dict(
            expected_version_id=plan.version_id,
            expected_last_event_id=current["last_event_id"],
            idempotency_key=key,
            observation=SYNTHETIC,
            user_confirmed=True,
            photo_ids=[],
        )
        | fields,
    )


def stock(snapshot, stock_id):
    return next(s for s in snapshot["expected_remaining_stock"] if s["id"] == stock_id)


def test_wasted_spare_cannot_supply_a_repair_until_salvaged(setup):
    client, version, _ = setup
    plan = version.plan
    current = joined(client, version)
    spare = dict(operation_id="stand-cut-panels", stock_id="synthetic-spare")
    response = report_material(
        client,
        plan,
        current,
        "waste-spare",
        kind="waste",
        region_id="synthetic-spare-region",
        **spare,
    )
    assert response.status_code == 200, response.text
    wasted = response.json()["progress"]
    assert stock(wasted, "synthetic-spare")["usable_regions"] == []
    assert wasted["status"] == current["status"]
    assert wasted["completed_operation_ids"] == current["completed_operation_ids"]
    receipt = wasted["material_transactions"][-1]
    assert (receipt["kind"], receipt["unit"], receipt["source_region_id"]) == (
        "waste",
        "mm2",
        "synthetic-spare-region",
    )
    assert (wasted["events"][-1]["kind"], wasted["evidence"][-1]["kind"]) == (
        "measurement",
        "measurement",
    )
    blocked = simulate(client, plan, wasted, [patch(plan)], key="simulate-wasted")
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["previews"][0]["simulation"]["blockers"] == [
        {
            "code": "stock_exhausted",
            "message": "No actual remaining region fits the replacement brace and measured margins.",
            "target_ids": ["synthetic-spare"],
        }
    ]

    response = report_material(
        client,
        plan,
        wasted,
        "salvage-spare",
        kind="salvage",
        region_id="synthetic-spare-region",
        **spare,
    )
    assert response.status_code == 200, response.text
    salvaged = response.json()["progress"]
    assert stock(salvaged, "synthetic-spare") == stock(current, "synthetic-spare")
    feasible = simulate(client, plan, salvaged, [patch(plan)], key="simulate-salvaged")
    assert feasible.status_code == 200, feasible.text
    assert feasible.json()["previews"][0]["simulation"]["status"] == "feasible"


def test_measured_tape_loss_must_match_the_measured_remainder(setup):
    client, version, _ = setup
    plan = version.plan
    current = joined(client, version)
    before = stock(current, "synthetic-tape-stock")["remaining_length_mm"]["value"]
    response = report_material(
        client,
        plan,
        current,
        "waste-tape",
        kind="waste",
        stock_id="synthetic-tape-stock",
        operation_id="stand-joint-rear-attach",
        length_mm=20,
    )
    assert response.status_code == 200, response.text
    lost = response.json()["progress"]
    after = stock(lost, "synthetic-tape-stock")["remaining_length_mm"]
    assert after["value"] == before - 20 and after["source"] == "calculated"
    stale = simulate(
        client, plan, lost, [patch(plan)], key="simulate-old-tape", tape=before
    )
    stale_sim = stale.json()["previews"][0]["simulation"]
    assert stale_sim["status"] == "blocked"
    assert "Remaining connector length conflicts with confirmed consumption." in {
        b["message"] for b in stale_sim["blockers"]
    }
    fresh = simulate(
        client, plan, lost, [patch(plan)], key="simulate-new-tape", tape=before - 20
    )
    assert fresh.json()["previews"][0]["simulation"]["status"] == "feasible"


@pytest.mark.parametrize(
    "fields,status",
    [
        (dict(stock_id="synthetic-tape-stock", length_mm=20), 422),
        (
            dict(
                stock_id="synthetic-tape-stock",
                operation_id="stand-joint-rear-attach",
                length_mm=10_000,
            ),
            409,
        ),
        (dict(stock_id="synthetic-spare", region_id="no-such-region"), 409),
        (
            dict(
                stock_id="synthetic-spare",
                region_id="synthetic-spare-region",
                kind="salvage",
            ),
            409,
        ),
        (
            dict(
                stock_id="synthetic-spare",
                region_id="synthetic-spare-region",
                length_mm=5,
            ),
            422,
        ),
        (dict(stock_id="synthetic-spare"), 422),
        (dict(stock_id="no-such-stock", region_id="synthetic-spare-region"), 422),
        (dict(stock_id="synthetic-spare", length_mm=5), 422),
    ],
)
def test_invalid_material_report_leaves_history_unchanged(setup, fields, status):
    client, version, _ = setup
    plan = version.plan
    current = joined(client, version)
    body = dict(kind="waste", operation_id="stand-cut-panels") | fields
    response = report_material(client, plan, current, "invalid-material", **body)
    assert response.status_code == status, response.text
    assert progress(client, plan.project_id, plan.version_id) == current


def test_two_part_damage_cannot_be_cleared_by_one_replacement(setup):
    client, version, directory = setup
    plan = version.plan
    damaged = report_damage(
        client,
        plan,
        joined(client, version),
        part_ids=["stand-brace", "stand-support"],
    )
    response = simulate(client, plan, damaged, [patch(plan)])
    assert response.status_code == 200, response.text
    preview = response.json()["previews"][0]
    assert preview["simulation"]["status"] == "blocked"
    assert preview["version"] is None and preview["rank"] is None
    assert any(
        b["code"] == "needs_confirmation"
        and damaged["events"][-1]["id"] in b["target_ids"]
        for b in preview["simulation"]["blockers"]
    )
    refused = commit(client, plan, damaged, preview["preview_id"])
    assert (refused.status_code, refused.json()["code"]) == (409, "blocked")
    assert active(client, plan.project_id) == plan.version_id
    assert progress(client, plan.project_id, plan.version_id) == damaged
    assert set(damaged["damaged_part_ids"]) == {"stand-brace", "stand-support"}
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM plan_revisions").fetchone() == (
            0,
        )
