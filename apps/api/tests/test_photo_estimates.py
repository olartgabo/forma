"""Photo estimate routes: provenance, retries, staleness and inventory gates."""

import sqlite3
import sys
from pathlib import Path

import cv2
import pytest
from fastapi.testclient import TestClient
from test_intake_route import AUTH, OTHER, TOKENS, project

from forma_api.main import create_app
from forma_api.model_gateway import MetaGateway

sys.path.insert(0, str(Path(__file__).parents[3] / "packages/photo_measure/tests"))
from scenes import MATERIAL, box_around, camera, rect_mm, render, texture  # noqa: E402

SHEET = rect_mm(200, 60, 280, 190)


@pytest.fixture
def client(tmp_path, monkeypatch):
    def no_provider(*_, **__):
        raise AssertionError("photo estimates never call a provider")

    monkeypatch.setattr(MetaGateway, "from_env", no_provider)
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        yield client


@pytest.fixture(scope="module")
def scene_png():
    _, h = camera(tilt_deg=20, yaw_deg=8)
    image = render(texture([(SHEET, [], MATERIAL)]), h)
    ok, data = cv2.imencode(".png", image)
    assert ok
    return data.tobytes(), box_around(h, SHEET)


def upload(client, p, data, key):
    response = client.post(
        f"/api/projects/{p['id']}/media",
        content=data,
        headers={**AUTH, "Idempotency-Key": key, "Content-Type": "image/png"},
    )
    assert response.status_code == 201, response.text
    return response.json()["media"]


def body(p, photo, outline, key="estimate-0001", stock_id="sheet-a", **extra):
    return {
        "media_id": photo["id"],
        "expected_revision_id": p["revision_id"],
        "idempotency_key": key,
        "stock_id": stock_id,
        "stock_kind": "sheet",
        "stock_material": "cardboard",
        "reference": {
            "kind": "forma_card",
            "printed_check_x_mm": 150,
            "printed_check_y_mm": 100,
            "size_tolerance_mm": 0.5,
        },
        "outline": outline.model_dump(mode="json", exclude_none=True),
        "capture": {"shape": "flat", "same_surface_as_reference": True},
        **extra,
    }


def estimate(client, p, payload, auth=AUTH):
    return client.post(
        f"/api/projects/{p['id']}/photo-estimates", json=payload, headers=auth
    )


def measurement(value=None, source="unknown", confirmed=False):
    return {"value": value, "unit": "mm", "source": source, "confirmed": confirmed}


def stock(photo_id, width, height, kind="sheet", stock_id="sheet-a"):
    return {
        "id": stock_id,
        "kind": kind,
        "material": "cardboard",
        "width_mm": width,
        "height_mm": height,
        "thickness_mm": measurement(),
        "remaining_length_mm": measurement(),
        "condition": "usable",
        "image_ids": [photo_id],
    }


def save(client, p, stocks, key):
    return client.put(
        f"/api/projects/{p['id']}/inventory",
        headers=AUTH,
        json={
            "expected_revision_id": p["revision_id"],
            "idempotency_key": key,
            "stocks": stocks,
            "user_confirmed": True,
        },
    )


def dims(record):
    return {d["stock_field"]: d for d in record["estimate"]["dimensions"]}


def test_estimate_is_local_retry_exact_and_owner_scoped(client, scene_png):
    data, outline = scene_png
    p = project(client)
    photo = upload(client, p, data, "upload-0001")
    payload = body(p, photo, outline)
    first = estimate(client, p, payload)
    assert first.status_code == 200, first.text
    record = first.json()
    assert first.headers["cache-control"] == "no-store"
    assert record["estimate"]["outcome"] == "estimate"
    assert record["estimate"]["measurement_status"] == "photo_estimate_unconfirmed"
    assert record["estimate"]["input"]["media_sha256"]
    assert abs(dims(record)["width_mm"]["value"] - 280) < 3
    again = estimate(client, p, payload).json()
    assert again["replayed"] is True and again["estimate_id"] == record["estimate_id"]
    conflict = estimate(client, p, {**payload, "stock_id": "sheet-b"})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
    assert estimate(client, p, payload, auth=OTHER).status_code == 404
    stale = estimate(
        client,
        p,
        {
            **payload,
            "idempotency_key": "estimate-0002",
            "expected_revision_id": "inventory-old",
        },
    )
    assert stale.status_code == 409
    # Nothing in the inventory changed.
    saved = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    assert saved["revision_id"] == p["revision_id"] and saved["stocks"] == []
    listed = client.get(f"/api/projects/{p['id']}/photo-estimates", headers=AUTH).json()
    assert [r["estimate_id"] for r in listed["records"]] == [record["estimate_id"]]
    assert listed["records"][0]["status"] == "current"


