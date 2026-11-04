"""Provider dispatch boundary tests: generated images and injected runtime only."""

import hashlib
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
from forma_api.model_gateway import GatewayError, Trace
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

    monkeypatch.setattr(muse_construction, "default_gateway_factory", factory)
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


def replacement_source(
    directory, p, key="original-unknown", digest="b" * 64, saved=None
):
    saved = (
        saved
        or '{"pending":true,"uncertain":true,"error_code":"timeout","evidence":{"usage":null}}'
    )
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        connection.execute(
            "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
            ("alice", p["id"] + ":construction-proposal", key, digest, saved),
        )
    return dict(
        expected_revision_id=p["revision_id"],
        original_idempotency_key=key,
        original_digest=digest,
        replacement_idempotency_key="replacement-one",
        acknowledge_unknown=True,
    )


def authorize(client, p, payload, auth=AUTH):
    return client.post(
        f"/api/projects/{p['id']}/construction/replacement-authorizations",
        headers=auth,
        json=payload,
    )


def request_rows(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        return connection.execute(
            "SELECT owner, scope, key, digest, response FROM requests WHERE scope LIKE '%:construction-proposal' ORDER BY rowid"
        ).fetchall()


def test_explicit_replacement_is_audited_one_key_only_and_preserves_original_bytes(
    setup,
):
    client, p, calls, factories, directory, _ = setup
    payload = replacement_source(directory, p)
    original = request_rows(directory)
    response = authorize(client, p, payload)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert not response.json()["replayed"]
    assert request_rows(directory) == original
    assert not calls and not factories
    replay = authorize(client, p, payload)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert (
        authorize(
            client, p, payload | {"replacement_idempotency_key": "replacement-other"}
        ).status_code
        == 409
    )
    assert post(client, p).json()["code"] == "generation_outcome_unknown"
    sent = post(client, p, body(p, idempotency_key="replacement-one"))
    assert sent.status_code == 200, sent.text
    assert len(calls) == len(factories) == 1
    assert request_rows(directory)[0] == original[0]
    assert post(client, p, body(p, idempotency_key="replacement-one")).json()[
        "replayed"
    ]
    assert len(calls) == len(factories) == 1
    assert (
        post(client, p, body(p, idempotency_key="replacement-other")).status_code == 200
    )
    listed = client.get(
        f"/api/projects/{p['id']}/construction/receipts", headers=AUTH
    ).json()["receipts"]
    by_key = {r["idempotency_key"]: r for r in listed}
    assert by_key["original-unknown"]["state"] == "unknown"
    assert (
        by_key["original-unknown"]["replacement_idempotency_key"] == "replacement-one"
    )
    assert by_key["replacement-one"]["replaces_idempotency_key"] == "original-unknown"


@pytest.mark.parametrize(
    "change,status",
    [
        ({"acknowledge_unknown": False}, 422),
        ({"acknowledge_unknown": "true"}, 422),
        ({"expected_revision_id": "old-revision"}, 409),
        ({"original_digest": "a" * 64}, 409),
        ({"original_idempotency_key": "missing-source"}, 404),
        ({"replacement_idempotency_key": "original-unknown"}, 422),
    ],
)
def test_replacement_requires_explicit_ack_current_revision_and_exact_original(
    setup, change, status
):
    client, p, calls, factories, directory, _ = setup
    payload = replacement_source(directory, p)
    before = request_rows(directory)
    assert authorize(client, p, payload | change).status_code == status
    assert request_rows(directory) == before
    assert not calls and not factories
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM construction_replacements"
            ).fetchone()[0]
            == 0
        )


