import io
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from forma_api import demo_smoke
from forma_api.demo_smoke import HttpRequest, HttpResponse, TransportError

TOKEN = "smoke-owner-secret-token-1234567890"
ORIGIN = "https://api.example.test"
PROJECT_ID = "project-abc"
MEDIA_ID = "media-abc"
REVISION = "inventory-rev1"


def resp(status=200, payload=None, body=None):
    data = body if body is not None else json.dumps(payload).encode()
    return HttpResponse(status=status, headers={}, body=data)


def project_payload(**overrides):
    value = {
        "id": PROJECT_ID,
        "goal": "stand",
        "revision_id": REVISION,
        "active_version_id": None,
        "stocks": [],
        "inventory_confirmed": True,
        "requirements": None,
    }
    value.update(overrides)
    return value


def provider_payload(**overrides):
    value = {"configured": True, "model": "muse-spark-1.3"}
    value.update(overrides)
    return value


def media_payload(**overrides):
    item = {
        "id": MEDIA_ID,
        "project_id": PROJECT_ID,
        "content_type": "image/png",
        "byte_count": 1234,
        "width_px": 12,
        "height_px": 8,
    }
    item.update(overrides)
    return {"media": [item]}


PROBLEM = "Secret reported problem leg split"
OPERATION_ID = "operation-abc"
ACTIVE_VERSION = "version-abc"


def readiness_payload(**overrides):
    value = {
        "project_id": PROJECT_ID,
        "inventory_revision_id": REVISION,
        "inventory_confirmed": True,
        "status": "inputs_complete",
        "missing_inputs": [],
        "blockers": [],
    }
    value.update(overrides)
    return value


def diagnosis_payload(**overrides):
    value = {
        "project_id": PROJECT_ID,
        "revision_id": REVISION,
        "media_id": MEDIA_ID,
        "active_version_id": None,
        "current_operation_id": None,
        "diagnosis": {
            "visible_observations": ["secret visible observation"],
            "hypotheses": ["secret hypothesis text"],
            "questions_or_measurements": ["secret question text"],
            "affected_ids": [],
            "failure_type": "torn_slot",
        },
        "diagnostics": {
            "status": "ok",
            "model": "muse-spark-1.3",
            "elapsed_ms": 99,
            "usage": {"model_calls": 1, "input_tokens": 20, "output_tokens": 7},
        },
    }
    value.update(overrides)
    return value


DESIGN_NOTES = "Secret design notes handle with care"


def design_payload(**overrides):
    value = {
        "project_id": PROJECT_ID,
        "inventory_revision_id": REVISION,
        "status": "proposed",
        "candidates": [
            {
                "candidate_id": "candidate-a",
                "status": "accepted",
                "version": None,
                "blockers": [],
            },
            {
                "candidate_id": "candidate-b",
                "status": "blocked",
                "version": None,
                "blockers": [],
            },
            {
                "candidate_id": "candidate-c",
                "status": "needs_measurement",
                "version": None,
                "blockers": [],
            },
            {
                "candidate_id": "candidate-d",
                "status": "unsupported",
                "version": None,
                "blockers": [],
            },
        ],
        "questions": ["secret design question text"],
        "blockers": [
            {
                "code": "missing_measurement",
                "message": "secret design blocker text",
                "target_ids": [],
            }
        ],
        "diagnostics": {
            "status": "ok",
            "model": "muse-spark-1.3",
            "elapsed_ms": 123,
            "model_rounds": 2,
            "tool_executions": 1,
            "usage": {"model_calls": 2, "input_tokens": 30, "output_tokens": 11},
        },
        "replayed": False,
    }
    value.update(overrides)
    return value


LAST_EVENT_ID = "event-abc"
REPAIR_CANDIDATE_A = "candidate-a"
REPAIR_CANDIDATE_B = "candidate-b"
SECRET_RATIONALE = "secret patch rationale text"
SECRET_REPAIR_QUESTION = "secret repair question text"


def repair_candidate(candidate_id, **overrides):
    value = {
        "id": candidate_id,
        "base_version_id": ACTIVE_VERSION,
        "kind": "resize_part",
        "target_id": "part-abc",
        "replacement_stock_id": None,
        "replacement_profile_id": None,
        "width_mm": 100.0,
        "height_mm": 50.0,
        "angle_deg": None,
        "rationale": SECRET_RATIONALE,
    }
    value.update(overrides)
    return value


def progress_payload(**overrides):
    value = {
        "project_id": PROJECT_ID,
        "version_id": ACTIVE_VERSION,
        "last_event_id": LAST_EVENT_ID,
        "events": [],
        "evidence": [],
        "material_transactions": [],
        "completed_operation_ids": [],
        "failed_operation_ids": [],
        "expected_remaining_stock": [],
        "status": "not_started",
    }
    value.update(overrides)
    return value


SECRET_EVENT_TEXT = "secret progress event observation"
SECRET_EVIDENCE_TEXT = "secret progress evidence description"


def _progress_event(event_id):
    return {
        "id": event_id,
        "project_id": PROJECT_ID,
        "version_id": ACTIVE_VERSION,
        "operation_id": None,
        "kind": "observation",
        "evidence_ids": [],
        "recorded_at": "2026-01-01T00:00:00Z",
        "actor": "user",
        "observation": SECRET_EVENT_TEXT,
        "verification_state": "unknown",
        "test_result": None,
    }


def _progress_evidence(evidence_id, kind, provenance):
    return {
        "id": evidence_id,
        "project_id": PROJECT_ID,
        "version_id": ACTIVE_VERSION,
        "kind": kind,
        "provenance": provenance,
        "asset_id": None,
        "part_ids": [],
        "operation_ids": [],
        "checkpoint_ids": [],
        "recorded_at": "2026-01-01T00:00:00Z",
        "description": SECRET_EVIDENCE_TEXT,
        "verification_state": "vision_observed",
    }


def rich_progress_payload(**overrides):
    value = progress_payload(
        events=[_progress_event("event-abc"), _progress_event("event-def")],
        evidence=[
            _progress_evidence("evidence-a", "model_interpretation", "model"),
            _progress_evidence("evidence-b", "model_interpretation", "user"),
            _progress_evidence("evidence-c", "photo", "model"),
        ],
        completed_operation_ids=["operation-abc", "operation-def"],
        failed_operation_ids=["operation-ghi"],
        status="building",
    )
    value.update(overrides)
    return value


def repair_payload(**overrides):
    value = {
        "project_id": PROJECT_ID,
        "base_version_id": ACTIVE_VERSION,
        "base_last_event_id": LAST_EVENT_ID,
        "candidates": [
            repair_candidate(REPAIR_CANDIDATE_A),
            repair_candidate(
                REPAIR_CANDIDATE_B,
                kind="change_angle",
                target_id=ACTIVE_VERSION,
                width_mm=None,
                height_mm=None,
                angle_deg=45.0,
            ),
        ],
        "questions": [SECRET_REPAIR_QUESTION],
        "diagnostics": {
            "status": "ok",
            "model": "muse-spark-1.3",
            "elapsed_ms": 55,
            "usage": {"model_calls": 1, "input_tokens": 15, "output_tokens": 9},
        },
    }
    value.update(overrides)
    return value


def _minimal_plan():
    unknown = {"value": None, "unit": "mm", "source": "unknown", "confirmed": False}
    unknown_g = {"value": None, "unit": "g", "source": "unknown", "confirmed": False}
    unknown_deg = {
        "value": None,
        "unit": "deg",
        "source": "unknown",
        "confirmed": False,
    }
    return {
        "project_id": PROJECT_ID,
        "version_id": "version-next",
        "parent_version_id": ACTIVE_VERSION,
        "family": "tabletop_fixture_v1",
        "status": "draft",
        "stocks": [],
        "parts": [],
        "joint_profiles": [],
        "joints": [],
        "operations": [],
        "checkpoints": [],
        "constraints": {
            "device_mass_g": unknown_g,
            "support_angle_deg": unknown_deg,
            "max_footprint_width_mm": unknown,
            "max_footprint_height_mm": dict(unknown),
            "allowed_profile_ids": [],
            "allow_purchases": False,
        },
        "compiler_version": "smoke-test",
        "created_at": "2026-01-01T00:00:00Z",
    }


