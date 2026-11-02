"""Synthetic software reports only; no real physical attempt or pass."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from forma_compiler import validate_plan
from forma_replanner import simulate_patch
from PIL import Image
from test_plans import AUTH, OTHER, TOKENS, approval, prepared

from forma_api.main import create_app
from forma_api.plans import PlanService
from forma_api.progress import record_diagnosis_evidence
from forma_api.projects import ProjectStore
from forma_domain import models as m


@pytest.fixture
def preview_setup(tmp_path, request, monkeypatch):
    if getattr(request, "param", None) == "offcut":
        from forma_api import plans as module

        compile_stand = module.compile_stand

        def compile_declared_offcut(*args, **kwargs):
            compiled = compile_stand(*args, **kwargs)
            assert compiled.status == "accepted"
            data = compiled.plan.model_dump()
            data["operations"][0]["effects"]["created_offcuts"] = (
                m.Region(
                    id="synthetic-offcut",
                    geometry=m.Rect(x=120, y=400, width=40, height=80),
                ),
            )
            return validate_plan(
                m.BuildPlan.model_validate(data),
                process=kwargs["process"],
                allow_synthetic=True,
            )

        monkeypatch.setattr(module, "compile_stand", compile_declared_offcut)
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        project, body, context = prepared(client)
        if getattr(request, "param", None) == "fractional":
            stocks = project["stocks"]
            stocks[1]["remaining_length_mm"]["value"] = 240.03
            project = client.put(
                f"/api/projects/{project['id']}/inventory",
                headers=AUTH,
                json={
                    "expected_revision_id": project["revision_id"],
                    "idempotency_key": "fractional-inventory",
                    "stocks": stocks,
                    "user_confirmed": True,
                },
            ).json()["project"]
            body = body.model_copy(
                update={
                    "expected_revision_id": project["revision_id"],
                    "candidate": body.candidate.model_copy(
                        update={"part_width_mm": 80.01}
                    ),
                }
            )
        compiled = PlanService(
            ProjectStore(tmp_path), allow_synthetic=True
        ).compile_preview("alice", project["id"], body, **context)
        assert compiled.status == "accepted"
        version = compiled.version
        yield client, version, tmp_path


@pytest.fixture
def setup(preview_setup):
    client, version, directory = preview_setup
    response = client.post(
        f"/api/projects/{version.project_id}/plans/{version.version_id}/activate",
        headers=AUTH,
        json=approval({"revision_id": version.inventory_revision_id}),
    )
    assert response.status_code == 200, response.text
    return client, version, directory


def progress(client, version, headers=AUTH):
    return client.get(
        f"/api/projects/{version.project_id}/versions/{version.version_id}/progress",
        headers=headers,
    )


def update(version, current, index=0, key=None, result=None):
    operation = version.plan.operations[index]
    return dict(
        expected_version_id=version.version_id,
        expected_last_event_id=current["last_event_id"],
        idempotency_key=key or f"progress-{index:03d}",
        operation_id=operation.id,
        result=result
        or (
            "passed"
            if operation.type in {"inspect", "functional_test"}
            else "completed"
        ),
        observation="SYNTHETIC software action; no actual physical result",
        user_confirmed=True,
        checks_confirmed=True,
        photo_ids=[],
    )


def post(client, version, body, headers=AUTH):
    return client.post(
        f"/api/projects/{version.project_id}/events", headers=headers, json=body
    )


def complete(client, version, index):
    response = post(
        client, version, update(version, progress(client, version).json(), index)
    )
    assert response.status_code == 200, response.text
    return response.json()["progress"]


def photo(client, version):
    buffer = BytesIO()
    Image.new("RGB", (3, 3), "white").save(buffer, format="PNG")
    response = client.post(
        f"/api/projects/{version.project_id}/media",
        content=buffer.getvalue(),
        headers={
            **AUTH,
            "Content-Type": "image/png",
            "Idempotency-Key": "progress-photo-001",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["media"]["id"]


def test_empty_preview_history_and_active_version_gate(setup):
    client, version, _ = setup
    response = progress(client, version)
    assert response.headers["Cache-Control"] == "no-store"
    empty = response.json()
    assert empty["status"] == "not_started"
    assert empty["events"] == empty["evidence"] == empty["material_transactions"] == []
    assert empty["expected_remaining_stock"] == [
        s.model_dump(mode="json") for s in version.plan.stocks
    ]
    assert (
        post(
            client,
            version,
            {**update(version, empty), "expected_version_id": "another-version"},
        ).status_code
        == 409
    )
    assert progress(client, version).json() == empty


def test_diagnosis_evidence_does_not_change_status_or_block_next_report(setup):
    client, version, directory = setup
    before = progress(client, version).json()
    photo_id = photo(client, version)
    diagnosis = m.DiagnosisProposal(
        visible_observations=["A tear is visible"],
        hypotheses=["The slot may be weak"],
        questions_or_measurements=["Measure the edge distance"],
        affected_ids=[version.plan.parts[0].id],
        failure_type="torn_slot",
    )
    store = ProjectStore(directory)
    with store.transaction() as connection:
        record_diagnosis_evidence(
            connection,
            project_id=version.project_id,
            version_id=version.version_id,
            operation_id=version.plan.operations[0].id,
            media_id=photo_id,
            diagnosis=diagnosis,
            part_ids=(version.plan.parts[0].id,),
        )
    after = progress(client, version).json()
    assert after["status"] == before["status"]
    assert after["last_event_id"] == before["last_event_id"]
    assert after["completed_operation_ids"] == before["completed_operation_ids"]
    assert after["failed_operation_ids"] == before["failed_operation_ids"]
    assert after["events"] == before["events"]
    assert len(after["evidence"]) == 1
    assert after["evidence"][0]["kind"] == "model_interpretation"
    saved = complete(client, version, 0)
    assert saved["completed_operation_ids"] == [version.plan.operations[0].id]
    assert saved["last_event_id"] is not None


def test_saved_preview_can_be_read_but_cannot_record_work(preview_setup):
    client, version, _ = preview_setup
    empty = progress(client, version).json()
    assert empty["status"] == "not_started"
    assert post(client, version, update(version, empty)).status_code == 409
    assert progress(client, version).json() == empty


@pytest.mark.parametrize("preview_setup", ["offcut"], indirect=True)
def test_declared_offcut_receipt_and_expected_region_match_real_validation(setup):
    client, version, _ = setup
    saved = complete(client, version, 0)
    consume, offcut = saved["material_transactions"]
    declared = version.plan.operations[0].effects.created_offcuts[0]
    assert consume["quantity"] == 110000
    assert offcut["kind"] == "offcut" and offcut["quantity"] == 3200
    assert offcut["output_region"] == declared.model_dump(mode="json")
    assert saved["expected_remaining_stock"][0]["usable_regions"] == [
        declared.model_dump(mode="json")
    ]
    assert consume["physical_event_id"] == offcut["physical_event_id"]


@pytest.mark.parametrize("preview_setup", ["fractional"], indirect=True)
def test_exact_fractional_connector_exhaustion_does_not_invent_a_tolerance(setup):
    client, version, _ = setup
    for index in range(len(version.plan.operations)):
        saved = complete(client, version, index)
    assert saved["status"] == "passed"
    assert saved["expected_remaining_stock"][1]["remaining_length_mm"]["value"] == 0
    assert [
        t["quantity"] for t in saved["material_transactions"] if t["unit"] == "mm"
    ] == [80.01] * 3


def test_receipts_match_replanner_and_changed_receipt_is_rejected(setup):
    client, version, directory = setup
    saved = complete(client, version, 0)
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        process = connection.execute(
            "SELECT process FROM plans WHERE version_id=?", (version.version_id,)
        ).fetchone()[0]
    from forma_compiler import CutProcess

    patch = m.RepairPatch(
        id="synthetic-patch",
        base_version_id=version.version_id,
        kind="resize_part",
        target_id=version.plan.parts[0].id,
        replacement_stock_id=None,
        replacement_profile_id=None,
        width_mm=70,
        height_mm=140,
        angle_deg=None,
        rationale="SYNTHETIC receipt compatibility check",
    )
    source = m.ReplannerInput(
        base_plan=version.plan,
        events=tuple(m.PhysicalEvent.model_validate(e) for e in saved["events"]),
        evidence=tuple(m.Evidence.model_validate(e) for e in saved["evidence"]),
        material_transactions=tuple(
            m.MaterialTransaction.model_validate(e)
            for e in saved["material_transactions"]
        ),
        remaining_stock=tuple(
            m.Stock.model_validate(s) for s in saved["expected_remaining_stock"]
        ),
        patch=patch,
    )
    outcome = simulate_patch(
        source, process=CutProcess.model_validate_json(process), allow_synthetic=True
    )
    assert "invalid_reference" not in {b.code for b in outcome.blockers}
    changed = source.model_dump()
    changed["material_transactions"][0]["quantity"] = 100
    rejected = simulate_patch(
        m.ReplannerInput.model_validate(changed),
        process=CutProcess.model_validate_json(process),
        allow_synthetic=True,
    )
    assert "invalid_reference" in {b.code for b in rejected.blockers}


def test_scope_is_checked_before_progress_or_replay(setup):
    client, version, _ = setup
    body = update(version, progress(client, version).json())
    assert post(client, version, body, OTHER).status_code == 404
    assert progress(client, version, OTHER).status_code == 404
    assert progress(client, version, {}).status_code == 401
    assert post(client, version, body).status_code == 200
    assert post(client, version, body, OTHER).status_code == 404
    other = version.model_copy(update={"project_id": "unknown-project"})
    assert progress(client, other).status_code == 404
    wrong_version = version.model_copy(update={"version_id": "unknown-version"})
    assert progress(client, wrong_version).status_code == 404


def test_cut_receipt_and_immutable_plan_replay_and_restart(setup):
    client, version, directory = setup
    initial = progress(client, version).json()
    body = update(version, initial)
    first = post(client, version, body)
    assert first.status_code == 200, first.text
    assert first.headers["Cache-Control"] == "no-store"
    saved = first.json()["progress"]
    assert saved["completed_operation_ids"] == [version.plan.operations[0].id]
    assert saved["expected_remaining_stock"][0]["usable_regions"] == []
    receipt = saved["material_transactions"][0]
    assert receipt["kind"] == "consume"
    assert receipt["quantity"] == 200 * 550
    assert receipt["unit"] == "mm2"
    assert (
        receipt["source_region_id"] == version.plan.operations[0].args.source_region_id
    )
    assert receipt["physical_event_id"] == saved["events"][0]["id"]
    assert saved["events"][0]["actor"] == "user"
    assert saved["evidence"][0]["provenance"] == "user"
    assert post(client, version, body).json() == {**first.json(), "replayed": True}
    changed = {**body, "observation": "Changed retry"}
    assert post(client, version, changed).json()["code"] == "idempotency_conflict"
    assert progress(client, version).json() == saved
    assert client.get(
        f"/api/projects/{version.project_id}/versions/{version.version_id}",
        headers=AUTH,
    ).json() == version.model_dump(mode="json")
    with TestClient(create_app(directory, TOKENS)) as restarted:
        assert progress(restarted, version).json() == saved


def test_dependencies_stale_history_and_duplicate_completion_do_not_mutate(setup):
    client, version, _ = setup
    empty = progress(client, version).json()
    assert post(client, version, update(version, empty, 1)).status_code == 409
    assert progress(client, version).json() == empty
    current = complete(client, version, 0)
    assert (
        post(client, version, update(version, empty, 1)).json()["code"]
        == "stale_version"
    )
    assert (
        post(
            client, version, update(version, current, 0, key="duplicate-001")
        ).status_code
        == 409
    )
    assert progress(client, version).json() == current


@pytest.mark.parametrize(
    "change",
    [
        {"operation_id": "unknown-operation"},
        {"result": "passed"},
        {"user_confirmed": False},
        {"user_confirmed": 1},
        {"checks_confirmed": False},
        {"observation": "  "},
        {"actor": "system"},
        {"material_transactions": []},
        {"photo_ids": ["foreign-photo"]},
        {"photo_ids": ["photo-1", "photo-1"]},
    ],
)
def test_invalid_report_leaves_history_unchanged(setup, change):
    client, version, _ = setup
    initial = progress(client, version).json()
    response = post(client, version, {**update(version, initial), **change})
    assert response.status_code == 422, response.text
    assert progress(client, version).json() == initial


def test_pass_all_steps_records_defined_test_and_connector_use_once(setup):
    client, version, _ = setup
    for index in range(len(version.plan.operations)):
        current = complete(client, version, index)
    assert current["status"] == "passed"
    assert current["completed_operation_ids"] == [
        op.id for op in version.plan.operations
    ]
    assert len(current["events"]) == 9
    test, completion = current["events"][-2:]
    assert test["kind"] == "test" and test["test_result"] == "passed"
    assert completion["kind"] == "operation_confirmed"
    assert test["evidence_ids"] == completion["evidence_ids"]
    assert current["evidence"][-1]["kind"] == "physical_test"
    assert current["evidence"][-1]["checkpoint_ids"] == [
        version.plan.operations[-1].args.checkpoint_id
    ]
    tape = current["expected_remaining_stock"][1]["remaining_length_mm"]
    assert tape == {
        "value": 260.0,
        "unit": "mm",
        "source": "calculated",
        "confirmed": False,
        "evidence_ids": [],
    }
    assert [
        tx["quantity"] for tx in current["material_transactions"] if tx["unit"] == "mm"
    ] == [80, 80, 80]
    assert all(event["actor"] == "user" for event in current["events"])
    assert version.plan.stocks[1].remaining_length_mm.value == 500


@pytest.mark.parametrize("index", [1, 7])
def test_failed_checks_remain_failed_and_freeze_confirmations(setup, index):
    client, version, _ = setup
    for previous in range(index):
        complete(client, version, previous)
    body = update(version, progress(client, version).json(), index, result="failed")
    response = post(client, version, body)
    assert response.status_code == 200, response.text
    failed = response.json()["progress"]
    assert failed["status"] == "needs_review"
    assert failed["failed_operation_ids"] == [version.plan.operations[index].id]
    assert version.plan.operations[index].id not in failed["completed_operation_ids"]
    assert failed["events"][-1]["verification_state"] == "failed"
    assert failed["evidence"][-1]["verification_state"] == "failed"
    if index == 7:
        assert failed["events"][-1]["test_result"] == "failed"
    retry = update(version, failed, index, key="retry-failed-check")
    assert post(client, version, retry).status_code == 409
    assert progress(client, version).json() == failed


def test_concurrent_confirmation_has_one_winner(setup):
    client, version, _ = setup
    empty = progress(client, version).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda key: post(client, version, update(version, empty, key=key)),
                ["parallel-progress-001", "parallel-progress-002"],
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 409]
    current = progress(client, version).json()
    assert len(current["events"]) == len(current["material_transactions"]) == 1


def test_receipt_failure_rolls_back_every_progress_record(setup, monkeypatch):
    client, version, _ = setup
    before = progress(client, version).json()
    original = ProjectStore.remember

    def fail(*args):
        raise sqlite3.OperationalError("SYNTHETIC receipt failure")

    monkeypatch.setattr(ProjectStore, "remember", staticmethod(fail))
    with pytest.raises(sqlite3.OperationalError):
        post(client, version, update(version, before))
    assert progress(client, version).json() == before
    monkeypatch.setattr(ProjectStore, "remember", staticmethod(original))
    assert post(client, version, update(version, before)).status_code == 200


def test_photo_evidence_is_private_and_cannot_be_individually_deleted(setup):
    client, version, _ = setup
    photo_id = photo(client, version)
    body = {
        **update(version, progress(client, version).json()),
        "photo_ids": [photo_id],
    }
    response = post(client, version, body)
    assert response.status_code == 200, response.text
    items = response.json()["progress"]["evidence"]
    assert items[-1]["kind"] == "photo" and items[-1]["asset_id"] == photo_id
    deletion = client.delete(
        f"/api/projects/{version.project_id}/media/{photo_id}",
        headers={**AUTH, "Idempotency-Key": "delete-progress-photo"},
    )
    assert deletion.status_code == 409
    assert (
        client.get(
            f"/api/projects/{version.project_id}/media/{photo_id}", headers=AUTH
        ).status_code
        == 200
    )


def test_project_deletion_purges_history_photos_and_retry_snapshots(setup):
    client, version, directory = setup
    photo_id = photo(client, version)
    body = {
        **update(version, progress(client, version).json()),
        "photo_ids": [photo_id],
    }
    assert post(client, version, body).status_code == 200
    assert (
        client.delete(
            f"/api/projects/{version.project_id}",
            headers={**AUTH, "Idempotency-Key": "delete-progress-project"},
        ).status_code
        == 200
    )
    assert post(client, version, body).status_code == 404
    assert progress(client, version).status_code == 404
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        for table in (
            "progress_events",
            "progress_evidence",
            "progress_material",
            "plans",
            "media",
        ):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )
        receipts = [
            row[0] for row in connection.execute("SELECT response FROM requests")
        ]
    assert all("SYNTHETIC software action" not in receipt for receipt in receipts)


def test_server_ingestion_order_survives_clock_moving_backwards(setup, monkeypatch):
    from forma_api import progress as module

    client, version, _ = setup
    first = complete(client, version, 0)

    class Earlier(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2000, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(module, "datetime", Earlier)
    second = complete(client, version, 1)
    assert second["events"][-1]["recorded_at"] > first["events"][-1]["recorded_at"]
    assert second["evidence"][-1]["recorded_at"] <= second["events"][-1]["recorded_at"]