def test_replacement_auth_owner_pending_completed_and_newer_unresolved_are_blocked(
    setup,
):
    client, p, calls, factories, directory, _ = setup
    payload = replacement_source(directory, p)
    assert authorize(client, p, payload, {}).status_code == 401
    assert authorize(client, p, payload, OTHER).status_code == 404
    other = create(client, "separate-project")
    assert (
        authorize(
            client, other, payload | {"expected_revision_id": other["revision_id"]}
        ).status_code
        == 404
    )
    replacement_source(directory, p, key="newer-pending", saved=route._PENDING)
    assert authorize(client, p, payload).status_code == 409
    pending_payload = payload | {"original_idempotency_key": "newer-pending"}
    assert authorize(client, p, pending_payload).status_code == 409
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        connection.execute("DELETE FROM requests WHERE key='newer-pending'")
    # An unrelated newer unknown cannot be skipped either.
    replacement_source(directory, p, key="newer-unknown")
    assert authorize(client, p, payload).status_code == 409
    assert not calls and not factories


def test_completed_source_cannot_authorize_replacement(setup):
    client, p, _, _, directory, _ = setup
    assert post(client, p).status_code == 200
    original = request_rows(directory)[0]
    payload = dict(
        expected_revision_id=p["revision_id"],
        original_idempotency_key=original[2],
        original_digest=original[3],
        replacement_idempotency_key="new-replacement",
        acknowledge_unknown=True,
    )
    assert authorize(client, p, payload).status_code == 409


def test_unknown_replacement_stops_again_and_only_explicit_child_grant_can_continue(
    setup,
):
    client, p, _, factories, directory, monkeypatch = setup
    payload = replacement_source(directory, p)
    assert authorize(client, p, payload).status_code == 200

    def timeout(*args, **kwargs):
        raise GatewayError("timeout")

    monkeypatch.setattr(muse_construction, "generate_muse_construction", timeout)
    assert (
        post(client, p, body(p, idempotency_key="replacement-one")).json()["code"]
        == "generation_outcome_unknown"
    )
    before = request_rows(directory)
    assert (
        post(client, p, body(p, idempotency_key="replacement-one")).status_code == 409
    )
    assert (
        post(client, p, body(p, idempotency_key="replacement-two")).status_code == 409
    )
    assert len(factories) == 1
    newest = before[-1]
    child = payload | dict(
        original_idempotency_key=newest[2],
        original_digest=newest[3],
        replacement_idempotency_key="replacement-two",
    )
    assert authorize(client, p, child).status_code == 200
    assert (
        post(client, p, body(p, idempotency_key="replacement-two")).status_code == 409
    )
    assert len(factories) == 2
    assert request_rows(directory)[:2] == before


def test_replacement_authorization_race_has_only_one_winner(setup):
    client, p, calls, factories, directory, _ = setup
    payload = replacement_source(directory, p)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda key: (
                    authorize(
                        client, p, payload | {"replacement_idempotency_key": key}
                    ).status_code
                ),
                ["replacement-one", "replacement-two"],
            )
        )
    assert sorted(results) == [200, 409]
    assert not calls and not factories
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM construction_replacements"
            ).fetchone()[0]
            == 1
        )


def test_stale_unused_grant_requires_explicit_append_only_successor(setup):
    client, p, calls, factories, directory, _ = setup
    payload = replacement_source(directory, p)
    original = request_rows(directory)
    assert authorize(client, p, payload).status_code == 200
    changed = p | {"revision_id": "inventory-new"}
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?", (json.dumps(changed), p["id"])
        )
    assert (
        post(
            client, changed, body(changed, idempotency_key="replacement-one")
        ).status_code
        == 409
    )
    successor = payload | {
        "expected_revision_id": changed["revision_id"],
        "replacement_idempotency_key": "replacement-two",
    }
    assert authorize(client, changed, successor).status_code == 200
    assert (
        post(
            client, changed, body(changed, idempotency_key="replacement-one")
        ).status_code
        == 409
    )
    assert request_rows(directory) == original
    assert (
        post(
            client, changed, body(changed, idempotency_key="replacement-two")
        ).status_code
        == 200
    )
    assert len(calls) == len(factories) == 1
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM construction_replacements"
            ).fetchone()[0]
            == 2
        )