def test_failed_capture_explains_the_fix(client, scene_png):
    data, outline = scene_png
    p = project(client)
    photo = upload(client, p, data, "upload-0001")
    payload = body(p, photo, outline)
    payload["reference"] = {"kind": "forma_card", "size_tolerance_mm": 0.5}
    record = estimate(client, p, payload).json()
    assert record["estimate"]["outcome"] == "reference_unverified"
    assert record["estimate"]["dimensions"] == []
    assert "ruler" in record["estimate"]["request"]


def test_inventory_accepts_only_current_matching_unconfirmed_estimates(
    client, scene_png
):
    data, outline = scene_png
    p = project(client)
    photo = upload(client, p, data, "upload-0001")
    record = estimate(client, p, body(p, photo, outline)).json()
    width = dims(record)["width_mm"]["display_value"]
    height = dims(record)["height_mm"]["display_value"]
    wrong = save(
        client,
        p,
        [
            stock(
                photo["id"],
                measurement(width + 5, "photo_estimate"),
                measurement(height, "photo_estimate"),
            )
        ],
        "save-0001",
    )
    assert wrong.status_code == 422 and "sheet-a width_mm" in wrong.json()["message"]
    confirmed = save(
        client,
        p,
        [stock(photo["id"], measurement(width, "photo_estimate", True), measurement())],
        "save-0002",
    )
    assert confirmed.status_code == 422
    unlinked = stock(photo["id"], measurement(width, "photo_estimate"), measurement())
    unlinked["image_ids"] = []
    assert save(client, p, [unlinked], "save-0003").status_code == 422
    other_kind = save(
        client,
        p,
        [
            stock(
                photo["id"],
                measurement(width, "photo_estimate"),
                measurement(),
                kind="strip",
            )
        ],
        "save-0004",
    )
    assert other_kind.status_code == 422
    ok = save(
        client,
        p,
        [
            stock(
                photo["id"],
                measurement(width, "photo_estimate"),
                measurement(height, "photo_estimate"),
            )
        ],
        "save-0005",
    )
    assert ok.status_code == 200, ok.text
    saved = ok.json()["project"]["stocks"][0]
    assert saved["width_mm"] == {
        **measurement(width, "photo_estimate"),
        "evidence_ids": [],
    }
    assert saved["width_mm"]["confirmed"] is False


def test_changes_make_estimates_stale_but_keep_history(client, scene_png):
    data, outline = scene_png
    p = project(client)
    photo = upload(client, p, data, "upload-0001")
    first = estimate(client, p, body(p, photo, outline)).json()
    payload = body(p, photo, outline, key="estimate-0002")
    payload["reference"]["printed_check_x_mm"] = 149
    second = estimate(client, p, payload).json()
    assert second["estimate"]["input_digest"] != first["estimate"]["input_digest"]
    records = client.get(
        f"/api/projects/{p['id']}/photo-estimates", headers=AUTH
    ).json()["records"]
    assert [r["status"] for r in records] == ["stale", "current"]
    assert records[0]["stale_reasons"] == ["A newer estimate replaced this one."]
    # The superseded value can no longer be saved.
    old = dims(first)["width_mm"]["display_value"]
    new = dims(second)["width_mm"]["display_value"]
    if old != new:
        assert (
            save(
                client,
                p,
                [stock(photo["id"], measurement(old, "photo_estimate"), measurement())],
                "save-0001",
            ).status_code
            == 422
        )
    # Changing the material type invalidates the estimate.
    saved = save(
        client,
        p,
        [stock(photo["id"], measurement(), measurement(), kind="strip")],
        "save-0002",
    )
    assert saved.status_code == 200
    records = client.get(
        f"/api/projects/{p['id']}/photo-estimates", headers=AUTH
    ).json()["records"]
    assert records[1]["status"] == "stale"
    assert "The material type changed." in records[1]["stale_reasons"]


