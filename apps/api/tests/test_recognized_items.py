"""Recognised-item cards: stable identity, corrections, links and no false support."""

import json
import sqlite3

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_intake_route import AUTH, OTHER, TOKENS, project

from forma_api.main import create_app
from forma_api.model_gateway import MetaGateway


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path


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
        "conflicts": [],
        "inventory_confirmed": False,
        "inventory_revision_id": p["revision_id"],
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


def confirmed(client, p):
    return client.get(f"/api/projects/{p['id']}", headers=AUTH).json()[
        "inventory_confirmed"
    ]


def readiness_text(client, p):
    response = client.get(f"/api/projects/{p['id']}/designs/readiness", headers=AUTH)
    assert response.status_code == 200, response.text
    return " ".join(response.json()["missing_inputs"])


def linked_cardboard(client, key="items-0101"):
    p = project(client)
    p = save_stocks(client, p, [stock("sheet-a")], "save-0101")
    cardboard = item(
        "box--1",
        None,
        box=None,
        box_source=None,
        identity={"outcome": "catalog", "category_id": "corrugated_cardboard"},
        stock_id="sheet-a",
    )
    first = put(client, p, [cardboard], key)
    assert first.status_code == 200, first.text
    assert first.json()["inventory_confirmed"] is True
    return p, cardboard, first.json()["revision"]


def bottle(cardboard):
    return {
        **cardboard,
        "identity": {"outcome": "catalog", "category_id": "plastic_bottle"},
        "identity_source": "user",
        "user_fields": ["identity"],
    }


def test_a_contradicting_correction_withdraws_confirmation_until_reconciled(client):
    p, cardboard, revision = linked_cardboard(client)
    corrected = put(client, p, [bottle(cardboard)], "items-0102", revision)
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert body["inventory_confirmed"] is False
    [conflict] = body["conflicts"]
    assert conflict["stock_id"] == "sheet-a" and "Plastic bottle" in conflict["message"]
    # Every design and fabrication gate reads this confirmation.
    assert confirmed(client, p) is False
    assert "Confirm the saved inventory." in readiness_text(client, p)
    # Saving the same contradicted stock again does not confirm it.
    current = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    again = save_stocks(client, current, [stock("sheet-a")], "save-0102")
    assert again["inventory_confirmed"] is False
    # Changing the item back restores the earlier confirmation.
    back = put(client, p, [cardboard], "items-0103", body["revision"])
    assert back.status_code == 200, back.text
    assert back.json()["conflicts"] == []
    assert back.json()["inventory_confirmed"] is True
    assert confirmed(client, p) is True


def test_removing_the_contradicted_material_reconciles(client):
    p, cardboard, revision = linked_cardboard(client)
    body = put(client, p, [bottle(cardboard)], "items-0202", revision).json()
    current = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    removed = save_stocks(client, current, [stock("sheet-b")], "save-0202")
    assert removed["inventory_confirmed"] is True
    unlinked = put(
        client,
        p,
        [{**bottle(cardboard), "stock_id": None}],
        "items-0203",
        body["revision"],
    )
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["inventory_confirmed"] is True


def test_retyping_material_and_item_in_one_save_ends_confirmed(client):
    # The inventory saves first, while the stored item still says cardboard.
    p, cardboard, revision = linked_cardboard(client)
    current = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    retyped = save_stocks(
        client, current, [stock("sheet-a", material="paperboard")], "save-0302"
    )
    assert retyped["inventory_confirmed"] is False
    card = {
        **cardboard,
        "identity": {"outcome": "catalog", "category_id": "cardstock"},
        "identity_source": "user",
        "user_fields": ["identity"],
    }
    saved = put(client, p, [card], "items-0302", revision)
    assert saved.status_code == 200, saved.text
    assert saved.json()["conflicts"] == []
    assert confirmed(client, p) is True


def test_unlinking_without_a_hold_leaves_confirmation_as_saved(client):
    p = project(client)
    p = save_stocks(client, p, [stock("sheet-a")], "save-0401")
    tape = item(
        "box--1",
        None,
        box=None,
        box_source=None,
        identity={"outcome": "catalog", "category_id": "corrugated_cardboard"},
        stock_id="sheet-a",
    )
    first = put(client, p, [tape], "items-0401")
    assert first.json()["inventory_confirmed"] is True
    second = put(
        client, p, [{**tape, "stock_id": None}], "items-0402", first.json()["revision"]
    )
    # Unlinking with no hold leaves confirmation exactly as saved.
    assert second.json()["inventory_confirmed"] is True