def test_stale_reserved_grant_is_not_reclassified_as_never_used(setup):
    client, p, _, _, directory, monkeypatch = setup
    payload = replacement_source(directory, p)
    assert authorize(client, p, payload).status_code == 200

    def unavailable():
        raise ValueError("configuration unavailable")

    monkeypatch.setattr(muse_construction, "default_gateway_factory", unavailable)
    assert (
        post(client, p, body(p, idempotency_key="replacement-one")).status_code == 503
    )
    # The normal known-failure path removes its pending row; the separate
    # append-only reservation still proves this key was previously reserved.
    assert len(request_rows(directory)) == 1
    changed = p | {"revision_id": "inventory-new"}
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?", (json.dumps(changed), p["id"])
        )
    successor = payload | {
        "expected_revision_id": changed["revision_id"],
        "replacement_idempotency_key": "replacement-two",
    }
    assert authorize(client, changed, successor).status_code == 409


@pytest.mark.parametrize("change", ["digest", "completed"])
def test_dispatch_rechecks_original_after_authorization(setup, change):
    client, p, calls, factories, directory, _ = setup
    payload = replacement_source(directory, p)
    assert authorize(client, p, payload).status_code == 200
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        if change == "digest":
            connection.execute(
                "UPDATE requests SET digest=? WHERE key=?",
                ("c" * 64, payload["original_idempotency_key"]),
            )
        else:
            # Reconciliation outside this feature must invalidate the grant;
            # no replacement dispatch can keep assuming an unknown ancestor.
            connection.execute(
                "UPDATE requests SET response=? WHERE key=?",
                ("{}", payload["original_idempotency_key"]),
            )
    before = request_rows(directory)
    assert (
        post(client, p, body(p, idempotency_key="replacement-one")).status_code == 409
    )
    assert request_rows(directory) == before
    assert not calls and not factories


def test_completed_replacement_allows_new_cycle_but_new_unknown_needs_own_grant(setup):
    client, p, calls, factories, directory, monkeypatch = setup
    payload = replacement_source(directory, p)
    original = request_rows(directory)[0]
    assert authorize(client, p, payload).status_code == 200
    assert (
        post(client, p, body(p, idempotency_key="replacement-one")).status_code == 200
    )
    successful_runtime = muse_construction.generate_muse_construction

    def timeout(*args, **kwargs):
        raise GatewayError("timeout")

    monkeypatch.setattr(muse_construction, "generate_muse_construction", timeout)
    assert (
        post(client, p, body(p, idempotency_key="normal-next-cycle")).json()["code"]
        == "generation_outcome_unknown"
    )
    saved = request_rows(directory)
    assert (
        post(client, p, body(p, idempotency_key="unrelated-new-key")).status_code == 409
    )
    assert len(factories) == 2
    latest = saved[-1]
    child = payload | dict(
        original_idempotency_key=latest[2],
        original_digest=latest[3],
        replacement_idempotency_key="second-cycle-child",
    )
    assert authorize(client, p, child).status_code == 200
    monkeypatch.setattr(
        muse_construction, "generate_muse_construction", successful_runtime
    )
    assert (
        post(client, p, body(p, idempotency_key="second-cycle-child")).status_code
        == 200
    )
    assert (
        post(client, p, body(p, idempotency_key="third-normal-cycle")).status_code
        == 200
    )
    assert request_rows(directory)[0] == original
    assert request_rows(directory)[2] == saved[2]