def test_deleted_photo_marks_estimate_stale(client, scene_png):
    data, outline = scene_png
    p = project(client)
    photo = upload(client, p, data, "upload-0001")
    estimate(client, p, body(p, photo, outline))
    deleted = client.delete(
        f"/api/projects/{p['id']}/media/{photo['id']}",
        headers={**AUTH, "Idempotency-Key": "delete-0001"},
    )
    assert deleted.status_code == 200, deleted.text
    records = client.get(
        f"/api/projects/{p['id']}/photo-estimates", headers=AUTH
    ).json()["records"]
    assert records[0]["status"] == "stale"
    assert "The photo was deleted." in records[0]["stale_reasons"]


def test_project_delete_purges_estimates(client, scene_png, tmp_path):
    data, outline = scene_png
    p = project(client)
    photo = upload(client, p, data, "upload-0001")
    estimate(client, p, body(p, photo, outline))
    deleted = client.delete(
        f"/api/projects/{p['id']}", headers={**AUTH, "Idempotency-Key": "delete-0001"}
    )
    assert deleted.status_code == 200, deleted.text
    with sqlite3.connect(tmp_path / "projects.sqlite3") as c:
        assert c.execute("SELECT COUNT(*) FROM photo_estimates").fetchone()[0] == 0
        assert (
            c.execute(
                "SELECT COUNT(*) FROM requests WHERE scope LIKE '%photo-estimate'"
            ).fetchone()[0]
            == 0
        )


def test_reference_card_is_public_and_true_size(client):
    response = client.get("/api/photo-reference-card.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert 'width="200mm"' in response.text


def test_removing_a_stock_retires_its_estimates_for_good(client, scene_png):
    data, outline = scene_png
    p = project(client)
    photo = upload(client, p, data, "upload-0001")
    record = estimate(client, p, body(p, photo, outline)).json()
    width = dims(record)["width_mm"]["display_value"]
    saved = save(
        client,
        p,
        [stock(photo["id"], measurement(width, "photo_estimate"), measurement())],
        "save-0001",
    )
    assert saved.status_code == 200
    p = saved.json()["project"]
    other = stock(photo["id"], measurement(), measurement(), stock_id="sheet-b")
    dropped = save(client, p, [other], "save-0002")
    assert dropped.status_code == 200
    p = dropped.json()["project"]
    # Re-adding the same ID with the same photo cannot revive the estimate.
    again = save(
        client,
        p,
        [
            other,
            stock(photo["id"], measurement(width, "photo_estimate"), measurement()),
        ],
        "save-0003",
    )
    assert again.status_code == 422
    records = client.get(
        f"/api/projects/{p['id']}/photo-estimates", headers=AUTH
    ).json()["records"]
    assert records[0]["removed"] is True and records[0]["status"] == "stale"


def test_failed_retry_does_not_supersede_a_usable_estimate(client, scene_png):
    data, outline = scene_png
    p = project(client)
    photo = upload(client, p, data, "upload-0001")
    estimate(client, p, body(p, photo, outline))
    failed = body(p, photo, outline, key="estimate-0002")
    failed["capture"]["shape"] = "curved"
    assert (
        estimate(client, p, failed).json()["estimate"]["outcome"] == "unsupported_shape"
    )
    records = client.get(
        f"/api/projects/{p['id']}/photo-estimates", headers=AUTH
    ).json()["records"]
    assert records[0]["status"] == "current"
