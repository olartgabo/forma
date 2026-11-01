import io
import json
import subprocess
import sys

from forma_api import demo_smoke
from forma_api.demo_smoke import HttpResponse, TransportError

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
        ("GET", f"/api/projects/{PROJECT_ID}"): resp(payload=project_payload()),
        ("GET", f"/api/projects/{PROJECT_ID}/media"): resp(payload=media_payload()),
        ("POST", f"/api/projects/{PROJECT_ID}/intake"): resp(payload=intake_payload()),
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
    assert report["project"] == {"status": "not_checked"}
    assert report["media"] == {"status": "not_checked"}
    assert report["intake"] == {"status": "not_requested"}
    assert report["physical_verification"] == "not_checked"
    assert report["measurements"] == "unknown"
    assert fake.paths() == [("GET", "/api/health")]
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
    assert [m for m, _ in fake.paths()] == ["GET", "GET", "GET"]
    assert fake.requests[1].headers["Authorization"] == f"Bearer {TOKEN}"
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
    assert fake.requests[1].headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in text
    assert str(cred) not in text


def test_missing_credential_fails_project_without_project_request():
    fake = FakeTransport(healthy_routes())
    code, report, _ = invoke(base_argv("--project-id", PROJECT_ID), fake, env={})
    assert code == 1
    assert report["project"] == {"status": "failed"}
    assert report["errors"] == [{"check": "credential", "code": "credential_missing"}]
    assert fake.paths() == [("GET", "/api/health")]


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