@pytest.mark.parametrize(
    "leaf", ["missing", "pending", "unknown", "corrupt", "foreign", "foreign_revision"]
)
def test_only_a_valid_completed_authorized_successor_releases_historical_block(
    setup, leaf
):
    client, p, calls, factories, directory, _ = setup
    payload = replacement_source(directory, p)
    original = request_rows(directory)[0]
    assert authorize(client, p, payload).status_code == 200
    if leaf != "missing":
        assert (
            post(client, p, body(p, idempotency_key="replacement-one")).status_code
            == 200
        )
        row = request_rows(directory)[-1]
        if leaf == "pending":
            saved = route._PENDING
        elif leaf == "unknown":
            saved = route._uncertain_marker("timeout")
        elif leaf == "corrupt":
            saved = "{broken"
        elif leaf == "foreign":
            saved = json.dumps(json.loads(row[4]) | {"project_id": "foreign-project"})
        else:
            saved = json.dumps(
                json.loads(row[4]) | {"inventory_revision_id": "foreign-revision"}
            )
        with sqlite3.connect(directory / "projects.sqlite3") as connection:
            connection.execute(
                "UPDATE requests SET response=? WHERE key=?", (saved, "replacement-one")
            )
    before = len(factories)
    assert (
        post(client, p, body(p, idempotency_key="normal-unbound-key")).status_code
        == 409
    )
    assert len(factories) == before
    assert request_rows(directory)[0] == original
    if leaf in ("corrupt", "foreign", "foreign_revision"):
        listed = client.get(
            f"/api/projects/{p['id']}/construction/receipts", headers=AUTH
        ).json()["receipts"]
        child = next(r for r in listed if r["idempotency_key"] == "replacement-one")
        assert child["state"] == "unknown"
        assert child["error_code"] == "result_not_confirmed"


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


def test_approximate_requires_owned_consented_photo_before_dispatch(setup):
    client, p, calls, factories, directory, _ = setup
    assert post(client, p, body(p, approximate=True)).status_code == 422
    other = create(client, "project-other")
    foreign = upload(client, other).json()["media"]
    assert (
        post(
            client,
            p,
            body(
                p,
                approximate=True,
                media_id=foreign["id"],
                provider_transfer_consented=True,
            ),
        ).status_code
        == 404
    )
    photo_record = upload(client, p).json()["media"]
    assert (
        post(
            client, p, body(p, approximate=True, media_id=photo_record["id"])
        ).status_code
        == 422
    )
    assert not calls and not factories and not receipts(directory)
    assert (
        post(
            client,
            p,
            body(
                p,
                approximate=True,
                media_id=photo_record["id"],
                provider_transfer_consented=True,
            ),
        ).status_code
        == 200
    )
    assert calls[0]["approximate"] is True
    assert calls[0]["request_budget"].max_rounds == 1


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
    evidence = json.loads(receipts(directory)[0][0])["evidence"]
    assert evidence["observed_attempt_count"] is None
    assert evidence["usage"] is None
    if isinstance(error, GatewayError):
        assert evidence["gateway_code"] == error.code


def test_unknown_receipt_retains_attempt_evidence_without_releasing_identity(setup):
    client, p, _, factories, directory, monkeypatch = setup

    def fail(*args, **kwargs):
        kwargs["request_budget"].traces.extend(
            [
                Trace("/chat/completions", "muse-spark-1.3", 12, "ok", 101, 202),
                Trace("SECRET endpoint", "SECRET model", -1, "SECRET status", True, -1),
            ]
        )
        raise GatewayError("timeout")

    monkeypatch.setattr(muse_construction, "generate_muse_construction", fail)
    assert post(client, p).status_code == 409
    saved = receipts(directory)[0][0]
    evidence = json.loads(saved)["evidence"]
    assert evidence["stage"] == "generation"
    assert evidence["observed_attempt_count"] == 2
    assert evidence["attempts"][0]["input_tokens"] == 101
    assert evidence["attempts"][0]["output_tokens"] == 202
    assert evidence["usage"] == {
        "model_calls": 2,
        "input_tokens": None,
        "output_tokens": None,
    }
    assert evidence["attempts"][1] == dict(
        endpoint="unknown",
        model="unknown",
        status="unknown",
        elapsed_ms=None,
        input_tokens=None,
        output_tokens=None,
    )
    assert "SECRET" not in saved
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        identity = connection.execute(
            "SELECT owner,scope,key,digest FROM requests WHERE scope LIKE '%:construction-proposal'"
        ).fetchone()
    for key in ("construction-001", "construction-new"):
        assert post(client, p, body(p, idempotency_key=key)).status_code == 409
    assert receipts(directory)[0][0] == saved
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert connection.execute(
            "SELECT owner,scope,key,digest FROM requests WHERE scope LIKE '%:construction-proposal'"
        ).fetchall() == [identity]
    assert len(factories) == 1


