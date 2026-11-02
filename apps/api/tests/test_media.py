"""Private upload regressions use generated pixels, never real physical evidence."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from random import Random

import pytest
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from test_plans import prepared

from forma_api import media
from forma_api.main import create_app
from forma_api.plans import PlanService
from forma_api.progress import record_diagnosis_evidence
from forma_api.projects import ProjectStore
from forma_domain import models as domain_models
from forma_domain.fixtures import synthetic_inventory_a

TOKENS = {"alice": "a" * 40, "bob": "b" * 40}
AUTH = {"Authorization": "Bearer " + TOKENS["alice"]}
OTHER = {"Authorization": "Bearer " + TOKENS["bob"]}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        yield client


def project(client, key="project-001"):
    response = client.post(
        "/api/projects", headers=AUTH, json={"goal": "stand", "idempotency_key": key}
    )
    assert response.status_code == 201, response.text
    return response.json()["project"]


def photo(format="PNG", size=(12, 8), **options):
    with Image.new("RGB", size, "white") as image:
        output = BytesIO()
        image.save(output, format=format, **options)
        return output.getvalue()


def upload(client, p, body=None, key="upload-001", content_type="image/png", auth=AUTH):
    return client.post(
        "/api/projects/" + p["id"] + "/media",
        content=photo() if body is None else body,
        headers={**auth, "Idempotency-Key": key, "Content-Type": content_type},
    )


def inventory(p, image_ids=(), key="inventory-001"):
    stocks = [s.model_dump(mode="json") for s in synthetic_inventory_a()]
    stocks[0]["image_ids"] = image_ids
    return {
        "stocks": stocks,
        "expected_revision_id": p["revision_id"],
        "idempotency_key": key,
        "user_confirmed": True,
    }


def counts(tmp_path):
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        return connection.execute("SELECT count(*) FROM media").fetchone()[0]


def test_photo_list_restores_unlinked_uploads_and_obeys_project_scope(client):
    first = project(client)
    second = project(client, "project-002")
    first_path = f"/api/projects/{first['id']}/media"
    second_path = f"/api/projects/{second['id']}/media"
    assert client.get(first_path, headers=AUTH).json() == {"media": []}
    saved = upload(client, first).json()["media"]
    assert upload(client, first).json()["replayed"] is True
    response = client.get(first_path, headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"media": [saved]}
    assert response.headers["cache-control"] == "private, no-store"
    assert client.get(first_path).status_code == 401
    assert client.get(first_path, headers=OTHER).status_code == 404
    assert client.get(second_path, headers=AUTH).json() == {"media": []}
    assert (
        client.get("/api/projects/missing-project/media", headers=AUTH).status_code
        == 404
    )
    deleted = client.delete(
        first_path + "/" + saved["id"],
        headers={**AUTH, "Idempotency-Key": "delete-photo-001"},
    )
    assert deleted.status_code == 200
    assert client.get(first_path, headers=AUTH).json() == {"media": []}


@pytest.mark.parametrize(
    "format,mime",
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")],
)
def test_private_photo_survives_restart_and_removes_metadata(tmp_path, format, mime):
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "PRIVATE_DESCRIPTION"
    png = PngImagePlugin.PngInfo()
    png.add_text("Description", "PRIVATE_TEXT")
    body = photo(format, exif=exif, icc_profile=b"PRIVATE_ICC", pnginfo=png)
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        p = project(client)
        result = upload(client, p, body, content_type=mime)
        assert result.status_code == 201, result.text
        saved = result.json()["media"]
        assert saved["project_id"] == p["id"]
        assert (saved["width_px"], saved["height_px"]) == (8, 12)
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        response = client.get(
            f"/api/projects/{p['id']}/media/{saved['id']}", headers=AUTH
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == mime
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-disposition"] == "attachment"
        assert len(response.content) == saved["byte_count"]
        assert b"PRIVATE_" not in response.content
        with Image.open(BytesIO(response.content)) as image:
            assert image.size == (8, 12)
            assert not image.getexif()
            assert "icc_profile" not in image.info
            assert "Description" not in image.info


def test_authentication_and_cross_owner_scope(client, tmp_path):
    p = project(client)
    result = upload(client, p)
    path = f"/api/projects/{p['id']}/media/{result.json()['media']['id']}"
    for auth in ({}, OTHER):
        expected = 401 if not auth else 404
        assert client.get(path, headers=auth).status_code == expected
        assert (
            client.delete(
                path, headers={**auth, "Idempotency-Key": "delete-001"}
            ).status_code
            == expected
        )
        assert (
            upload(client, p, b"private invalid photo", auth=auth).status_code
            == expected
        )
    assert counts(tmp_path) == 1


def test_same_owner_cannot_read_reference_or_delete_another_projects_photo(client):
    first = project(client)
    second = project(client, "project-002")
    image_id = upload(client, first).json()["media"]["id"]
    wrong_path = f"/api/projects/{second['id']}/media/{image_id}"
    assert client.get(wrong_path, headers=AUTH).status_code == 404
    assert (
        client.delete(
            wrong_path, headers={**AUTH, "Idempotency-Key": "delete-001"}
        ).status_code
        == 404
    )
    response = client.put(
        f"/api/projects/{second['id']}/inventory",
        json=inventory(second, [image_id]),
        headers=AUTH,
    )
    assert response.status_code == 422
    assert client.get(f"/api/projects/{second['id']}", headers=AUTH).json() == second
    own = client.put(
        f"/api/projects/{first['id']}/inventory",
        json=inventory(first, [image_id]),
        headers=AUTH,
    )
    assert own.status_code == 200, own.text
    assert own.json()["project"]["stocks"][0]["thickness_mm"]["value"] is None


def test_photo_is_not_accepted_as_measurement_evidence(client):
    p = project(client)
    image_id = upload(client, p).json()["media"]["id"]
    body = inventory(p, [image_id])
    body["stocks"][0]["width_mm"]["evidence_ids"] = [image_id]
    assert (
        client.put(
            f"/api/projects/{p['id']}/inventory", json=body, headers=AUTH
        ).status_code
        == 422
    )


def test_referenced_photo_requires_inventory_unreference_before_delete(client):
    p = project(client)
    image_id = upload(client, p).json()["media"]["id"]
    path = f"/api/projects/{p['id']}"
    saved = client.put(
        path + "/inventory", json=inventory(p, [image_id]), headers=AUTH
    ).json()["project"]
    headers = {**AUTH, "Idempotency-Key": "delete-001"}
    assert (
        client.delete(path + "/media/" + image_id, headers=headers).status_code == 409
    )
    assert client.get(path + "/media/" + image_id, headers=AUTH).status_code == 200
    cleared = client.put(
        path + "/inventory", json=inventory(saved, (), "inventory-002"), headers=AUTH
    )
    assert cleared.status_code == 200
    deleted = client.delete(path + "/media/" + image_id, headers=headers)
    assert deleted.status_code == 200
    assert client.delete(path + "/media/" + image_id, headers=headers).json() == {
        **deleted.json(),
        "replayed": True,
    }
    assert client.get(path + "/media/" + image_id, headers=AUTH).status_code == 404
    assert upload(client, p).status_code == 404
    assert client.get(path, headers=AUTH).json() == cleared.json()["project"]


def test_upload_retries_and_changed_payload_conflicts(client, tmp_path):
    p = project(client)
    first = upload(client, p)
    assert first.status_code == 201
    assert upload(client, p).json() == {**first.json(), "replayed": True}
    assert upload(client, p, photo(size=(13, 8))).status_code == 409
    assert counts(tmp_path) == 1


def test_concurrent_identical_uploads_have_one_photo(client, tmp_path):
    p = project(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: upload(client, p), range(2)))
    assert [r.status_code for r in responses] == [201, 201]
    assert len({r.json()["media"]["id"] for r in responses}) == 1
    assert sorted(r.json()["replayed"] for r in responses) == [False, True]
    assert counts(tmp_path) == 1


@pytest.mark.parametrize(
    "body,mime,status",
    [
        (b"", "image/png", 413),
        (b"private-invalid", "image/png", 422),
        (b"<svg/>", "image/svg+xml", 415),
        (photo(), "image/jpeg", 415),
        (photo()[:40], "image/png", 422),
        (photo(), "application/octet-stream", 415),
    ],
)
def test_invalid_photos_do_not_write_or_consume_keys(
    client, tmp_path, body, mime, status
):
    p = project(client)
    response = upload(client, p, body, content_type=mime)
    assert response.status_code == status, response.text
    assert "private-invalid" not in response.text
    assert counts(tmp_path) == 0
    assert upload(client, p).status_code == 201


def test_pixel_limit_and_animated_images_are_rejected(client, monkeypatch, tmp_path):
    p = project(client)
    monkeypatch.setattr(media, "MAX_PHOTO_PIXELS", 100)
    assert upload(client, p, photo(size=(11, 10))).status_code == 413
    with (
        Image.new("RGB", (2, 2), "white") as one,
        Image.new("RGB", (2, 2), "black") as two,
    ):
        output = BytesIO()
        one.save(output, format="PNG", save_all=True, append_images=[two], duration=100)
    assert upload(client, p, output.getvalue()).status_code == 422
    assert counts(tmp_path) == 0


def test_byte_limit_applies_without_content_length(client, monkeypatch, tmp_path):
    p = project(client)
    monkeypatch.setattr(media, "MAX_PHOTO_BYTES", 100)
    response = client.post(
        f"/api/projects/{p['id']}/media",
        content=iter([b"a" * 60, b"b" * 60]),
        headers={**AUTH, "Content-Type": "image/png", "Idempotency-Key": "upload-001"},
    )
    assert response.status_code == 413
    assert counts(tmp_path) == 0


def test_failed_receipt_rolls_back_photo_write_and_delete(
    client, monkeypatch, tmp_path
):
    p = project(client)
    original = ProjectStore.remember

    def fail(*args):
        raise sqlite3.OperationalError("synthetic receipt failure")

    monkeypatch.setattr(ProjectStore, "remember", staticmethod(fail))
    with pytest.raises(sqlite3.OperationalError):
        upload(client, p)
    assert counts(tmp_path) == 0
    monkeypatch.setattr(ProjectStore, "remember", staticmethod(original))
    image_id = upload(client, p).json()["media"]["id"]
    monkeypatch.setattr(ProjectStore, "remember", staticmethod(fail))
    with pytest.raises(sqlite3.OperationalError):
        client.delete(
            f"/api/projects/{p['id']}/media/{image_id}",
            headers={**AUTH, "Idempotency-Key": "delete-001"},
        )
    assert counts(tmp_path) == 1


def test_project_delete_atomically_removes_photos_and_media_receipts(client, tmp_path):
    p = project(client)
    image_id = upload(client, p).json()["media"]["id"]
    path = f"/api/projects/{p['id']}"
    assert (
        client.delete(
            path, headers={**AUTH, "Idempotency-Key": "delete-001"}
        ).status_code
        == 200
    )
    assert counts(tmp_path) == 0
    assert client.get(path + "/media/" + image_id, headers=AUTH).status_code == 404
    assert upload(client, p).status_code == 404
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM requests WHERE scope LIKE ?",
                (p["id"] + ":media:%",),
            ).fetchone()[0]
            == 0
        )


def test_inventory_reference_and_photo_delete_serialize(client, tmp_path):
    p = project(client)
    image_id = upload(client, p).json()["media"]["id"]
    path = f"/api/projects/{p['id']}"

    def reference():
        return client.put(
            path + "/inventory", json=inventory(p, [image_id]), headers=AUTH
        )

    def delete():
        return client.delete(
            path + "/media/" + image_id,
            headers={**AUTH, "Idempotency-Key": "delete-001"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        referenced, deleted = [
            future.result() for future in (pool.submit(reference), pool.submit(delete))
        ]
    assert (referenced.status_code, deleted.status_code) in {(200, 409), (422, 200)}
    saved = client.get(path, headers=AUTH).json()
    if referenced.status_code == 200:
        assert saved["stocks"][0]["image_ids"] == [image_id]
        assert counts(tmp_path) == 1
    else:
        assert saved == p
        assert counts(tmp_path) == 0


def test_normalized_photo_has_its_own_byte_limit(client, monkeypatch, tmp_path):
    p = project(client)
    with Image.frombytes("RGB", (64, 64), Random(42).randbytes(64 * 64 * 3)) as image:
        output = BytesIO()
        image.save(output, format="JPEG", quality=10)
        body = output.getvalue()
    normalized, _, _ = media.decode_photo(body, "image/jpeg")
    assert len(normalized) > len(body)
    monkeypatch.setattr(media, "MAX_PHOTO_BYTES", len(body))
    response = upload(client, p, body, content_type="image/jpeg")
    assert response.status_code == 413, response.text
    assert counts(tmp_path) == 0


def test_media_list_marks_evidence_across_versions_and_delete_stays_blocked(
    client, tmp_path
):
    project_data, body, context = prepared(client)
    project_id = project_data["id"]
    service = PlanService(ProjectStore(tmp_path), allow_synthetic=True)
    first = service.compile_preview("alice", project_id, body, **context)
    assert first.status == "accepted", first.model_dump()
    historical = first.version
    second_body = body.model_copy(
        update={
            "idempotency_key": "preview-002",
            "candidate": body.candidate.model_copy(
                update={"id": "synthetic-candidate-2"}
            ),
        }
    )
    second = service.compile_preview("alice", project_id, second_body, **context)
    assert second.status == "accepted", second.model_dump()
    current = second.version
    activated = client.post(
        f"/api/projects/{project_id}/plans/{current.version_id}/activate",
        headers=AUTH,
        json={
            "expected_revision_id": project_data["revision_id"],
            "idempotency_key": "activate-evidence-001",
            "user_approved": True,
        },
    )
    assert activated.status_code == 200, activated.text

    def uploaded(key):
        response = upload(client, project_data, key=key)
        assert response.status_code == 201, response.text
        saved = response.json()["media"]
        assert saved["evidence_linked"] is False
        return saved["id"]

    historical_id = uploaded("upload-evidence-historical")
    diagnosis_id = uploaded("upload-evidence-diagnosis")
    physical_id = uploaded("upload-evidence-physical")
    free_id = uploaded("upload-evidence-free")

    diagnosis = domain_models.DiagnosisProposal(
        visible_observations=["A tear is visible"],
        hypotheses=["The slot may be weak"],
        questions_or_measurements=["Measure the edge distance"],
        affected_ids=[],
        failure_type="torn_slot",
    )
    store = ProjectStore(tmp_path)
    with store.transaction() as connection:
        for version, media_id in (
            (historical, historical_id),
            (current, diagnosis_id),
        ):
            record_diagnosis_evidence(
                connection,
                project_id=project_id,
                version_id=version.version_id,
                operation_id=version.plan.operations[0].id,
                media_id=media_id,
                diagnosis=diagnosis,
                part_ids=(version.plan.parts[0].id,),
            )

    operation = current.plan.operations[0]
    progress = client.get(
        f"/api/projects/{project_id}/versions/{current.version_id}/progress",
        headers=AUTH,
    ).json()
    reported = client.post(
        f"/api/projects/{project_id}/events",
        headers=AUTH,
        json={
            "expected_version_id": current.version_id,
            "expected_last_event_id": progress["last_event_id"],
            "idempotency_key": "progress-evidence-001",
            "operation_id": operation.id,
            "result": "passed"
            if operation.type in {"inspect", "functional_test"}
            else "completed",
            "observation": "SYNTHETIC software action; no actual physical result",
            "user_confirmed": True,
            "checks_confirmed": True,
            "photo_ids": [physical_id],
        },
    )
    assert reported.status_code == 200, reported.text

    path = f"/api/projects/{project_id}/media"
    assert client.get(path, headers=OTHER).status_code == 404
    response = client.get(path, headers=AUTH)
    assert response.status_code == 200
    listed = {item["id"]: item for item in response.json()["media"]}
    assert listed[historical_id]["evidence_linked"] is True
    assert listed[diagnosis_id]["evidence_linked"] is True
    assert listed[physical_id]["evidence_linked"] is True
    assert listed[free_id]["evidence_linked"] is False
    for item in listed.values():
        assert set(item) == {
            "id",
            "project_id",
            "content_type",
            "byte_count",
            "width_px",
            "height_px",
            "evidence_linked",
        }
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        evidence_ids = [
            row[0]
            for row in connection.execute(
                "SELECT id FROM progress_evidence WHERE project_id=?", (project_id,)
            )
        ]
    assert evidence_ids
    for evidence_id in evidence_ids:
        assert evidence_id not in response.text
    assert "A tear is visible" not in response.text

    other_project = project(client, "project-other-owner-scope")
    other_photo = upload(client, other_project, key="upload-other-scope").json()[
        "media"
    ]
    other_list = client.get(
        f"/api/projects/{other_project['id']}/media", headers=AUTH
    ).json()["media"]
    assert other_list == [{**other_photo, "evidence_linked": False}]

    headers = {**AUTH, "Idempotency-Key": "delete-evidence-001"}
    blocked = client.delete(path + "/" + historical_id, headers=headers)
    assert blocked.status_code == 409
    assert client.get(path + "/" + historical_id, headers=AUTH).status_code == 200
    assert client.get(path, headers=AUTH).json()["media"] == response.json()["media"]
    assert (
        client.delete(
            path + "/" + free_id,
            headers={**AUTH, "Idempotency-Key": "delete-free-001"},
        ).status_code
        == 200
    )


def test_project_delete_failure_restores_photo_and_inventory(
    client, monkeypatch, tmp_path
):
    p = project(client)
    image_id = upload(client, p).json()["media"]["id"]
    path = f"/api/projects/{p['id']}"
    saved = client.put(
        path + "/inventory", json=inventory(p, [image_id]), headers=AUTH
    ).json()["project"]

    def fail(*args):
        raise sqlite3.OperationalError("synthetic receipt failure")

    monkeypatch.setattr(ProjectStore, "remember", staticmethod(fail))
    with pytest.raises(sqlite3.OperationalError):
        client.delete(path, headers={**AUTH, "Idempotency-Key": "delete-001"})
    assert counts(tmp_path) == 1
    assert client.get(path, headers=AUTH).json() == saved
    assert client.get(path + "/media/" + image_id, headers=AUTH).status_code == 200
