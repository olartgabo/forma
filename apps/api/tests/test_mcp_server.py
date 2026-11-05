"""The MCP endpoint forwards to the REST routes under the caller's credential."""

import base64

import pytest
from fastapi.testclient import TestClient
from test_media import inventory, photo

from forma_api.main import create_app

TOKENS = {"alice": "a" * 40, "bob": "b" * 40}
ACCEPT = {"Accept": "application/json, text/event-stream"}
AUTH = {**ACCEPT, "Authorization": "Bearer " + TOKENS["alice"]}
OTHER = {**ACCEPT, "Authorization": "Bearer " + TOKENS["bob"]}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        yield client


def rpc(client, method, params=None, headers=AUTH):
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/api/mcp", json=body, headers=headers)


def call(client, name, arguments, headers=AUTH):
    response = rpc(
        client, "tools/call", {"name": name, "arguments": arguments}, headers
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def create(client, headers=AUTH, key="project-001"):
    result = call(
        client,
        "create_project",
        {"goal": "phone stand", "idempotency_key": key},
        headers,
    )
    assert not result["isError"], result
    return result["structuredContent"]["project"]


@pytest.mark.parametrize(
    "headers",
    [ACCEPT, {**ACCEPT, "Authorization": "Bearer " + "c" * 31}],
    ids=["missing", "short"],
)
def test_rejects_requests_without_a_usable_token(client, headers):
    response = rpc(client, "tools/list", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["code"] == "forbidden"


def test_unconfigured_token_is_an_isolated_guest_owner(client):
    guest = {**ACCEPT, "Authorization": "Bearer " + "c" * 40}
    create(client, headers=guest)
    listed = call(client, "list_projects", {}, AUTH)
    assert listed["structuredContent"]["projects"] == []


def test_lists_only_upload_and_read_tools(client):
    response = rpc(client, "tools/list")
    assert response.status_code == 200, response.text
    assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
        "list_projects",
        "get_project",
        "create_project",
        "list_photos",
        "upload_photo",
        "update_inventory",
    }


def test_creates_and_reads_projects_for_the_caller_only(client):
    project = create(client)
    assert create(client)["id"] == project["id"]
    listed = call(client, "list_projects", {})["structuredContent"]
    assert [p["id"] for p in listed["projects"]] == [project["id"]]
    got = call(client, "get_project", {"project_id": project["id"]})
    assert got["structuredContent"] == project

    foreign = call(client, "get_project", {"project_id": project["id"]}, OTHER)
    assert foreign["isError"]
    assert "404" in foreign["content"][0]["text"]
    assert call(client, "list_projects", {}, OTHER)["structuredContent"] == {
        "projects": [],
        "next_cursor": None,
    }


def test_uploads_a_photo_and_links_it_in_confirmed_inventory(client):
    project = create(client)
    uploaded = call(
        client,
        "upload_photo",
        {
            "project_id": project["id"],
            "content_type": "image/png",
            "image_base64": base64.b64encode(photo()).decode(),
            "idempotency_key": "upload-001",
        },
    )
    assert not uploaded["isError"], uploaded
    media = uploaded["structuredContent"]
    assert (media["project_id"], media["width_px"]) == (project["id"], 12)
    listed = call(client, "list_photos", {"project_id": project["id"]})
    assert [m["id"] for m in listed["structuredContent"]["media"]] == [media["id"]]

    body = inventory(project, image_ids=[media["id"]])
    updated = call(
        client,
        "update_inventory",
        {"project_id": project["id"], "inventory": body},
    )
    assert not updated["isError"], updated
    saved = updated["structuredContent"]["project"]
    assert saved["stocks"][0]["image_ids"] == [media["id"]]
    assert saved["revision_id"] != project["revision_id"]

    stale = call(
        client,
        "update_inventory",
        {
            "project_id": project["id"],
            "inventory": {**body, "idempotency_key": "x" * 8},
        },
    )
    assert stale["isError"]
    assert "409 (stale_version" in stale["content"][0]["text"]


def test_inventory_requires_user_confirmation(client):
    project = create(client)
    body = {**inventory(project), "user_confirmed": False}
    result = call(
        client, "update_inventory", {"project_id": project["id"], "inventory": body}
    )
    assert result["isError"]
    assert (
        call(client, "get_project", {"project_id": project["id"]})["structuredContent"]
        == project
    )


@pytest.mark.parametrize(
    ("encoded", "message"),
    [
        ("not base64!", "image_base64 is not valid base64"),
        (base64.b64encode(b"not an image").decode(), "FORMA API returned"),
    ],
)
def test_rejects_invalid_photo_uploads(client, encoded, message):
    project = create(client)
    result = call(
        client,
        "upload_photo",
        {
            "project_id": project["id"],
            "content_type": "image/png",
            "image_base64": encoded,
            "idempotency_key": "upload-001",
        },
    )
    assert result["isError"]
    assert message in result["content"][0]["text"]
    assert call(client, "list_photos", {"project_id": project["id"]})[
        "structuredContent"
    ] == {"media": []}


def test_serves_mcp_across_repeated_app_lifespans(tmp_path):
    app = create_app(tmp_path, TOKENS)
    for _ in range(2):
        with TestClient(app) as client:
            assert rpc(client, "tools/list").status_code == 200
