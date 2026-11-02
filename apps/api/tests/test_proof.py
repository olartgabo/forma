"""Photo-excluded snapshots over synthetic plans and reports, not physical evidence."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

import pytest
import test_adapt
from test_adapt import commit, joined, patch, simulate
from test_plans import AUTH, OTHER, stand_inputs
from test_progress import complete, photo, post, progress, update
from test_progress import preview_setup as preview_setup
from test_progress import setup as setup

from forma_api.plans import CompilePreview, PlanService
from forma_api.progress import record_diagnosis_evidence
from forma_api.projects import ProjectStore
from forma_domain.models import DiagnosisProposal

repair_setup = test_adapt.setup


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
    assert report["coverage"] == "versioned_plan_reports"
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
        assert [item["state"] for item in report["versions"]] == ["preview", "active"]
        assert all(item["revision"] is None for item in report["versions"])


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
    monkeypatch,
):
    from forma_api import adapt

    monkeypatch.setattr(adapt, "ALLOW_SYNTHETIC", True)
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
    spare = {
        **project["stocks"][0],
        "id": "synthetic-spare",
        "usable_regions": [
            {
                **project["stocks"][0]["usable_regions"][0],
                "id": "synthetic-spare-region",
            }
        ],
    }
    saved = client.put(
        f"/api/projects/{first.project_id}/inventory",
        headers=AUTH,
        json={
            "expected_revision_id": project["revision_id"],
            "idempotency_key": "proof-photo-inventory",
            "stocks": project["stocks"] + [spare],
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
    for index in range(1, 6):
        complete(client, version, index)
    current = progress(client, version).json()
    remaining_tape = next(
        stock["remaining_length_mm"]["value"]
        for stock in current["expected_remaining_stock"]
        if stock["id"] == "synthetic-tape-stock"
    )
    preview_response = simulate(
        client, version.plan, current, [patch(version.plan)], tape=remaining_tape
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()["previews"][0]
    assert preview["version"] is not None, preview["simulation"]["blockers"]
    approved = commit(client, version.plan, current, preview["preview_id"])
    assert approved.status_code == 200, approved.text
    response = proof(client, version.project_id)
    assert response.status_code == 200, response.text
    assert photo_id not in response.text and unlinked not in response.text
    assert [item["state"] for item in response.json()["versions"]] == [
        "preview",
        "historical",
        "active",
    ]
    repaired = response.json()["versions"][-1]
    assert repaired["revision"] is not None
    assert all(
        stock["image_ids"] == []
        for stock in repaired["revision"]["simulation"]["plan"]["stocks"]
    )
    with ProjectStore(directory).transaction() as connection:
        original = connection.execute(
            "SELECT body FROM plan_revisions WHERE id=?",
            (repaired["plan"]["version_id"],),
        ).fetchone()[0]
    assert photo_id in original


def test_repair_proof_keeps_failed_history_and_scopes_invalidations_to_its_source(
    repair_setup,
):
    client, version, _ = repair_setup
    joined(client, version)
    complete(client, version, 6)
    photo_id = photo(client, version)
    failed = post(
        client,
        version,
        {
            **update(version, progress(client, version).json(), 7, result="failed"),
            "photo_ids": [photo_id],
        },
    )
    assert failed.status_code == 200, failed.text
    original_progress = progress(client, version).json()
    response = simulate(client, version.plan, original_progress, [patch(version.plan)])
    assert response.status_code == 200, response.text
    preview = response.json()["previews"][0]
    approved = commit(client, version.plan, original_progress, preview["preview_id"])
    assert approved.status_code == 200, approved.text
    receipt = approved.json()
    assert receipt["invalidations"]
    report_response = proof(client, version.project_id)
    assert report_response.status_code == 200, report_response.text
    old, repaired = report_response.json()["versions"]
    assert [old["state"], repaired["state"]] == ["historical", "active"]
    assert old["revision"] is None
    assert old["invalidations"] == receipt["invalidations"]
    assert repaired["invalidations"] == []
    assert repaired["revision"] == receipt["revision"]
    assert old["progress"]["status"] == "needs_review"
    assert old["progress"]["events"] == original_progress["events"]
    assert (
        old["progress"]["material_transactions"]
        == original_progress["material_transactions"]
    )
    assert all(
        item["evidence_id"] in {e["id"] for e in old["progress"]["evidence"]}
        for item in old["invalidations"]
    )
    failed_evidence = next(
        e for e in old["progress"]["evidence"] if e["kind"] == "physical_test"
    )
    assert failed_evidence["verification_state"] == "failed"
    assert failed_evidence["checkpoint_ids"]
    assert any(i["evidence_id"] == failed_evidence["id"] for i in old["invalidations"])
    assert all(
        i["invalidated_for_version_id"] == repaired["plan"]["version_id"]
        and i["reason"]
        for i in old["invalidations"]
    )
    assert repaired["progress"]["events"] == []
    assert repaired["progress"]["status"] == "building"
    assert (
        repaired["progress"]["carried_operation_ids"]
        == receipt["revision"]["carried_completed_operation_ids"]
    )
    assert photo_id not in report_response.text
    assert progress(client, version).json() == original_progress
    assert proof(client, version.project_id, OTHER).status_code == 404


def test_proof_strips_diagnosis_evidence_asset_id(setup):
    client, version, directory = setup
    photo_id = photo(client, version)
    diagnosis = DiagnosisProposal(
        visible_observations=["A tear is visible"],
        hypotheses=["The slot may be weak"],
        questions_or_measurements=["Measure the edge distance"],
        affected_ids=[version.plan.parts[0].id],
        failure_type="torn_slot",
    )
    with ProjectStore(directory).transaction() as connection:
        record_diagnosis_evidence(
            connection,
            project_id=version.project_id,
            version_id=version.version_id,
            operation_id=version.plan.operations[0].id,
            media_id=photo_id,
            diagnosis=diagnosis,
            part_ids=(version.plan.parts[0].id,),
        )
    response = proof(client, version.project_id)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["photo_policy"] == "excluded"
    assert photo_id not in response.text
    evidence = report["versions"][0]["progress"]["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["asset_id"] is None
    assert evidence[0]["kind"] == "model_interpretation"
    assert "torn_slot" in evidence[0]["description"]
    # Private source retains the media reference.
    source = progress(client, version).json()
    assert source["evidence"][0]["asset_id"] == photo_id


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
