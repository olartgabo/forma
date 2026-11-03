"""Provider dispatch boundary tests: generated images and injected runtime only."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from test_media import photo, upload
from test_plans import AUTH, OTHER, TOKENS
from test_projects import create

from forma_api import design_runtime, muse_construction
from forma_api.design_context import ResolvedDesignContext, StaticDesignContextResolver
from forma_api.main import create_app
from forma_api.model_gateway import GatewayError
from forma_api.routes import muse_construction as route


@pytest.fixture
def setup(tmp_path, monkeypatch):
    calls = []
    factory_calls = []

    def factory():
        factory_calls.append(True)
        return object()

    def run(gateway, **kwargs):
        calls.append(kwargs)
        p = kwargs["project"]
        return muse_construction.MuseConstructionResult(
            project_id=p.id,
            inventory_revision_id=p.revision_id,
            status="needs_measurement",
            candidates=(),
            questions=("Measure sheet thickness.",),
            diagnostics=design_runtime.DesignDiagnostics(
                status="ok",
                model="test-runtime",
                elapsed_ms=1,
                model_rounds=1,
                tool_executions=0,
            ),
        )

    monkeypatch.setattr(design_runtime, "default_gateway_factory", factory)
    monkeypatch.setattr(muse_construction, "generate_muse_construction", run)
    monkeypatch.setattr(
        route.design_context,
        "default_context_resolver",
        lambda: StaticDesignContextResolver(None),
    )
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        p = create(client)
        yield client, p, calls, factory_calls, tmp_path, monkeypatch


def body(p, **changes):
    return {
        "expected_revision_id": p["revision_id"],
        "idempotency_key": "construction-001",
        "provider_context_consented": True,
        **changes,
    }


def post(client, p, payload=None, auth=AUTH):
    return client.post(
        f"/api/projects/{p['id']}/construction/propose",
        headers=auth,
        json=payload or body(p),
    )


def receipts(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        return connection.execute(
            "SELECT response FROM requests WHERE scope LIKE '%:construction-proposal'"
        ).fetchall()


def test_consented_saved_context_photo_replay_and_no_physical_writes(setup):
    client, p, calls, factories, directory, _ = setup
    media = upload(client, p).json()["media"]
    payload = body(p, media_id=media["id"], provider_transfer_consented=True)
    first = post(client, p, payload)
    assert first.status_code == 200, first.text
    assert first.headers["Cache-Control"] == "no-store"
    assert calls[0]["project"].goal == p["goal"]
    assert calls[0]["image"].consented is True
    assert calls[0]["image"].mime == "image/png"
    assert calls[0]["image"].data.startswith(b"\x89PNG")
    assert post(client, p, payload).json()["replayed"] is True
    assert len(calls) == len(factories) == 1
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        for table in (
            "plans",
            "progress_events",
            "progress_evidence",
            "progress_material",
        ):
            assert (
                connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == 0
            )
    assert client.get(f"/api/projects/{p['id']}", headers=AUTH).json() == p
    assert "data:image" not in receipts(directory)[0][0]


@pytest.mark.parametrize(
    "change,code",
    [
        ({"provider_context_consented": False}, 422),
        ({"expected_revision_id": "stale"}, 409),
        ({"stocks": []}, 422),
        ({"provider_context_consented": "true"}, 422),
    ],
)
def test_preconditions_no_dispatch(setup, change, code):
    client, p, calls, factories, directory, _ = setup
    response = post(client, p, body(p, **change))
    assert response.status_code == code
    assert not calls and not factories and not receipts(directory)


def test_auth_foreign_photo_and_photo_consent(setup):
    client, p, calls, factories, _, _ = setup
    assert post(client, p, auth={}).status_code == 401
    assert post(client, p, auth=OTHER).status_code == 404
    second = create(client, "project-other")
    media = upload(client, second).json()["media"]
    assert (
        post(
            client, p, body(p, media_id=media["id"], provider_transfer_consented=True)
        ).status_code
        == 404
    )
    media = upload(client, p).json()["media"]
    assert (
        post(client, p, body(p, media_id=media["id"])).json()["code"]
        == "consent_required"
    )
    assert not calls and not factories


def test_media_type_and_size_before_dispatch(setup):
    client, p, calls, factories, directory, _ = setup
    media = upload(client, p, body=photo("WEBP"), content_type="image/webp").json()[
        "media"
    ]
    payload = body(p, media_id=media["id"], provider_transfer_consented=True)
    assert post(client, p, payload).status_code == 415
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        connection.execute(
            "UPDATE media SET content_type=?, body=? WHERE id=?",
            ("image/png", b"x" * 5_000_001, media["id"]),
        )
    assert post(client, p, payload).status_code == 413
    assert not calls and not factories


def test_changed_key_payload_or_context_rejected_without_second_dispatch(setup):
    client, p, calls, _, _, monkeypatch = setup
    assert post(client, p).status_code == 200
    assert post(client, p, body(p, user_notes="different")).status_code == 409
    monkeypatch.setattr(
        route.design_context,
        "default_context_resolver",
        lambda: StaticDesignContextResolver(
            ResolvedDesignContext.missing("Changed context")
        ),
    )
    assert post(client, p).status_code == 409
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        GatewayError("timeout"),
        GatewayError("network_error"),
        GatewayError("budget_exhausted"),
        RuntimeError("SECRET/raw provider response"),
    ],
)
def test_unknown_outcome_blocks_same_and_new_keys_and_redacts(setup, error):
    client, p, _, factories, directory, monkeypatch = setup

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(muse_construction, "generate_muse_construction", fail)
    response = post(client, p)
    assert response.status_code == 409
    assert response.json()["code"] == "generation_outcome_unknown"
    assert "SECRET" not in response.text
    for key in ("construction-001", "construction-new"):
        replay = post(client, p, body(p, idempotency_key=key))
        assert replay.status_code == 409
        assert replay.json()["code"] == "generation_outcome_unknown"
    assert len(factories) == 1
    assert json.loads(receipts(directory)[0][0])["uncertain"] is True


def test_pre_dispatch_configuration_failure_releases_claim(setup):
    client, p, _, _, directory, monkeypatch = setup

    def bad_factory():
        raise ValueError("SECRET api key")

    monkeypatch.setattr(design_runtime, "default_gateway_factory", bad_factory)
    result = post(client, p)
    assert result.status_code == 503
    assert "SECRET" not in result.text
    assert not receipts(directory)


def test_concurrent_new_and_same_keys_do_not_duplicate_dispatch(setup):
    client, p, _, factories, _, monkeypatch = setup
    original = muse_construction.generate_muse_construction
    entered, finish = Event(), Event()

    def waiting(*args, **kwargs):
        entered.set()
        assert finish.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(muse_construction, "generate_muse_construction", waiting)
    with ThreadPoolExecutor() as executor:
        future = executor.submit(post, client, p)
        assert entered.wait(5)
        try:
            for key in ("construction-001", "construction-new"):
                response = post(client, p, body(p, idempotency_key=key))
                assert response.status_code == 409
                assert response.json()["code"] == "generation_in_progress"
        finally:
            finish.set()
        assert future.result().status_code == 200
    assert len(factories) == 1


@pytest.mark.parametrize("mutation", ["inventory", "photo", "active"])
def test_post_dispatch_race_rejects_result_and_retains_dispatch_receipt(
    setup, mutation
):
    client, p, _, _, directory, monkeypatch = setup
    media = upload(client, p).json()["media"]
    original = muse_construction.generate_muse_construction

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        with sqlite3.connect(directory / "projects.sqlite3") as connection:
            if mutation == "photo":
                connection.execute("DELETE FROM media WHERE id=?", (media["id"],))
            else:
                changed = dict(p)
                changed[
                    "revision_id" if mutation == "inventory" else "active_version_id"
                ] = "changed-version"
                connection.execute(
                    "UPDATE projects SET body=? WHERE id=?",
                    (json.dumps(changed), p["id"]),
                )
        return result

    monkeypatch.setattr(muse_construction, "generate_muse_construction", mutate)
    response = post(
        client, p, body(p, media_id=media["id"], provider_transfer_consented=True)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "generation_outcome_unknown"
    receipt = json.loads(receipts(directory)[0][0])
    assert receipt["uncertain"] is True
    assert (
        receipt["error_code"]
        == {"photo": "not_found", "inventory": "stale_version", "active": "blocked"}[
            mutation
        ]
    )


def test_context_race_rejects_result(setup):
    client, p, _, _, directory, monkeypatch = setup
    contexts = iter(
        [
            ResolvedDesignContext.missing("Before"),
            ResolvedDesignContext.missing("After"),
        ]
    )
    monkeypatch.setattr(
        route.design_context,
        "default_context_resolver",
        lambda: lambda *_: next(contexts),
    )
    response = post(client, p)
    assert response.status_code == 409
    assert response.json()["code"] == "generation_outcome_unknown"
    receipt = json.loads(receipts(directory)[0][0])
    assert receipt["uncertain"] is True
    assert receipt["error_code"] == "stale_version"


@pytest.mark.parametrize("failure", ["context_reload", "result_serialization"])
def test_post_dispatch_unexpected_failure_explicitly_preserves_request_identity(
    setup, failure
):
    client, p, _, factories, directory, monkeypatch = setup
    if failure == "context_reload":
        count = 0

        def resolve(*_):
            nonlocal count
            count += 1
            if count > 1:
                raise RuntimeError("SECRET server configuration path")
            return ResolvedDesignContext.missing("Missing process")

        monkeypatch.setattr(
            route.design_context, "default_context_resolver", lambda: resolve
        )
    else:

        def serialize(*_, **__):
            raise RuntimeError("SECRET result storage details")

        monkeypatch.setattr(
            muse_construction.MuseConstructionResult, "model_dump_json", serialize
        )
    response = post(client, p)
    assert response.status_code == 409
    assert response.json()["code"] == "generation_outcome_unknown"
    assert "SECRET" not in response.text
    receipt = json.loads(receipts(directory)[0][0])
    assert receipt["uncertain"] is True
    assert receipt["error_code"] == "result_not_confirmed"
    # Restore context resolution so an explicit original-request retry reaches
    # the durable receipt rather than initiating another provider dispatch.
    monkeypatch.setattr(
        route.design_context,
        "default_context_resolver",
        lambda: StaticDesignContextResolver(None),
    )
    replay = post(client, p, body(p, idempotency_key="construction-new"))
    assert replay.json()["code"] == "generation_outcome_unknown"
    assert len(factories) == 1


@pytest.mark.parametrize("during_call", [False, True])
def test_project_deletion_purges_proposal_receipts_without_resurrection(
    setup, during_call
):
    client, p, _, _, directory, monkeypatch = setup

    def delete():
        result = client.delete(
            f"/api/projects/{p['id']}",
            headers={**AUTH, "Idempotency-Key": "delete-construction-project"},
        )
        assert result.status_code == 200

    if during_call:
        original = muse_construction.generate_muse_construction

        def run(*args, **kwargs):
            result = original(*args, **kwargs)
            delete()
            return result

        monkeypatch.setattr(muse_construction, "generate_muse_construction", run)
        response = post(client, p)
        assert response.status_code == 409
        assert response.json()["code"] == "generation_outcome_unknown"
    else:
        assert post(client, p).status_code == 200
        delete()
    assert not receipts(directory)