def _repair_cost():
    return {
        "irreversible_completed_actions_lost": 0,
        "required_physical_undos": 0,
        "new_irreversible_actions": 0,
        "known_weighted_cost": 0,
        "estimated_extra_minutes": None,
        "material_waste_fraction": None,
        "estimated_new_purchase_cost": None,
        "complete_estimate": False,
    }


def simulate_payload(**overrides):
    candidates = repair_payload()["candidates"]
    value = {
        "project_id": PROJECT_ID,
        "base_version_id": ACTIVE_VERSION,
        "base_last_event_id": LAST_EVENT_ID,
        "remaining_stock": [],
        "previews": [
            {
                "preview_id": "preview-a",
                "rank": 1,
                "patch": candidates[0],
                "simulation": {
                    "patch_id": REPAIR_CANDIDATE_A,
                    "base_version_id": ACTIVE_VERSION,
                    "status": "feasible",
                    "plan": _minimal_plan(),
                    "cost": _repair_cost(),
                    "blockers": [],
                },
                "version": None,
                "panel_diff": None,
                "render_blockers": [],
            },
            {
                "preview_id": "preview-b",
                "rank": None,
                "patch": candidates[1],
                "simulation": {
                    "patch_id": REPAIR_CANDIDATE_B,
                    "base_version_id": ACTIVE_VERSION,
                    "status": "blocked",
                    "plan": None,
                    "cost": None,
                    "blockers": [
                        {
                            "code": "geometry_invalid",
                            "message": "secret simulation blocker text",
                            "target_ids": [],
                        },
                        {
                            "code": "stock_exhausted",
                            "message": "secret simulation blocker two",
                            "target_ids": [],
                        },
                    ],
                },
                "version": None,
                "panel_diff": None,
                "render_blockers": [],
            },
        ],
        "replayed": False,
    }
    value.update(overrides)
    return value


def intake_payload(**overrides):
    value = {
        "project_id": PROJECT_ID,
        "revision_id": REVISION,
        "media_id": MEDIA_ID,
        "observation": {
            "labels": ["cardboard sheet", "tape"],
            "measurement_source": "unknown",
            "questions": ["Measure thickness"],
        },
        "diagnostics": {
            "status": "ok",
            "model": "muse-spark-1.3",
            "elapsed_ms": 42,
            "usage": {"model_calls": 1, "input_tokens": 10, "output_tokens": 5},
        },
    }
    value.update(overrides)
    return value


class FakeTransport:
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path = (
            request.url[len(ORIGIN) :]
            if request.url.startswith(ORIGIN)
            else request.url
        )
        key = (request.method, path)
        if key not in self.routes:
            raise AssertionError(f"unexpected request {key}")
        handler = self.routes[key]
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            return handler(request)
        return handler

    def paths(self):
        return [(r.method, r.url[len(ORIGIN) :]) for r in self.requests]


def healthy_routes(overrides=None):
    routes = {
        ("GET", "/api/health"): resp(payload={"status": "ok"}),
        ("GET", "/api/provider/status"): resp(payload=provider_payload()),
        ("GET", f"/api/projects/{PROJECT_ID}"): resp(payload=project_payload()),
        ("GET", f"/api/projects/{PROJECT_ID}/media"): resp(payload=media_payload()),
        ("GET", f"/api/projects/{PROJECT_ID}/designs/readiness"): resp(
            payload=readiness_payload()
        ),
        ("POST", f"/api/projects/{PROJECT_ID}/intake"): resp(payload=intake_payload()),
        ("POST", f"/api/projects/{PROJECT_ID}/diagnose"): resp(
            payload=diagnosis_payload()
        ),
        ("POST", f"/api/projects/{PROJECT_ID}/designs/generate"): resp(
            payload=design_payload()
        ),
        (
            "GET",
            f"/api/projects/{PROJECT_ID}/versions/{ACTIVE_VERSION}/progress",
        ): resp(payload=progress_payload()),
        ("POST", f"/api/projects/{PROJECT_ID}/repairs/propose"): resp(
            payload=repair_payload()
        ),
        ("POST", f"/api/projects/{PROJECT_ID}/adapt/simulate"): resp(
            payload=simulate_payload()
        ),
    }
    if overrides:
        routes.update(overrides)
    return routes


def invoke(argv, transport, env=None):
    out = io.StringIO()
    code = demo_smoke.run(
        argv, env={} if env is None else env, transport=transport, out=out
    )
    text = out.getvalue()
    return code, json.loads(text), text


def base_argv(*extra):
    return ["--api-origin", ORIGIN, *extra]


def test_health_only_default_no_inference_no_credential():
    fake = FakeTransport(healthy_routes())
    code, report, _ = invoke(base_argv(), fake, env={})
    assert code == 0
    assert report["status"] == "ok"
    assert report["health"] == {"status": "ok"}
    assert report["provider"] == {
        "status": "ok",
        "configured": True,
        "model": "muse-spark-1.3",
    }
    assert report["progress"] == {"status": "not_checked"}
    assert report["usage_total"] is None
    assert report["project"] == {"status": "not_checked"}
    assert report["media"] == {"status": "not_checked"}
    assert report["intake"] == {"status": "not_requested"}
    assert report["design"] == {"status": "not_requested"}
    assert report["physical_verification"] == "not_checked"
    assert report["measurements"] == "unknown"
    assert fake.paths() == [("GET", "/api/health"), ("GET", "/api/provider/status")]
    assert "Authorization" not in fake.requests[0].headers


def test_readonly_project_media_eligibility_uses_env_credential():
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(
        base_argv("--project-id", PROJECT_ID, "--media-id", MEDIA_ID, "--timeout", "5"),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN, "MODEL_API_KEY": "provider-secret"},
    )
    assert code == 0
    assert report["project"]["revision_id"] == REVISION
    assert report["project"]["inventory_confirmed"] is True
    assert report["media"] == {
        "status": "ok",
        "media_id": MEDIA_ID,
        "content_type": "image/png",
        "byte_count": 1234,
        "eligible": True,
    }
    assert report["intake"] == {"status": "not_requested"}
    assert [m for m, _ in fake.paths()] == ["GET", "GET", "GET", "GET", "GET"]
    assert fake.requests[2].headers["Authorization"] == f"Bearer {TOKEN}"
    assert fake.requests[0].timeout == 5.0
    assert TOKEN not in text and "provider-secret" not in text


