"""Recognised-item cards: stable identity, corrections, links and no false support."""

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_intake_route import AUTH, OTHER, TOKENS, project

from forma_api.main import create_app
from forma_api.model_gateway import MetaGateway


@pytest.fixture
def client(tmp_path, monkeypatch):
    def no_provider(*_, **__):
        raise AssertionError("saving item cards never calls a provider")

    monkeypatch.setattr(MetaGateway, "from_env", no_provider)
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        yield client


def photo(client, p, key="upload-0001"):
    ok, data = cv2.imencode(".png", np.full((60, 80, 3), 200, np.uint8))
    assert ok
    response = client.post(
        f"/api/projects/{p['id']}/media",
        content=data.tobytes(),
        headers={**AUTH, "Idempotency-Key": key, "Content-Type": "image/png"},
    )
    assert response.status_code == 201, response.text
    return response.json()["media"]["id"]


def item(item_id, media_id, **extra):
    return {
        "id": item_id,
        "name": "Plastic bottle",
        "identity": {"outcome": "catalog", "category_id": "plastic_bottle"},
        "identity_source": "muse_suggestion",
        "media_id": media_id,
        "box": {"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.9},
        "box_source": "muse_approximate",
        "visibility": "partial",
        **extra,
    }


def put(client, p, items, key, revision=None, auth=AUTH):
    return client.put(
        f"/api/projects/{p['id']}/recognized-items",
        headers=auth,
        json={"expected_revision": revision, "idempotency_key": key, "items": items},
    )


def get(client, p, auth=AUTH):
    return client.get(f"/api/projects/{p['id']}/recognized-items", headers=auth)


def stock(stock_id, kind="sheet", material="cardboard"):
    unknown = {"value": None, "unit": "mm", "source": "unknown", "confirmed": False}
    return {
        "id": stock_id,
        "kind": kind,
        "material": material,
        "width_mm": unknown,
        "height_mm": unknown,
        "thickness_mm": unknown,
        "remaining_length_mm": unknown,
        "condition": "uncertain",
    }


def save_stocks(client, p, stocks, key):
    response = client.put(
        f"/api/projects/{p['id']}/inventory",
        headers=AUTH,
        json={
            "expected_revision_id": p["revision_id"],
            "idempotency_key": key,
            "stocks": stocks,
            "user_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["project"]


def test_corrections_and_separate_instances_survive_save_and_reload(client):
    p = project(client)
    media = photo(client, p)
    assert get(client, p).json() == {
        "project_id": p["id"],
        "revision": None,
        "catalog_version": "material-catalog-v1",
        "items": [],
        "problems": [],
        "replayed": False,
    }
    two = [
        item("bottle-a--1", media),
        item(
            "bottle-b--2",
            media,
            box={"x1": 0.5, "y1": 0.1, "x2": 0.8, "y2": 0.9},
        ),
    ]
    first = put(client, p, two, "items-0001")
    assert first.status_code == 200, first.text
    revision = first.json()["revision"]

    corrected = [
        {
            **two[0],
            "name": "Juice bottle",
            "identity": {"outcome": "catalog", "category_id": "food_container"},
            "identity_source": "user",
            "user_fields": ["identity", "name"],
        },
        two[1],
    ]
    second = put(client, p, corrected, "items-0002", revision)
    assert second.status_code == 200, second.text
    reloaded = get(client, p).json()
    assert [i["id"] for i in reloaded["items"]] == ["bottle-a--1", "bottle-b--2"]
    assert reloaded["items"][0]["name"] == "Juice bottle"
    assert reloaded["items"][0]["identity"]["category_id"] == "food_container"
    assert reloaded["items"][0]["user_fields"] == ["identity", "name"]
    assert reloaded["revision"] == second.json()["revision"] != revision

    # A stale writer cannot overwrite the corrections.
    stale = put(client, p, two, "items-0003", revision)
    assert stale.status_code == 409
    # An exact retry replays; the same key with another body conflicts.
    again = put(client, p, corrected, "items-0002", revision)
    assert again.json()["replayed"] is True
    assert put(client, p, two, "items-0002", revision).status_code == 409


def test_unsupported_items_never_link_to_fabrication_stock(client):
    p = project(client)
    p = save_stocks(client, p, [stock("sheet-a")], "save-0001")
    bottle = item("bottle--1", None, box=None, box_source=None, stock_id="sheet-a")
    refused = put(client, p, [bottle], "items-0001")
    assert refused.status_code == 422
    assert "build rules are not available" in refused.text
    unsure = {
        **bottle,
        "identity": {"outcome": "uncertain", "alternatives": ["corrugated_cardboard"]},
    }
    assert put(client, p, [unsure], "items-0002").status_code == 422
    # Recognised inventory stays available without a link.
    kept = put(client, p, [{**bottle, "stock_id": None}], "items-0003")
    assert kept.status_code == 200, kept.text
    cardboard = {
        **bottle,
        "id": "box--2",
        "identity": {"outcome": "catalog", "category_id": "corrugated_cardboard"},
    }
    linked = put(
        client,
        p,
        [{**bottle, "stock_id": None}, cardboard],
        "items-0004",
        kept.json()["revision"],
    )
    assert linked.status_code == 200, linked.text
    # A new tape item cannot back a sheet.
    tape = {
        **cardboard,
        "id": "tape--3",
        "identity": {"outcome": "catalog", "category_id": "masking_tape"},
    }
    assert (
        put(client, p, [tape], "items-0005", linked.json()["revision"]).status_code
        == 422
    )


def test_broken_links_are_reported_not_hidden(client):
    p = project(client)
    media = photo(client, p)
    p = save_stocks(client, p, [stock("sheet-a")], "save-0001")
    cardboard = item(
        "box--1",
        media,
        identity={"outcome": "catalog", "category_id": "corrugated_cardboard"},
        stock_id="sheet-a",
    )
    assert put(client, p, [cardboard], "items-0001").status_code == 200
    save_stocks(client, p, [stock("sheet-b")], "save-0002")
    deleted = client.request(
        "DELETE",
        f"/api/projects/{p['id']}/media/{media}",
        headers={**AUTH, "Idempotency-Key": "delete-0001"},
    )
    assert deleted.status_code in (200, 204), deleted.text
    problems = {x["problem"] for x in get(client, p).json()["problems"]}
    assert problems == {
        "The photo was deleted.",
        "The linked material is no longer in the saved inventory.",
    }


def test_items_are_owner_scoped_and_validated(client):
    p = project(client)
    assert get(client, p, auth=OTHER).status_code == 404
    assert put(client, p, [], "items-0001", auth=OTHER).status_code == 404
    missing = put(client, p, [item("bottle--1", "no-such-photo")], "items-0002")
    assert missing.status_code == 404
    forced = item("thing--1", None, box=None, box_source=None)
    forced["identity"] = {"outcome": "uncertain", "category_id": "felt"}
    assert put(client, p, [forced], "items-0003").status_code == 422
    dupes = [item("x--1", None, box=None, box_source=None)] * 2
    assert put(client, p, dupes, "items-0004").status_code == 422


def test_a_correction_keeps_a_saved_link_and_reports_the_mismatch(client):
    p = project(client)
    p = save_stocks(client, p, [stock("sheet-a")], "save-0001")
    cardboard = item(
        "box--1",
        None,
        box=None,
        box_source=None,
        identity={"outcome": "catalog", "category_id": "corrugated_cardboard"},
        stock_id="sheet-a",
    )
    first = put(client, p, [cardboard], "items-0001")
    assert first.status_code == 200, first.text
    corrected = {
        **cardboard,
        "identity": {"outcome": "catalog", "category_id": "plastic_sheet"},
        "identity_source": "user",
        "user_fields": ["identity"],
    }
    second = put(client, p, [corrected], "items-0002", first.json()["revision"])
    assert second.status_code == 200, second.text
    assert get(client, p).json()["problems"] == [
        {
            "item_id": "box--1",
            "problem": "The linked material no longer matches what this item is.",
        }
    ]
    # A new mismatched link is still refused.
    other = {**corrected, "id": "box--2"}
    assert (
        put(
            client,
            p,
            [{**corrected, "stock_id": None}, other],
            "items-0003",
            second.json()["revision"],
        ).status_code
        == 422
    )