def test_legacy_unknown_receipt_stays_byte_identical(setup):
    client, p, _, factories, directory, monkeypatch = setup

    def fail(*args, **kwargs):
        raise GatewayError("timeout")

    monkeypatch.setattr(muse_construction, "generate_muse_construction", fail)
    assert post(client, p).status_code == 409
    legacy = '{"pending": true, "uncertain": true, "error_code": "timeout"}'
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        connection.execute(
            "UPDATE requests SET response=? WHERE scope LIKE '%:construction-proposal'",
            (legacy,),
        )
    for key in ("construction-001", "construction-new"):
        assert post(client, p, body(p, idempotency_key=key)).status_code == 409
    assert receipts(directory) == [(legacy,)]
    assert len(factories) == 1


@pytest.mark.parametrize("unknown", [False, True])
def test_pre_approximate_schema_receipts_preserve_identity_and_replay(setup, unknown):
    client, p, calls, factories, directory, _ = setup
    media_id = upload(client, p).json()["media"]["id"]
    # Construct the old wire shape explicitly, without today's request model
    # or digest helper. The deployed schema had no approximate field.
    legacy_request = {
        "expected_revision_id": p["revision_id"],
        "user_notes": None,
        "media_id": media_id,
        "provider_context_consented": True,
        "provider_transfer_consented": True,
        "idempotency_key": "legacy-construction-001",
    }
    if unknown:
        saved = '{"pending": true, "uncertain": true, "error_code": "timeout"}'
    else:
        saved = json.dumps(
            {
                "project_id": p["id"],
                "inventory_revision_id": p["revision_id"],
                "status": "blocked",
                "questions": [],
                "replayed": False,
                "candidates": [
                    {
                        "candidate_id": "legacy-option",
                        "title": "Hypothetical panel",
                        "rationale": "Measurements remain unknown.",
                        "status": "blocked",
                        "construction": None,
                        "fabrication_plan": None,
                        "fabrication_report": None,
                        "blockers": ["Measurements required."],
                    }
                ],
                "diagnostics": {
                    "status": "ok",
                    "model": "muse-spark-1.3",
                    "elapsed_ms": 1,
                    "model_rounds": 1,
                    "tool_executions": 0,
                },
            }
        )
    scope = p["id"] + ":construction-proposal"
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        owner = connection.execute(
            "SELECT owner FROM projects WHERE id=?", (p["id"],)
        ).fetchone()[0]
        mime, photo_bytes = connection.execute(
            "SELECT content_type,body FROM media WHERE id=?", (media_id,)
        ).fetchone()
        legacy_digest = hashlib.sha256(
            json.dumps(
                {
                    "request": legacy_request,
                    "project_id": p["id"],
                    "context_fingerprint": StaticDesignContextResolver(None)(
                        p["id"], p["revision_id"]
                    ).fingerprint,
                    "photo_hash": hashlib.sha256(
                        mime.encode() + photo_bytes
                    ).hexdigest(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        original_row = (
            owner,
            scope,
            legacy_request["idempotency_key"],
            legacy_digest,
            saved,
        )
        connection.execute("INSERT INTO requests VALUES (?,?,?,?,?)", original_row)
    for payload in (legacy_request, legacy_request | {"approximate": False}):
        result = post(client, p, payload)
        if unknown:
            assert result.status_code == 409
            assert result.json()["code"] == "generation_outcome_unknown"
        else:
            assert result.status_code == 200
            assert result.json()["replayed"] is True
            assert result.json()["candidates"][0]["estimated_materials"] == []
    if unknown:
        assert (
            post(
                client, p, legacy_request | {"idempotency_key": "another-legacy-key"}
            ).json()["code"]
            == "generation_outcome_unknown"
        )
    for change in ({"user_notes": "Changed goal"}, {"approximate": True}):
        result = post(client, p, legacy_request | change)
        assert result.status_code == 409
        assert result.json()["code"] == "idempotency_conflict"
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert connection.execute(
            "SELECT * FROM requests WHERE scope=?", (scope,)
        ).fetchall() == [original_row]
    assert not calls and not factories


def test_receipt_read_is_owner_scoped_read_only_and_excludes_raw_payload(setup):
    client, p, _, factories, directory, monkeypatch = setup
    assert post(client, p).status_code == 200
    completed = receipts(directory)[0][0]
    legacy = '{"pending":true,"uncertain":true,"error_code":"timeout","evidence":{"SECRET":"raw"}}'
    malformed = '{"SECRET":"raw response", "error_code":"SECRET"}'
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        owner, scope = connection.execute(
            "SELECT owner,scope FROM requests WHERE scope LIKE '%:construction-proposal'"
        ).fetchone()
        connection.executemany(
            "INSERT INTO requests VALUES (?,?,?,?,?)",
            [
                (owner, scope, "legacy-unknown", "a" * 64, legacy),
                (owner, scope, "pending-original", "b" * 64, route._PENDING),
                (owner, scope, "corrupt-response", "c" * 64, malformed),
                (owner, scope + "-unrelated", "different-scope", "d" * 64, legacy),
            ],
        )
        before = connection.execute("SELECT * FROM requests ORDER BY rowid").fetchall()

    def forbidden(*args, **kwargs):
        pytest.fail(
            "Receipt inspection must not construct a gateway or resolve context"
        )

    monkeypatch.setattr(muse_construction, "default_gateway_factory", forbidden)
    monkeypatch.setattr(route.design_context, "default_context_resolver", forbidden)
    url = f"/api/projects/{p['id']}/construction/receipts"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=OTHER).status_code == 404
    response = client.get(url, headers=AUTH)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    by_key = {r["idempotency_key"]: r for r in response.json()["receipts"]}
    assert len(by_key) == 4
    assert by_key["construction-001"]["state"] == "completed"
    assert by_key["legacy-unknown"] == dict(
        idempotency_key="legacy-unknown",
        digest="a" * 64,
        state="unknown",
        error_code="timeout",
    )
    assert by_key["pending-original"]["state"] == "pending"
    assert by_key["corrupt-response"]["state"] == "unknown"
    assert "SECRET" not in response.text
    assert "candidates" not in response.text and completed not in response.text
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        assert (
            connection.execute("SELECT * FROM requests ORDER BY rowid").fetchall()
            == before
        )
    assert len(factories) == 1


def test_receipt_read_returns_at_most_sixteen(setup):
    client, p, _, factories, directory, _ = setup
    assert post(client, p).status_code == 200
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        owner, scope = connection.execute(
            "SELECT owner,scope FROM requests WHERE scope LIKE '%:construction-proposal'"
        ).fetchone()
        connection.executemany(
            "INSERT INTO requests VALUES (?,?,?,?,?)",
            [
                (owner, scope, f"pending-{i:03}", "a" * 64, route._PENDING)
                for i in range(20)
            ],
        )
    result = client.get(f"/api/projects/{p['id']}/construction/receipts", headers=AUTH)
    assert len(result.json()["receipts"]) == 16
    assert len(factories) == 1


def test_pre_dispatch_configuration_failure_releases_claim(setup):
    client, p, _, _, directory, monkeypatch = setup

    def bad_factory():
        raise ValueError("SECRET api key")

    monkeypatch.setattr(muse_construction, "default_gateway_factory", bad_factory)
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
        kwargs["request_budget"].traces.append(
            Trace("/chat/completions", "muse-spark-1.3", 12, "ok", 101, 202)
        )
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
    assert receipt["evidence"]["stage"] == "receipt_confirmation"
    assert receipt["evidence"]["usage"] == {
        "model_calls": 1,
        "input_tokens": 101,
        "output_tokens": 202,
    }
    assert "candidates" not in receipt
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