def test_a_new_contradiction_is_refused_while_a_build_is_active(client, data_dir):
    p, cardboard, revision = linked_cardboard(client)
    with sqlite3.connect(data_dir / "projects.sqlite3") as connection:
        (body,) = connection.execute(
            "SELECT body FROM projects WHERE id=?", (p["id"],)
        ).fetchone()
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?",
            (
                json.dumps({**json.loads(body), "active_version_id": "version-1"}),
                p["id"],
            ),
        )
    refused = put(client, p, [bottle(cardboard)], "items-0502", revision)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "blocked"
    assert confirmed(client, p) is True


def test_withdrawal_issues_a_new_inventory_revision(client):
    # Work started against the earlier revision is refused as stale.
    p, cardboard, revision = linked_cardboard(client)
    before = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()["revision_id"]
    body = put(client, p, [bottle(cardboard)], "items-0602", revision).json()
    after = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()["revision_id"]
    assert after != before and body["inventory_revision_id"] == after
    back = put(client, p, [cardboard], "items-0603", body["revision"]).json()
    assert back["inventory_revision_id"] not in (before, after)


def test_contradictions_saved_before_reconciliation_are_held_at_startup(
    client, data_dir
):
    p, cardboard, revision = linked_cardboard(client)
    # Simulate an earlier build: a saved contradiction, still confirmed.
    with sqlite3.connect(data_dir / "projects.sqlite3") as connection:
        (body,) = connection.execute(
            "SELECT body FROM recognized_items WHERE project_id=?", (p["id"],)
        ).fetchone()
        stored = json.loads(body)
        stored["items"] = [bottle(cardboard)]
        connection.execute(
            "UPDATE recognized_items SET body=? WHERE project_id=?",
            (json.dumps(stored), p["id"]),
        )
    assert confirmed(client, p) is True
    with TestClient(create_app(data_dir, TOKENS)) as restarted:
        project_now = restarted.get(f"/api/projects/{p['id']}", headers=AUTH).json()
        assert project_now["inventory_confirmed"] is False
        # Changing the item back restores it.
        reread = restarted.get(
            f"/api/projects/{p['id']}/recognized-items", headers=AUTH
        ).json()
        back = put(restarted, p, [cardboard], "items-0702", reread["revision"])
        assert back.json()["inventory_confirmed"] is True


def test_deleting_or_unlinking_the_card_does_not_release_the_material(client):
    p, cardboard, revision = linked_cardboard(client)
    body = put(client, p, [bottle(cardboard)], "items-0802", revision).json()
    gone = put(client, p, [], "items-0803", body["revision"])
    assert gone.status_code == 200, gone.text
    assert gone.json()["inventory_confirmed"] is False
    [hold] = gone.json()["conflicts"]
    assert hold["stock_id"] == "sheet-a" and hold["item_id"] is None
    assert "Remove it or change its type" in hold["message"]
    # Re-saving the same material does not release it either.
    current = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    assert (
        save_stocks(client, current, [stock("sheet-a")], "save-0803")[
            "inventory_confirmed"
        ]
        is False
    )
    # Retyping the material is an explicit reconciliation.
    current = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    retyped = save_stocks(
        client, current, [stock("sheet-a", material="paperboard")], "save-0804"
    )
    assert retyped["inventory_confirmed"] is True


def test_earlier_contradictions_in_an_active_build_are_held_at_startup(
    client, data_dir
):
    p, cardboard, revision = linked_cardboard(client)
    with sqlite3.connect(data_dir / "projects.sqlite3") as connection:
        (items_body,) = connection.execute(
            "SELECT body FROM recognized_items WHERE project_id=?", (p["id"],)
        ).fetchone()
        stored = json.loads(items_body)
        stored["items"] = [bottle(cardboard)]
        connection.execute(
            "UPDATE recognized_items SET body=? WHERE project_id=?",
            (json.dumps(stored), p["id"]),
        )
        (body,) = connection.execute(
            "SELECT body FROM projects WHERE id=?", (p["id"],)
        ).fetchone()
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?",
            (
                json.dumps({**json.loads(body), "active_version_id": "version-1"}),
                p["id"],
            ),
        )
    with TestClient(create_app(data_dir, TOKENS)) as restarted:
        now = restarted.get(f"/api/projects/{p['id']}", headers=AUTH).json()
        # The build stays active; its stock is no longer confirmed for repair.
        assert now["active_version_id"] == "version-1"
        assert now["inventory_confirmed"] is False
