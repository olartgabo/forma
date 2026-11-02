"""Photo-excluded snapshots over synthetic plans and reports, not physical evidence."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

import pytest
from test_plans import AUTH, OTHER, stand_inputs
from test_progress import complete, photo, post, progress, update
from test_progress import preview_setup as preview_setup
from test_progress import setup as setup

from forma_api.plans import CompilePreview, PlanService
from forma_api.projects import ProjectStore


def proof(client, project_id, headers=AUTH):
    return client.get(f"/api/projects/{project_id}/proof", headers=headers)


def another_preview(client, directory, project_id, *, candidate_id="synthetic-second"):
    project = client.get(f"/api/projects/{project_id}", headers=AUTH).json()
    _, _, candidate, parameters, process, profiles = stand_inputs(project_id)
    result = PlanService(ProjectStore(directory), allow_synthetic=True).compile_preview(
        "alice",
        project_id,
        CompilePreview(
            expected_revision_id=project["revision_id"],
            idempotency_key=candidate_id,
            candidate=candidate.model_copy(
                update={"id": candidate_id, "part_width_mm": 90}
            ),
        ),
        process=process,
        parameters=parameters,
        joint_profiles=profiles,
        kerf_mm=2,
        edge_margin_mm=4,
    )
    assert result.status == "accepted", result
    return result.version


def activate(client, version):
    response = client.post(
        f"/api/projects/{version.project_id}/plans/{version.version_id}/activate",
        headers=AUTH,
        json={
            "expected_revision_id": version.inventory_revision_id,
            "idempotency_key": "proof-activation-001",
            "user_approved": True,
        },
    )
    assert response.status_code == 200, response.text


def test_empty_project_returns_explicit_initial_report_coverage(preview_setup):
    client, _, _ = preview_setup
    project = client.post(
        "/api/projects",
        headers=AUTH,
        json={"goal": "SYNTHETIC empty proof", "idempotency_key": "proof-empty-001"},
    ).json()["project"]
    response = proof(client, project["id"])
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    report = response.json()
    assert report["project"] == project
    assert report["versions"] == []
    assert report["photos_omitted"] == 0
    assert report["photo_policy"] == "excluded"
    assert report["coverage"] == "initial_plan_reports"
    assert report["generated_at"].endswith("Z")


def test_scope_is_checked_before_any_proof_data(preview_setup):
    client, version, _ = preview_setup
    assert proof(client, version.project_id, {}).status_code == 401
    foreign = proof(client, version.project_id, OTHER)
    assert foreign.status_code == 404
    assert version.version_id not in foreign.text
    assert proof(client, "missing-project").status_code == 404
    assert proof(client, version.project_id).status_code == 200


def test_saved_previews_remain_unattempted_in_stable_version_order(preview_setup):
    client, first, directory = preview_setup
    second = another_preview(client, directory, first.project_id)
    activate(client, second)
    for _ in range(2):
        report = proof(client, first.project_id).json()
        assert report["project"]["active_version_id"] == second.version_id
        assert [item["plan"]["version_id"] for item in report["versions"]] == [
            first.version_id,
            second.version_id,
        ]
        assert [item["candidate_id"] for item in report["versions"]] == [
            first.candidate_id,
            second.candidate_id,
        ]
        assert all(
            item["progress"]["status"] == "not_started" for item in report["versions"]
        )
        assert all(item["progress"]["events"] == [] for item in report["versions"])


@pytest.mark.parametrize("outcome", ["failed", "passed"])
def test_proof_preserves_actual_user_report_outcomes_and_named_test_conditions(
    setup, outcome
):
    client, version, _ = setup
    for index in range(7):
        complete(client, version, index)
    response = post(
        client,
        version,
        update(version, progress(client, version).json(), 7, result=outcome),
    )
    assert response.status_code == 200, response.text
    canonical = response.json()["progress"]
    report = proof(client, version.project_id).json()
    included = report["versions"][0]
    assert included["progress"] == canonical
    assert included["progress"]["status"] == (
        "needs_review" if outcome == "failed" else "passed"
    )
    test_event = next(event for event in canonical["events"] if event["kind"] == "test")
    assert test_event["test_result"] == outcome
    test = included["plan"]["operations"][-1]["args"]
    assert test["device_label"] == "SYNTHETIC phone"
    assert test["duration_seconds"] == 60
    assert test["surface"] == "SYNTHETIC desk"
    assert test["pass_criteria"] == ["No slip or tip"]
    assert canonical["evidence"][-1]["provenance"] == "user"
    assert (
        canonical["expected_remaining_stock"][1]["remaining_length_mm"]["confirmed"]
        is False
    )
    assert "manual" not in included


def test_photos_are_redacted_from_every_copy_without_changing_private_sources(
    preview_setup,
):
    client, first, directory = preview_setup
    photo_id = photo(client, first)
    original_photo = client.get(
        f"/api/projects/{first.project_id}/media/{photo_id}", headers=AUTH
    )
    unlinked = client.post(
        f"/api/projects/{first.project_id}/media",
        content=original_photo.content,
        headers={
            **AUTH,
            "Content-Type": "image/png",
            "Idempotency-Key": "proof-unlinked-photo",
        },
    ).json()["media"]["id"]
    project = client.get(f"/api/projects/{first.project_id}", headers=AUTH).json()
    project["stocks"][0]["image_ids"] = [photo_id]
    saved = client.put(
        f"/api/projects/{first.project_id}/inventory",
        headers=AUTH,
        json={
            "expected_revision_id": project["revision_id"],
            "idempotency_key": "proof-photo-inventory",
            "stocks": project["stocks"],
            "user_confirmed": True,
        },
    )
    assert saved.status_code == 200, saved.text
    version = another_preview(client, directory, first.project_id)
    activate(client, version)
    recorded = post(
        client,
        version,
        {
            **update(version, progress(client, version).json()),
            "photo_ids": [photo_id],
        },
    )
    assert recorded.status_code == 200, recorded.text
    source_project = client.get(
        f"/api/projects/{version.project_id}", headers=AUTH
    ).json()
    source_version = client.get(
        f"/api/projects/{version.project_id}/versions/{version.version_id}",
        headers=AUTH,
    ).json()
    source_progress = progress(client, version).json()
    for _ in range(2):
        response = proof(client, version.project_id)
        assert response.status_code == 200
        report = response.json()
        assert report["photos_omitted"] == 2
        assert photo_id not in response.text and unlinked not in response.text
        assert "<svg" not in response.text and "data:image" not in response.text
        assert all(stock["image_ids"] == [] for stock in report["project"]["stocks"])
        for item in report["versions"]:
            assert all(stock["image_ids"] == [] for stock in item["plan"]["stocks"])
            assert all(
                stock["image_ids"] == []
                for stock in item["progress"]["expected_remaining_stock"]
            )
            assert all(
                evidence["asset_id"] is None
                for evidence in item["progress"]["evidence"]
            )
    assert (
        client.get(f"/api/projects/{version.project_id}", headers=AUTH).json()
        == source_project
    )
    assert (
        client.get(
            f"/api/projects/{version.project_id}/versions/{version.version_id}",
            headers=AUTH,
        ).json()
        == source_version
    )
    assert progress(client, version).json() == source_progress
    assert source_project["stocks"][0]["image_ids"] == [photo_id]
    assert source_version["plan"]["stocks"][0]["image_ids"] == [photo_id]
    assert source_progress["evidence"][-1]["asset_id"] == photo_id
    assert (
        client.get(
            f"/api/projects/{version.project_id}/media/{photo_id}", headers=AUTH
        ).content
        == original_photo.content
    )


def test_proof_transaction_keeps_one_history_frontier_during_concurrent_report(
    setup, monkeypatch
):
    from forma_api import proof as module

    client, version, _ = setup
    before = progress(client, version).json()
    entered = Event()
    release = Event()
    writer_started = Event()
    snapshot = module.snapshot

    def paused_snapshot(connection, plan):
        entered.set()
        assert release.wait(5), "Test did not release the proof read"
        return snapshot(connection, plan)

    def write():
        writer_started.set()
        return post(client, version, update(version, before))

    monkeypatch.setattr(module, "snapshot", paused_snapshot)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(proof, client, version.project_id)
        assert entered.wait(5), "Proof did not reach its snapshot read"
        writing = pool.submit(write)
        assert writer_started.wait(5)
        try:
            with pytest.raises(TimeoutError):
                writing.result(timeout=0.1)
        finally:
            release.set()
        old = reading.result(timeout=5)
        appended = writing.result(timeout=5)
    assert old.status_code == appended.status_code == 200
    old_progress = old.json()["versions"][0]["progress"]
    assert old_progress == before
    assert (
        old_progress["events"]
        == old_progress["evidence"]
        == old_progress["material_transactions"]
        == []
    )
    monkeypatch.setattr(module, "snapshot", snapshot)
    current = proof(client, version.project_id).json()["versions"][0]["progress"]
    assert current == appended.json()["progress"]
    assert (
        len(current["events"])
        == len(current["evidence"])
        == len(current["material_transactions"])
        == 1
    )