def test_live_without_consent_rejects_before_any_request():
    fake = FakeTransport(healthy_routes())
    code, report, _ = invoke(
        base_argv("--project-id", PROJECT_ID, "--media-id", MEDIA_ID, "--live-intake"),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 2
    assert report["errors"] == [{"check": "intake", "code": "consent_required"}]
    assert fake.requests == []


def test_live_requires_project_and_media_before_any_request():
    fake = FakeTransport(healthy_routes())
    code, report, _ = invoke(
        base_argv("--live-intake", "--transfer-consent"),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 2
    assert report["errors"][0]["code"] == "live_intake_requires_project_and_media"
    assert fake.requests == []


def test_consent_without_live_never_posts():
    fake = FakeTransport(healthy_routes())
    code, report, _ = invoke(
        base_argv(
            "--project-id",
            PROJECT_ID,
            "--media-id",
            MEDIA_ID,
            "--transfer-consent",
        ),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 0
    assert report["intake"] == {"status": "not_requested"}
    assert all(m == "GET" for m, _ in fake.paths())


def test_live_success_derives_revision_and_scoped_body():
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(
        base_argv(
            "--project-id",
            PROJECT_ID,
            "--media-id",
            MEDIA_ID,
            "--live-intake",
            "--transfer-consent",
        ),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN, "MODEL_API_KEY": "provider-secret"},
    )
    assert code == 0
    post = fake.requests[-1]
    assert post.method == "POST"
    assert json.loads(post.body) == {
        "media_id": MEDIA_ID,
        "expected_revision_id": REVISION,
        "provider_transfer_consented": True,
    }
    assert post.headers["Authorization"] == f"Bearer {TOKEN}"
    assert report["intake"] == {
        "status": "ok",
        "model": "muse-spark-1.3",
        "elapsed_ms": 42,
        "label_count": 2,
        "question_count": 1,
        "measurement_source": "unknown",
        "usage": {"model_calls": 1, "input_tokens": 10, "output_tokens": 5},
    }
    # Observation prose, token and provider key are never printed.
    assert "cardboard sheet" not in text
    assert "Measure thickness" not in text
    assert TOKEN not in text and "provider-secret" not in text
    assert report["physical_verification"] == "not_checked"


def test_credential_from_file(tmp_path):
    cred = tmp_path / "token.txt"
    cred.write_text(TOKEN + "\n", encoding="utf-8")
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(
        base_argv(
            "--project-id",
            PROJECT_ID,
            "--credential-file",
            str(cred),
        ),
        fake,
        env={},
    )
    assert code == 0
    assert fake.requests[2].headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in text
    assert str(cred) not in text


def test_missing_credential_fails_project_without_project_request():
    fake = FakeTransport(healthy_routes())
    code, report, _ = invoke(base_argv("--project-id", PROJECT_ID), fake, env={})
    assert code == 1
    assert report["project"] == {"status": "failed"}
    assert report["errors"] == [{"check": "credential", "code": "credential_missing"}]
    assert fake.paths() == [("GET", "/api/health"), ("GET", "/api/provider/status")]


def test_cli_secret_argument_rejected_before_request():
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(base_argv("--token", "cli-secret-value"), fake, env={})
    assert code == 2
    assert report["errors"] == [{"check": "arguments", "code": "invalid_arguments"}]
    assert "cli-secret-value" not in text
    assert fake.requests == []


def test_userinfo_origin_rejected_before_request():
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(
        ["--api-origin", "https://user:origin-secret@api.example.test"],
        fake,
        env={},
    )
    assert code == 2
    assert report["errors"] == [{"check": "arguments", "code": "invalid_origin"}]
    assert "origin-secret" not in text
    assert fake.requests == []


def test_origin_with_path_and_bad_timeout_rejected():
    fake = FakeTransport(healthy_routes())
    code, report, _ = invoke(["--api-origin", ORIGIN + "/api"], fake, env={})
    assert code == 2 and report["errors"][0]["code"] == "invalid_origin"
    code, report, _ = invoke(base_argv("--timeout", "999"), fake, env={})
    assert code == 2 and report["errors"][0]["code"] == "invalid_timeout"
    assert fake.requests == []


def test_failed_health_is_safe_nonzero():
    fake = FakeTransport(
        {("GET", "/api/health"): resp(503, body=b"upstream secret-body")}
    )
    code, report, text = invoke(base_argv(), fake, env={})
    assert code == 1
    assert report["health"] == {"status": "failed"}
    assert report["errors"] == [
        {"check": "health", "code": "http_error", "http_status": 503}
    ]
    assert "secret-body" not in text


def test_redirect_rejected():
    fake = FakeTransport({("GET", "/api/health"): resp(302, payload={"status": "ok"})})
    code, report, _ = invoke(base_argv(), fake, env={})
    assert code == 1
    assert report["errors"][0]["code"] == "redirect_rejected"


def test_timeout_is_safe_nonzero():
    fake = FakeTransport({("GET", "/api/health"): TransportError("timeout")})
    code, report, _ = invoke(base_argv(), fake, env={})
    assert code == 1
    assert report["errors"] == [{"check": "health", "code": "timeout"}]


def test_malformed_and_oversized_health():
    fake = FakeTransport({("GET", "/api/health"): resp(body=b"not-json-secret")})
    code, report, text = invoke(base_argv(), fake, env={})
    assert code == 1 and report["errors"][0]["code"] == "invalid_response"
    assert "not-json-secret" not in text

    big = b"x" * (demo_smoke.MAX_RESPONSE_BYTES + 1)
    fake = FakeTransport({("GET", "/api/health"): resp(body=big)})
    code, report, _ = invoke(base_argv(), fake, env={})
    assert code == 1 and report["errors"][0]["code"] == "response_too_large"


def test_ineligible_media_never_calls_intake():
    for overrides in (
        {"content_type": "image/webp"},
        {"byte_count": 5_000_001},
        {"byte_count": 0},
    ):
        routes = healthy_routes(
            {
                ("GET", f"/api/projects/{PROJECT_ID}/media"): resp(
                    payload=media_payload(**overrides)
                )
            }
        )
        fake = FakeTransport(routes)
        code, report, _ = invoke(
            base_argv(
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-intake",
                "--transfer-consent",
            ),
            fake,
            env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
        )
        assert code == 1
        assert report["media"]["eligible"] is False
        assert report["media"]["status"] == "ineligible"
        assert all(m == "GET" for m, _ in fake.paths())


def test_foreign_project_media_rejected_readonly_and_live_without_post_or_leak():
    for live in (False, True):
        routes = healthy_routes(
            {
                ("GET", f"/api/projects/{PROJECT_ID}/media"): resp(
                    payload=media_payload(project_id="project-other-foreign")
                )
            }
        )
        fake = FakeTransport(routes)
        extra = ["--live-intake", "--transfer-consent"] if live else []
        code, report, text = invoke(
            base_argv("--project-id", PROJECT_ID, "--media-id", MEDIA_ID, *extra),
            fake,
            env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
        )
        assert code == 1
        assert report["media"] == {"status": "failed", "media_id": MEDIA_ID}
        assert report["errors"] == [{"check": "media", "code": "invalid_response"}]
        assert report["intake"] == {"status": "not_requested"}
        assert all(m == "GET" for m, _ in fake.paths())
        assert "project-other-foreign" not in text
        assert TOKEN not in text


class _TricklingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "1000")
        self.end_headers()
        try:
            for _ in range(100):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass

    def log_message(self, *args):
        pass


def test_http_transport_total_deadline_bounds_trickling_response():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TricklingHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        start = time.monotonic()
        with pytest.raises(TransportError) as caught:
            demo_smoke._http_transport(
                HttpRequest(
                    method="GET",
                    url=f"http://127.0.0.1:{server.server_port}/api/health",
                    headers={},
                    body=None,
                    timeout=0.35,
                )
            )
        elapsed = time.monotonic() - start
        assert caught.value.code == "timeout"
        # Bytes arrive every 0.05s, so an inactivity timeout would not fire
        # for ~5s; the total deadline must cut the request off near 0.35s.
        assert elapsed < 1.5
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _FakeSocket:
    def __init__(self):
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True


class _BlockingConnection:
    """Fake connection whose DNS/connect stage stalls with no sock assigned.

    ``connect()`` represents both name resolution and TCP connect, which
    ``http.client`` performs inside ``connect()`` before ``sock`` exists.
    """

    instances = []

    def __init__(self, host, port=None, timeout=None, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.closed = False
        self.request_calls = []
        self.connect_calls = 0
        self.connect_started = threading.Event()
        self.release_connect = threading.Event()
        _BlockingConnection.instances.append(self)

    def connect(self):
        self.connect_calls += 1
        self.connect_started.set()
        # Bounded so a failing test cannot hang the suite forever.
        self.release_connect.wait(timeout=10)
        self.sock = _FakeSocket()

    def request(self, method, url, body=None, headers=None):
        self.request_calls.append((method, url, body))

    def getresponse(self):  # pragma: no cover - must never be reached
        raise AssertionError("getresponse must not be called after timeout")

    def close(self):
        self.closed = True
        if self.sock is not None:
            self.sock.close()


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.mark.parametrize("method,body", [("GET", None), ("POST", b'{"x":1}')])
def test_http_transport_stalled_connect_no_sock_times_out_and_never_dispatches(
    monkeypatch, method, body
):
    _BlockingConnection.instances = []
    monkeypatch.setattr(demo_smoke.http.client, "HTTPConnection", _BlockingConnection)
    start = time.monotonic()
    with pytest.raises(TransportError) as caught:
        demo_smoke._http_transport(
            HttpRequest(
                method=method,
                url="http://unresolvable.example.test:8000/api/health"
                if method == "GET"
                else "http://unresolvable.example.test:8000/api/projects/p/intake",
                headers={"Authorization": "Bearer should-not-be-sent"},
                body=body,
                timeout=0.3,
            )
        )
    elapsed = time.monotonic() - start
    assert caught.value.code == "timeout"
    # Caller returns near its deadline even though connect is still blocked
    # and no socket was ever assigned (so shutdown could not interrupt it).
    assert elapsed < 1.5
    assert len(_BlockingConnection.instances) == 1
    conn = _BlockingConnection.instances[0]
    assert conn.connect_started.is_set()
    assert conn.sock is None
    assert conn.connect_calls == 1
    assert conn.request_calls == []

    # Releasing the blocked stage afterwards must not dispatch the request
    # (critical for a late live-intake POST) and must clean up.
    conn.release_connect.set()
    assert _wait_until(lambda: conn.closed)
    assert conn.request_calls == []
    assert conn.connect_calls == 1  # no automatic reconnect/retry
    assert conn.sock is not None and conn.sock.closed


def test_missing_media_is_not_found():
    routes = healthy_routes(
        {("GET", f"/api/projects/{PROJECT_ID}/media"): resp(payload={"media": []})}
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        base_argv("--project-id", PROJECT_ID, "--media-id", MEDIA_ID),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 1
    assert report["errors"] == [{"check": "media", "code": "not_found"}]


def test_stale_and_provider_intake_errors_are_redacted():
    for status, payload, expected in (
        (
            409,
            {"code": "stale_version", "message": "server secret detail"},
            "stale_version",
        ),
        (
            502,
            {"code": "provider_authentication", "message": "provider secret"},
            "provider_authentication",
        ),
        (
            503,
            {"code": "provider_not_configured", "message": "x"},
            "provider_not_configured",
        ),
        (429, {"code": "rate_limit", "message": "x"}, "rate_limit"),
    ):
        routes = healthy_routes(
            {
                ("POST", f"/api/projects/{PROJECT_ID}/intake"): resp(
                    status, payload=payload
                )
            }
        )
        fake = FakeTransport(routes)
        code, report, text = invoke(
            base_argv(
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-intake",
                "--transfer-consent",
            ),
            fake,
            env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
        )
        assert code == 1
        assert report["intake"] == {"status": "failed"}
        assert report["errors"] == [
            {"check": "intake", "code": expected, "http_status": status}
        ]
        assert "secret" not in text


def test_malformed_intake_result_is_invalid_response():
    routes = healthy_routes(
        {
            ("POST", f"/api/projects/{PROJECT_ID}/intake"): resp(
                payload=intake_payload(revision_id="inventory-other")
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        base_argv(
            "--project-id",
            PROJECT_ID,
            "--media-id",
            MEDIA_ID,
            "--live-intake",
            "--transfer-consent",
        ),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 1
    assert report["errors"] == [{"check": "intake", "code": "invalid_response"}]


def test_unauthorized_project_is_safe():
    routes = healthy_routes(
        {
            ("GET", f"/api/projects/{PROJECT_ID}"): resp(
                401, payload={"code": "forbidden", "message": "token secret hint"}
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, text = invoke(
        base_argv("--project-id", PROJECT_ID),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 1
    assert report["errors"] == [
        {"check": "project", "code": "forbidden", "http_status": 401}
    ]
    assert "secret hint" not in text and TOKEN not in text


def test_readiness_success_safe_fields_only():
    routes = healthy_routes(
        {
            ("GET", f"/api/projects/{PROJECT_ID}/designs/readiness"): resp(
                payload=readiness_payload(
                    status="needs_input",
                    missing_inputs=["secret missing input text"],
                    blockers=[
                        {
                            "code": "missing_measurement",
                            "message": "secret blocker text",
                            "target_ids": [],
                        }
                    ],
                )
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, text = invoke(
        base_argv("--project-id", PROJECT_ID),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 0
    readiness = report["design_readiness"]
    assert readiness["ready"] is False
    assert readiness["status"] == "needs_input"
    assert readiness["blocker_codes"] == ["missing_measurement"]
    assert readiness["counts"] == {"blockers": 1, "missing_inputs": 1}
    assert "blocker_count" not in readiness
    assert "missing_input_count" not in readiness
    assert "secret missing input text" not in text
    assert "secret blocker text" not in text
    assert TOKEN not in text
    assert ("GET", f"/api/projects/{PROJECT_ID}/designs/readiness") in fake.paths()


def test_readiness_schema_mismatch_and_http_error():
    routes = healthy_routes(
        {
            ("GET", f"/api/projects/{PROJECT_ID}/designs/readiness"): resp(
                payload={"project_id": PROJECT_ID, "bogus": "secret-schema-text"}
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, text = invoke(
        base_argv("--project-id", PROJECT_ID),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 1
    assert report["design_readiness"] == {"status": "failed"}
    assert report["errors"] == [
        {"check": "design_readiness", "code": "invalid_response"}
    ]
    assert "secret-schema-text" not in text

    routes = healthy_routes(
        {
            ("GET", f"/api/projects/{PROJECT_ID}/designs/readiness"): resp(
                503, payload={"code": "provider_error", "message": "secret detail"}
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, text = invoke(
        base_argv("--project-id", PROJECT_ID),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 1
    assert report["design_readiness"] == {"status": "failed"}
    assert report["errors"] == [
        {"check": "design_readiness", "code": "provider_error", "http_status": 503}
    ]
    assert "secret detail" not in text


def _diagnosis_argv(*extra):
    return base_argv(
        "--project-id",
        PROJECT_ID,
        "--media-id",
        MEDIA_ID,
        "--live-diagnosis",
        "--transfer-consent",
        "--problem",
        PROBLEM,
        *extra,
    )


def test_live_diagnosis_success_without_operation_scope():
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(
        _diagnosis_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 0
    posts = [r for r in fake.requests if r.method == "POST"]
    assert len(posts) == 1
    assert posts[0].url == ORIGIN + f"/api/projects/{PROJECT_ID}/diagnose"
    assert json.loads(posts[0].body) == {
        "media_id": MEDIA_ID,
        "expected_revision_id": REVISION,
        "reported_problem": PROBLEM,
        "provider_transfer_consented": True,
        "expected_active_version_id": None,
        "current_operation_id": None,
    }
    diag = report["diagnosis"]
    assert diag == {
        "status": "ok",
        "failure_type": "torn_slot",
        "counts": {
            "visible_observations": 1,
            "hypotheses": 1,
            "questions_or_measurements": 1,
            "affected_ids": 0,
        },
        "diagnostics": {
            "model": "muse-spark-1.3",
            "elapsed_ms": 99,
            "usage": {"model_calls": 1, "input_tokens": 20, "output_tokens": 7},
        },
        "live_provider_call": True,
    }
    assert report["usage_total"] == {
        "model_calls": 1,
        "input_tokens": 20,
        "output_tokens": 7,
        "elapsed_ms": 99,
    }
    assert PROBLEM not in text
    assert "secret visible observation" not in text
    assert "secret hypothesis text" not in text
    assert "secret question text" not in text
    assert TOKEN not in text


def test_live_diagnosis_success_with_operation_scope():
    routes = healthy_routes(
        {
            ("GET", f"/api/projects/{PROJECT_ID}"): resp(
                payload=project_payload(active_version_id=ACTIVE_VERSION)
            ),
            ("POST", f"/api/projects/{PROJECT_ID}/diagnose"): resp(
                payload=diagnosis_payload(
                    active_version_id=ACTIVE_VERSION,
                    current_operation_id=OPERATION_ID,
                )
            ),
        }
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        _diagnosis_argv("--operation-id", OPERATION_ID),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 0
    posts = [r for r in fake.requests if r.method == "POST"]
    assert len(posts) == 1
    assert json.loads(posts[0].body) == {
        "media_id": MEDIA_ID,
        "expected_revision_id": REVISION,
        "reported_problem": PROBLEM,
        "provider_transfer_consented": True,
        "expected_active_version_id": ACTIVE_VERSION,
        "current_operation_id": OPERATION_ID,
    }
    assert report["diagnosis"]["live_provider_call"] is True


@pytest.mark.parametrize(
    "extra,expected_code",
    [
        (["--live-diagnosis"], "live_diagnosis_requires_project_and_media"),
        (
            ["--live-diagnosis", "--transfer-consent"],
            "live_diagnosis_requires_project_and_media",
        ),
        (
            ["--live-diagnosis", "--transfer-consent", "--problem", PROBLEM],
            "live_diagnosis_requires_project_and_media",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--live-diagnosis",
                "--transfer-consent",
                "--problem",
                PROBLEM,
            ],
            "live_diagnosis_requires_project_and_media",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-diagnosis",
                "--problem",
                PROBLEM,
            ],
            "consent_required",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-diagnosis",
                "--transfer-consent",
            ],
            "live_diagnosis_requires_problem",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-diagnosis",
                "--transfer-consent",
                "--problem",
                "   ",
            ],
            "invalid_problem",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-diagnosis",
                "--transfer-consent",
                "--problem",
                "x" * 1001,
            ],
            "invalid_problem",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-diagnosis",
                "--transfer-consent",
                "--problem",
                PROBLEM,
                "--live-intake",
            ],
            "invalid_arguments",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-diagnosis",
                "--transfer-consent",
                "--problem",
                PROBLEM,
                "--operation-id",
                "bad id!",
            ],
            "invalid_operation_id",
        ),
    ],
)
def test_live_diagnosis_parser_rejections_zero_transport(extra, expected_code):
    fake = FakeTransport(healthy_routes())
    code, report, _ = invoke(
        base_argv(*extra), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 2
    assert report["errors"]
    assert report["errors"][0]["code"] == expected_code
    assert fake.requests == []


def test_live_diagnosis_ineligible_media_zero_posts():
    routes = healthy_routes(
        {
            ("GET", f"/api/projects/{PROJECT_ID}/media"): resp(
                payload=media_payload(content_type="image/webp")
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        _diagnosis_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 1
    assert report["media"]["eligible"] is False
    assert all(m == "GET" for m, _ in fake.paths())


def test_live_diagnosis_operation_without_active_plan_zero_posts():
    fake = FakeTransport(healthy_routes())  # active_version_id is None
    code, report, _ = invoke(
        _diagnosis_argv("--operation-id", OPERATION_ID),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 1
    assert report["errors"] == [{"check": "diagnosis", "code": "active_plan_required"}]
    assert all(m == "GET" for m, _ in fake.paths())


def test_live_diagnosis_result_mismatch_is_invalid_response():
    for overrides in (
        {"project_id": "project-other"},
        {"media_id": "media-other"},
        {"revision_id": "inventory-other"},
    ):
        routes = healthy_routes(
            {
                ("POST", f"/api/projects/{PROJECT_ID}/diagnose"): resp(
                    payload=diagnosis_payload(**overrides)
                )
            }
        )
        fake = FakeTransport(routes)
        code, report, text = invoke(
            _diagnosis_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
        )
        assert code == 1
        assert report["diagnosis"] == {"status": "failed"}
        assert report["errors"] == [{"check": "diagnosis", "code": "invalid_response"}]
        assert "project-other" not in text and "media-other" not in text
        assert "inventory-other" not in text


def test_live_diagnosis_operation_scope_mismatch_is_invalid_response():
    for overrides in (
        {"current_operation_id": "operation-other"},
        {"active_version_id": "version-other"},
        {"current_operation_id": None},
        {"active_version_id": None},
    ):
        routes = healthy_routes(
            {
                ("GET", f"/api/projects/{PROJECT_ID}"): resp(
                    payload=project_payload(active_version_id=ACTIVE_VERSION)
                ),
                ("POST", f"/api/projects/{PROJECT_ID}/diagnose"): resp(
                    payload={
                        **diagnosis_payload(
                            active_version_id=ACTIVE_VERSION,
                            current_operation_id=OPERATION_ID,
                        ),
                        **overrides,
                    }
                ),
            }
        )
        fake = FakeTransport(routes)
        code, report, text = invoke(
            _diagnosis_argv("--operation-id", OPERATION_ID),
            fake,
            env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
        )
        assert code == 1
        assert report["diagnosis"] == {"status": "failed"}
        assert report["errors"] == [{"check": "diagnosis", "code": "invalid_response"}]
        assert "operation-other" not in text and "version-other" not in text


def test_live_diagnosis_provider_errors_surfaced():
    for status, payload, expected in (
        (
            502,
            {"code": "provider_error", "message": "provider secret"},
            "provider_error",
        ),
        (
            503,
            {"code": "provider_not_configured", "message": "x"},
            "provider_not_configured",
        ),
        (504, {"code": "timeout", "message": "x"}, "timeout"),
        (429, {"code": "rate_limit", "message": "x"}, "rate_limit"),
        (422, {"code": "consent_required", "message": "x"}, "consent_required"),
    ):
        routes = healthy_routes(
            {
                ("POST", f"/api/projects/{PROJECT_ID}/diagnose"): resp(
                    status, payload=payload
                )
            }
        )
        fake = FakeTransport(routes)
        code, report, text = invoke(
            _diagnosis_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
        )
        assert code == 1
        assert report["diagnosis"] == {"status": "failed"}
        assert report["errors"] == [
            {"check": "diagnosis", "code": expected, "http_status": status}
        ]
        assert "provider secret" not in text
        assert PROBLEM not in text and TOKEN not in text


def _design_argv(*extra):
    return base_argv(
        "--project-id",
        PROJECT_ID,
        "--live-design",
        "--transfer-consent",
        *extra,
    )


def test_live_design_success_single_post_and_safe_report():
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(
        _design_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 0
    posts = [r for r in fake.requests if r.method == "POST"]
    assert len(posts) == 1
    assert posts[0].url == ORIGIN + f"/api/projects/{PROJECT_ID}/designs/generate"
    body = json.loads(posts[0].body)
    assert set(body) == {
        "expected_revision_id",
        "user_notes",
        "idempotency_key",
        "provider_context_consented",
    }
    assert body["expected_revision_id"] == REVISION
    assert body["user_notes"] is None
    assert body["provider_context_consented"] is True
    assert isinstance(body["idempotency_key"], str)
    assert len(body["idempotency_key"]) >= 8
    assert posts[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert report["design"] == {
        "status": "proposed",
        "counts": {
            "accepted": 1,
            "blocked": 1,
            "needs_measurement": 1,
            "unsupported": 1,
        },
        "question_count": 1,
        "diagnostics": {
            "model": "muse-spark-1.3",
            "elapsed_ms": 123,
            "model_rounds": 2,
            "tool_executions": 1,
            "usage": {"model_calls": 2, "input_tokens": 30, "output_tokens": 11},
        },
        "live_provider_call": True,
        "replayed": False,
    }
    assert "secret design question text" not in text
    assert "secret design blocker text" not in text
    assert TOKEN not in text
    assert report["physical_verification"] == "not_checked"


def test_live_design_success_with_notes_stripped_and_never_echoed():
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(
        _design_argv("--design-notes", f"  {DESIGN_NOTES}  "),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 0
    posts = [r for r in fake.requests if r.method == "POST"]
    assert len(posts) == 1
    assert json.loads(posts[0].body)["user_notes"] == DESIGN_NOTES
    assert DESIGN_NOTES not in text
    assert report["design"]["live_provider_call"] is True


@pytest.mark.parametrize(
    "extra,expected_code",
    [
        (["--live-design"], "live_design_requires_project"),
        (["--live-design", "--transfer-consent"], "live_design_requires_project"),
        (["--project-id", PROJECT_ID, "--live-design"], "consent_required"),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--live-design",
                "--transfer-consent",
                "--live-intake",
            ],
            "invalid_arguments",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--live-design",
                "--transfer-consent",
                "--live-diagnosis",
            ],
            "invalid_arguments",
        ),
        (
            ["--project-id", PROJECT_ID, "--design-notes", DESIGN_NOTES],
            "design_notes_requires_live_design",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--live-design",
                "--transfer-consent",
                "--design-notes",
                "x" * 1001,
            ],
            "invalid_design_notes",
        ),
    ],
)
def test_live_design_parser_rejections_zero_transport(extra, expected_code):
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(
        base_argv(*extra), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 2
    assert report["errors"]
    assert report["errors"][0]["code"] == expected_code
    assert fake.requests == []
    assert DESIGN_NOTES not in text


def test_live_design_whitespace_only_notes_sent_as_no_notes():
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(
        _design_argv("--design-notes", "   \t  "),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 0
    posts = [r for r in fake.requests if r.method == "POST"]
    assert len(posts) == 1
    assert json.loads(posts[0].body)["user_notes"] is None
    assert report["design"]["live_provider_call"] is True


def test_live_design_active_plan_refused_with_zero_generate_posts():
    routes = healthy_routes(
        {
            ("GET", f"/api/projects/{PROJECT_ID}"): resp(
                payload=project_payload(active_version_id=ACTIVE_VERSION)
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        _design_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 1
    assert report["design"] == {"status": "failed"}
    assert report["errors"] == [{"check": "design", "code": "blocked"}]
    assert all(m == "GET" for m, _ in fake.paths())
    assert not any(p.endswith("/designs/generate") for _, p in fake.paths())


def test_live_design_result_mismatch_is_invalid_response():
    for overrides in (
        {"project_id": "project-other"},
        {"inventory_revision_id": "inventory-other"},
    ):
        routes = healthy_routes(
            {
                ("POST", f"/api/projects/{PROJECT_ID}/designs/generate"): resp(
                    payload=design_payload(**overrides)
                )
            }
        )
        fake = FakeTransport(routes)
        code, report, text = invoke(
            _design_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
        )
        assert code == 1
        assert report["design"] == {"status": "failed"}
        assert report["errors"] == [{"check": "design", "code": "invalid_response"}]
        assert "project-other" not in text and "inventory-other" not in text


def test_live_design_provider_errors_surfaced():
    for status, payload, expected in (
        (429, {"code": "rate_limit", "message": "provider secret"}, "rate_limit"),
        (
            502,
            {"code": "provider_error", "message": "provider secret"},
            "provider_error",
        ),
        (
            503,
            {"code": "provider_not_configured", "message": "x"},
            "provider_not_configured",
        ),
        (504, {"code": "timeout", "message": "x"}, "timeout"),
        (422, {"code": "consent_required", "message": "x"}, "consent_required"),
        (409, {"code": "stale_version", "message": "x"}, "stale_version"),
        (409, {"code": "blocked", "message": "x"}, "blocked"),
    ):
        routes = healthy_routes(
            {
                ("POST", f"/api/projects/{PROJECT_ID}/designs/generate"): resp(
                    status, payload=payload
                )
            }
        )
        fake = FakeTransport(routes)
        code, report, text = invoke(
            _design_argv("--design-notes", DESIGN_NOTES),
            fake,
            env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
        )
        assert code == 1
        assert report["design"] == {"status": "failed"}
        assert report["errors"] == [
            {"check": "design", "code": expected, "http_status": status}
        ]
        assert "provider secret" not in text
        assert DESIGN_NOTES not in text and TOKEN not in text


def _repair_argv(*extra):
    return base_argv(
        "--project-id",
        PROJECT_ID,
        "--media-id",
        MEDIA_ID,
        "--live-repair",
        "--transfer-consent",
        "--problem",
        PROBLEM,
        *extra,
    )


def _repair_routes(overrides=None):
    base = {
        ("GET", f"/api/projects/{PROJECT_ID}"): resp(
            payload=project_payload(active_version_id=ACTIVE_VERSION)
        ),
        ("POST", f"/api/projects/{PROJECT_ID}/diagnose"): resp(
            payload=diagnosis_payload(
                active_version_id=ACTIVE_VERSION,
                current_operation_id=OPERATION_ID,
            )
        ),
    }
    if overrides:
        base.update(overrides)
    return healthy_routes(base)


def test_live_repair_success_two_candidates_one_blocked():
    fake = FakeTransport(_repair_routes())
    code, report, text = invoke(
        _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 0
    assert fake.paths() == [
        ("GET", "/api/health"),
        ("GET", "/api/provider/status"),
        ("GET", f"/api/projects/{PROJECT_ID}"),
        ("GET", f"/api/projects/{PROJECT_ID}/versions/{ACTIVE_VERSION}/progress"),
        ("GET", f"/api/projects/{PROJECT_ID}/designs/readiness"),
        ("GET", f"/api/projects/{PROJECT_ID}/media"),
        ("POST", f"/api/projects/{PROJECT_ID}/diagnose"),
        ("POST", f"/api/projects/{PROJECT_ID}/repairs/propose"),
        ("POST", f"/api/projects/{PROJECT_ID}/adapt/simulate"),
    ]
    assert (
        fake.paths().count(
            ("GET", f"/api/projects/{PROJECT_ID}/versions/{ACTIVE_VERSION}/progress")
        )
        == 1
    )
    assert not any(
        "commit" in path or "approve" in path or "activate" in path
        for _, path in fake.paths()
    )
    propose = fake.requests[7]
    propose_body = json.loads(propose.body)
    assert propose_body["expected_version_id"] == ACTIVE_VERSION
    assert propose_body["expected_last_event_id"] == LAST_EVENT_ID
    assert propose_body["reported_problem"] == PROBLEM
    assert propose_body["diagnosis"] == diagnosis_payload()["diagnosis"]
    assert propose_body["provider_context_consented"] is True
    simulate = fake.requests[8]
    sim_body = json.loads(simulate.body)
    assert sim_body["expected_version_id"] == ACTIVE_VERSION
    assert sim_body["expected_last_event_id"] == LAST_EVENT_ID
    assert sim_body["idempotency_key"].startswith("smoke-repair-")
    assert [c["id"] for c in sim_body["candidates"]] == [
        REPAIR_CANDIDATE_A,
        REPAIR_CANDIDATE_B,
    ]
    assert sim_body["remaining_confirmed"] is True
    assert sim_body["connector_measurements"] == []
    assert report["diagnosis"]["status"] == "ok"
    assert report["diagnosis"]["live_provider_call"] is True
    assert report["repair"] == {
        "status": "ok",
        "candidate_count": 2,
        "previews": [
            {"rank": 1, "feasible": True, "blocker_count": 0},
            {"rank": None, "feasible": False, "blocker_count": 2},
        ],
        "question_count": 1,
        "diagnostics": {
            "model": "muse-spark-1.3",
            "elapsed_ms": 55,
            "usage": {"model_calls": 1, "input_tokens": 15, "output_tokens": 9},
        },
        "live_provider_call": True,
        "simulate": {"status": "ok", "preview_count": 2},
    }
    assert report["usage_total"] == {
        "model_calls": 2,
        "input_tokens": 35,
        "output_tokens": 16,
        "elapsed_ms": 154,
    }
    assert PROBLEM not in text
    assert SECRET_RATIONALE not in text
    assert SECRET_REPAIR_QUESTION not in text
    assert "secret visible observation" not in text
    assert "secret hypothesis text" not in text
    assert "secret simulation blocker" not in text
    assert TOKEN not in text


def test_live_repair_success_with_operation_scope():
    fake = FakeTransport(_repair_routes())
    code, report, _ = invoke(
        _repair_argv("--operation-id", OPERATION_ID),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 0
    diagnose_body = json.loads(fake.requests[6].body)
    assert diagnose_body["expected_active_version_id"] == ACTIVE_VERSION
    assert diagnose_body["current_operation_id"] == OPERATION_ID
    assert report["repair"]["candidate_count"] == 2


def test_live_repair_zero_candidates_no_simulate():
    routes = _repair_routes(
        {
            ("POST", f"/api/projects/{PROJECT_ID}/repairs/propose"): resp(
                payload=repair_payload(candidates=[], questions=["q-secret"])
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, text = invoke(
        _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 0
    assert report["repair"]["candidate_count"] == 0
    assert report["repair"]["previews"] == []
    assert report["repair"]["simulate"] == {
        "status": "not_requested",
        "preview_count": 0,
    }
    assert not any(path.endswith("/adapt/simulate") for _, path in fake.paths())
    assert "q-secret" not in text


def test_live_repair_no_active_plan_exit1_zero_posts():
    routes = healthy_routes()  # active_version_id is None
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 1
    assert report["repair"] == {"status": "failed"}
    assert {"check": "repair", "code": "active_plan_required"} in report["errors"]
    assert all(m == "GET" for m, _ in fake.paths())


@pytest.mark.parametrize(
    "extra,expected_code,expected_check",
    [
        (["--live-repair"], "live_repair_requires_project_and_media", "arguments"),
        (
            ["--live-repair", "--transfer-consent"],
            "live_repair_requires_project_and_media",
            "arguments",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--live-repair",
                "--transfer-consent",
                "--problem",
                PROBLEM,
            ],
            "live_repair_requires_project_and_media",
            "arguments",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-repair",
                "--problem",
                PROBLEM,
            ],
            "consent_required",
            "repair",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-repair",
                "--transfer-consent",
            ],
            "live_repair_requires_problem",
            "arguments",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-repair",
                "--transfer-consent",
                "--problem",
                "   ",
            ],
            "invalid_problem",
            "arguments",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-repair",
                "--transfer-consent",
                "--problem",
                PROBLEM,
                "--live-diagnosis",
            ],
            "invalid_arguments",
            "arguments",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-repair",
                "--transfer-consent",
                "--problem",
                PROBLEM,
                "--live-design",
            ],
            "invalid_arguments",
            "arguments",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-repair",
                "--transfer-consent",
                "--problem",
                PROBLEM,
                "--live-intake",
            ],
            "invalid_arguments",
            "arguments",
        ),
        (
            [
                "--project-id",
                PROJECT_ID,
                "--media-id",
                MEDIA_ID,
                "--live-repair",
                "--transfer-consent",
                "--problem",
                PROBLEM,
                "--design-notes",
                DESIGN_NOTES,
            ],
            "design_notes_requires_live_design",
            "arguments",
        ),
        (
            ["--problem", PROBLEM],
            "problem_requires_live_diagnosis_or_repair",
            "arguments",
        ),
        (
            ["--operation-id", OPERATION_ID],
            "operation_id_requires_live_diagnosis_or_repair",
            "arguments",
        ),
    ],
)
def test_live_repair_parser_rejections_zero_transport(
    extra, expected_code, expected_check
):
    fake = FakeTransport(healthy_routes())
    code, report, text = invoke(
        base_argv(*extra), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 2
    assert report["errors"] == [{"check": expected_check, "code": expected_code}]
    assert fake.requests == []
    assert PROBLEM not in text and DESIGN_NOTES not in text


def test_live_repair_missing_credential_exit2_zero_transport():
    fake = FakeTransport(_repair_routes())
    code, report, _ = invoke(_repair_argv(), fake, env={})
    assert code == 2
    assert report["errors"] == [{"check": "credential", "code": "credential_missing"}]
    assert fake.requests == []


def test_live_repair_diagnosis_failure_no_repair_call():
    routes = _repair_routes(
        {
            ("POST", f"/api/projects/{PROJECT_ID}/diagnose"): resp(
                503,
                payload={"code": "provider_not_configured", "message": "x"},
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 1
    assert report["diagnosis"] == {"status": "failed"}
    # Repair was requested; it must not be reported as not_requested.
    assert report["repair"] == {"status": "failed"}
    assert report["errors"] == [
        {"check": "diagnosis", "code": "provider_not_configured", "http_status": 503}
    ]
    assert not any("repairs" in path for _, path in fake.paths())
    assert not any("adapt" in path for _, path in fake.paths())


@pytest.mark.parametrize(
    "status,server_code,expected",
    [
        (503, "provider_not_configured", "provider_not_configured"),
        (429, "rate_limit", "rate_limit"),
        (409, "stale_version", "stale_version"),
        (504, "timeout", "timeout"),
    ],
)
def test_live_repair_propose_provider_errors(status, server_code, expected):
    routes = _repair_routes(
        {
            ("POST", f"/api/projects/{PROJECT_ID}/repairs/propose"): resp(
                status, payload={"code": server_code, "message": "provider secret"}
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, text = invoke(
        _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 1
    assert report["repair"] == {"status": "failed"}
    assert report["errors"] == [
        {"check": "repair", "code": expected, "http_status": status}
    ]
    assert "provider secret" not in text and PROBLEM not in text
    assert not any("adapt" in path for _, path in fake.paths())


def test_live_repair_malformed_propose_is_invalid_response():
    for overrides in (
        {"project_id": "project-other"},
        {"base_version_id": "version-other"},
        {"base_last_event_id": "event-other"},
        {"base_last_event_id": None},
    ):
        routes = _repair_routes(
            {
                ("POST", f"/api/projects/{PROJECT_ID}/repairs/propose"): resp(
                    payload=repair_payload(**overrides)
                )
            }
        )
        fake = FakeTransport(routes)
        code, report, text = invoke(
            _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
        )
        assert code == 1
        assert report["repair"] == {"status": "failed"}
        assert {"check": "repair", "code": "invalid_response"} in report["errors"]
        assert "project-other" not in text and "version-other" not in text
        assert not any("adapt" in path for _, path in fake.paths())


def test_live_repair_progress_mismatch_is_invalid_response():
    routes = _repair_routes(
        {
            (
                "GET",
                f"/api/projects/{PROJECT_ID}/versions/{ACTIVE_VERSION}/progress",
            ): resp(payload=progress_payload(version_id="version-other"))
        }
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 1
    assert report["repair"] == {"status": "failed"}
    assert {"check": "progress", "code": "invalid_response"} in report["errors"]
    assert not any("repairs" in path for _, path in fake.paths())


def test_live_repair_malformed_simulate_is_invalid_response():
    for overrides in (
        {"project_id": "project-other"},
        {"base_version_id": "version-other"},
        {"base_last_event_id": "event-other"},
    ):
        routes = _repair_routes(
            {
                ("POST", f"/api/projects/{PROJECT_ID}/adapt/simulate"): resp(
                    payload=simulate_payload(**overrides)
                )
            }
        )
        fake = FakeTransport(routes)
        code, report, _ = invoke(
            _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
        )
        assert code == 1
        assert report["repair"]["status"] == "failed"
        assert {"check": "simulate", "code": "invalid_response"} in report["errors"]


def test_live_repair_simulate_missing_candidate_is_invalid_response():
    payload = simulate_payload()
    payload["previews"] = payload["previews"][:1]
    routes = _repair_routes(
        {("POST", f"/api/projects/{PROJECT_ID}/adapt/simulate"): resp(payload=payload)}
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 1
    assert report["repair"]["status"] == "failed"
    assert {"check": "simulate", "code": "invalid_response"} in report["errors"]


def test_live_repair_render_blocked_preview_is_not_reported_feasible():
    # The adapt route marks a simulation-feasible candidate whose manual
    # cannot render with render_blockers and no version; commit rejects it
    # ("cannot be approved"), so the smoke must not call it feasible.
    payload = simulate_payload()
    first = payload["previews"][0]
    first["rank"] = 1
    first["render_blockers"] = [
        {
            "code": "geometry_invalid",
            "message": "secret render blocker text",
            "target_ids": [],
        }
    ]
    routes = _repair_routes(
        {("POST", f"/api/projects/{PROJECT_ID}/adapt/simulate"): resp(payload=payload)}
    )
    fake = FakeTransport(routes)
    code, report, text = invoke(
        _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 0
    assert report["repair"]["previews"][0] == {
        "rank": 1,
        "feasible": False,
        "blocker_count": 1,
    }
    assert report["repair"]["previews"][1] == {
        "rank": None,
        "feasible": False,
        "blocker_count": 2,
    }
    assert "secret render blocker text" not in text


def test_live_repair_simulate_failure():
    routes = _repair_routes(
        {
            ("POST", f"/api/projects/{PROJECT_ID}/adapt/simulate"): resp(
                409, payload={"code": "stale_version", "message": "secret detail"}
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, text = invoke(
        _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 1
    assert report["repair"]["status"] == "failed"
    assert report["repair"]["simulate"] == {"status": "failed", "preview_count": 0}
    assert report["errors"] == [
        {"check": "simulate", "code": "stale_version", "http_status": 409}
    ]
    assert "secret detail" not in text
    assert not any("commit" in path or "approve" in path for _, path in fake.paths())


def test_provider_not_configured_readonly_is_informational():
    routes = healthy_routes(
        {
            ("GET", "/api/provider/status"): resp(
                payload=provider_payload(configured=False)
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(base_argv(), fake, env={})
    assert code == 0
    assert report["provider"] == {
        "status": "ok",
        "configured": False,
        "model": "muse-spark-1.3",
    }
    assert report["errors"] == []
    assert fake.paths() == [("GET", "/api/health"), ("GET", "/api/provider/status")]


def test_provider_not_configured_live_blocks_before_project_or_post():
    routes = healthy_routes(
        {
            ("GET", "/api/provider/status"): resp(
                payload=provider_payload(configured=False)
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        _diagnosis_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 1
    assert report["provider"] == {
        "status": "ok",
        "configured": False,
        "model": "muse-spark-1.3",
    }
    assert report["errors"] == [
        {"check": "provider", "code": "provider_not_configured"}
    ]
    assert fake.paths() == [("GET", "/api/health"), ("GET", "/api/provider/status")]
    assert all(m == "GET" for m, _ in fake.paths())


@pytest.mark.parametrize(
    "handler,expected_code",
    [
        (TransportError("timeout"), "timeout"),
        (
            resp(503, payload={"code": "provider_error", "message": "secret"}),
            "provider_error",
        ),
        (
            resp(payload={"configured": "secret-malformed", "model": 1}),
            "invalid_response",
        ),
    ],
)
def test_provider_failure_live_exits_before_post(handler, expected_code):
    routes = healthy_routes({("GET", "/api/provider/status"): handler})
    fake = FakeTransport(routes)
    code, report, text = invoke(
        _diagnosis_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 1
    assert report["provider"] == {"status": "failed"}
    assert report["errors"][0]["check"] == "provider"
    assert report["errors"][0]["code"] == expected_code
    assert fake.paths() == [("GET", "/api/health"), ("GET", "/api/provider/status")]
    assert all(m == "GET" for m, _ in fake.paths())
    assert "secret" not in text


@pytest.mark.parametrize(
    "handler",
    [
        TransportError("timeout"),
        resp(503, payload={"code": "provider_error", "message": "secret"}),
        resp(payload={"configured": "secret-malformed", "model": 1}),
    ],
)
def test_provider_failure_readonly_is_unavailable_without_error(handler):
    routes = healthy_routes({("GET", "/api/provider/status"): handler})
    fake = FakeTransport(routes)
    code, report, text = invoke(base_argv(), fake, env={})
    assert code == 0
    assert report["provider"] == {"status": "unavailable"}
    assert report["errors"] == []
    assert "secret" not in text


def test_progress_summary_counts_only_for_active_version():
    routes = _repair_routes(
        {
            (
                "GET",
                f"/api/projects/{PROJECT_ID}/versions/{ACTIVE_VERSION}/progress",
            ): resp(payload=rich_progress_payload())
        }
    )
    fake = FakeTransport(routes)
    code, report, text = invoke(
        base_argv("--project-id", PROJECT_ID),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 0
    assert report["progress"] == {
        "status": "building",
        "event_count": 2,
        "completed_operation_count": 2,
        "failed_operation_count": 1,
        "diagnosis_evidence_count": 1,
        "last_event_present": True,
    }
    assert report["usage_total"] is None
    assert SECRET_EVENT_TEXT not in text
    assert SECRET_EVIDENCE_TEXT not in text
    assert TOKEN not in text


def test_progress_not_checked_without_active_version():
    fake = FakeTransport(healthy_routes())
    code, report, _ = invoke(
        base_argv("--project-id", PROJECT_ID),
        fake,
        env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN},
    )
    assert code == 0
    assert report["progress"] == {"status": "not_checked"}
    assert not any("progress" in path for _, path in fake.paths())


def test_usage_total_null_field_when_any_step_reports_unknown():
    routes = _repair_routes(
        {
            ("POST", f"/api/projects/{PROJECT_ID}/diagnose"): resp(
                payload=diagnosis_payload(
                    diagnostics={
                        "status": "ok",
                        "model": "muse-spark-1.3",
                        "elapsed_ms": 99,
                        "usage": {
                            "model_calls": 1,
                            "input_tokens": None,
                            "output_tokens": 7,
                        },
                    }
                )
            )
        }
    )
    fake = FakeTransport(routes)
    code, report, _ = invoke(
        _repair_argv(), fake, env={demo_smoke.CREDENTIAL_ENV_VAR: TOKEN}
    )
    assert code == 0
    assert report["usage_total"] == {
        "model_calls": 2,
        "input_tokens": None,
        "output_tokens": 16,
        "elapsed_ms": 154,
    }


def test_module_entrypoint_invalid_origin_is_json():
    result = subprocess.run(
        [sys.executable, "-m", "forma_api.demo_smoke", "--api-origin", "ftp://x"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["errors"] == [{"check": "arguments", "code": "invalid_origin"}]
