"""Proof acceptance CLI over synthetic software snapshots; no physical evidence.

Snapshots and JSON exports come from the real Proof route on the existing
test_progress/test_proof/test_adapt fixtures. Text exports are produced by the
real web ``proof-report.ts`` formatter through Node (skipped only if Node is
unavailable), so a passing structural check is not against a regenerated copy.
"""

import copy
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_adapt import commit, joined, patch, simulate
from test_plans import AUTH
from test_progress import complete, photo, post, progress, update
from test_progress import preview_setup as preview_setup
from test_progress import setup as setup
from test_proof import proof
from test_proof import repair_setup as repair_setup

from forma_api import proof_smoke
from forma_api.demo_smoke import CREDENTIAL_ENV_VAR, HttpResponse, TransportError
from forma_api.plans import PlanRevision, PlanVersion
from forma_api.projects import Project, ProjectStore
from forma_domain.models import EvidenceInvalidation

ORIGIN = "https://api.example.test"
TOKEN = AUTH["Authorization"].split()[1]
LEAK = "LEAKSENTINEL-media-ZZ9"
WEB_FORMATTER = Path(proof_smoke.__file__).parents[3] / "web/src/lib/proof-report.ts"
NODE = shutil.which("node")


class Transport:
    def __init__(
        self, proof_body=b"{}", *, proof_status=200, headers=None, health=None
    ):
        self.proof_body = proof_body
        self.proof_status = proof_status
        self.headers = {"cache-control": "no-store"} if headers is None else headers
        self.health = health
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url[len(ORIGIN) :]
        if path == "/api/health":
            if self.health is not None:
                return self.health
            return HttpResponse(200, {}, b'{"status":"ok"}')
        return HttpResponse(self.proof_status, self.headers, self.proof_body)

    def calls(self):
        return [(r.method, r.url[len(ORIGIN) :]) for r in self.requests]


def run_cli(args, transport, *, env=None, project_id=None):
    out = io.StringIO()
    argv = ["--api-origin", ORIGIN, *args]
    if project_id is not None:
        argv = ["--project-id", project_id, *argv]
    code = proof_smoke.run(
        argv,
        env={CREDENTIAL_ENV_VAR: TOKEN} if env is None else env,
        transport=transport,
        out=out,
    )
    text = out.getvalue()
    return code, json.loads(text), text


def snapshot_bytes(client, project_id):
    response = proof(client, project_id)
    assert response.status_code == 200, response.text
    return response.content


def write_json_export(tmp_path, body, name="proof.json"):
    path = tmp_path / name
    path.write_text(json.dumps(json.loads(body), indent=2), encoding="utf-8")
    return str(path)


def write_text_export(tmp_path, body, name="proof.txt"):
    if NODE is None:
        pytest.skip("Node is required to run the real proof-report.ts formatter")
    script = (
        f"import {{proofText}} from {json.dumps(WEB_FORMATTER.as_uri())};"
        "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>"
        "process.stdout.write(proofText(JSON.parse(s))))"
    )
    result = subprocess.run(
        [NODE, "--experimental-strip-types", "--input-type=module", "-e", script],
        input=body,
        capture_output=True,
        timeout=60,
        check=True,
    )
    path = tmp_path / name
    path.write_bytes(result.stdout)
    return str(path)


def assert_no_leaks(text, *extra):
    for secret in (TOKEN, LEAK, "SYNTHETIC", "Authorization", *extra):
        assert secret not in text


def repaired(client, version):
    """A real approved repair: historical failed v1 plus active v2."""

    joined(client, version)
    complete(client, version, 6)
    failed = post(
        client,
        version,
        {
            **update(version, progress(client, version).json(), 7, result="failed"),
            "photo_ids": [photo(client, version)],
        },
    )
    assert failed.status_code == 200, failed.text
    current = progress(client, version).json()
    preview = simulate(client, version.plan, current, [patch(version.plan)])
    assert preview.status_code == 200, preview.text
    approved = commit(
        client, version.plan, current, preview.json()["previews"][0]["preview_id"]
    )
    assert approved.status_code == 200, approved.text


def mutated(body, change):
    document = json.loads(body)
    change(document)
    return json.dumps(document).encode()


# --- Offline / arguments ------------------------------------------------------


def test_help_is_offline_and_module_entrypoint_runs():
    result = subprocess.run(
        [sys.executable, "-m", "forma_api.proof_smoke", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "--json-export" in result.stdout and "--text-export" in result.stdout
    assert CREDENTIAL_ENV_VAR in result.stdout
    assert TOKEN not in result.stdout


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--project-id"],
        ["--project-id", "project-abc", "--token", LEAK],
        ["--project-id", "project-abc", "--timeout", LEAK],
        ["--project-id", "project-abc", "--json-ex", LEAK],
        [LEAK],
    ],
)
def test_malformed_arguments_are_safe_and_make_no_request(argv):
    transport = Transport()
    out = io.StringIO()
    code = proof_smoke.run(
        argv, env={CREDENTIAL_ENV_VAR: TOKEN}, transport=transport, out=out
    )
    report = json.loads(out.getvalue())
    assert code == 2
    assert report["errors"] == [{"check": "arguments", "code": "invalid_arguments"}]
    assert transport.requests == []
    assert_no_leaks(out.getvalue())


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["--api-origin", "https://user:pw@api.example.test"], "invalid_origin"),
        (["--api-origin", "https://api.example.test/path"], "invalid_origin"),
        (["--api-origin", "http://api.example.test"], "invalid_origin"),
        (["--timeout", "0"], "invalid_timeout"),
        (["--timeout", "31"], "invalid_timeout"),
    ],
)
def test_origin_and_timeout_are_validated_before_any_request(args, code):
    transport = Transport()
    out = io.StringIO()
    result = proof_smoke.run(
        ["--project-id", "project-abc", *args],
        env={CREDENTIAL_ENV_VAR: TOKEN},
        transport=transport,
        out=out,
    )
    assert result == 2
    assert json.loads(out.getvalue())["errors"] == [
        {"check": "arguments", "code": code}
    ]
    assert transport.requests == []
    assert "user:pw" not in out.getvalue()


def test_invalid_project_id_and_missing_credential_make_no_request():
    transport = Transport()
    code, report, _ = run_cli([], transport, project_id="../x")
    assert code == 2
    assert report["errors"] == [{"check": "arguments", "code": "invalid_project_id"}]
    code, report, _ = run_cli([], transport, project_id="project-abc", env={})
    assert code == 2
    assert report["errors"] == [{"check": "credential", "code": "credential_missing"}]
    assert transport.requests == []


def test_loopback_http_origin_is_allowed(setup):
    client, version, _ = setup
    body = snapshot_bytes(client, version.project_id)
    seen = []

    def transport(request):
        seen.append(request)
        if request.url.endswith("/api/health"):
            return HttpResponse(200, {}, b'{"status":"ok"}')
        return HttpResponse(200, {"cache-control": "no-store"}, body)

    out = io.StringIO()
    code = proof_smoke.run(
        ["--project-id", version.project_id, "--api-origin", "http://127.0.0.1:8000"],
        env={CREDENTIAL_ENV_VAR: TOKEN},
        transport=transport,
        out=out,
    )
    assert code == 0, out.getvalue()
    assert seen[0].url == "http://127.0.0.1:8000/api/health"


def test_credential_file_is_supported(setup, tmp_path):
    client, version, _ = setup
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN, encoding="utf-8")
    transport = Transport(snapshot_bytes(client, version.project_id))
    code, report, text = run_cli(
        ["--credential-file", str(token_file)],
        transport,
        env={},
        project_id=version.project_id,
    )
    assert code == 0, text
    assert transport.requests[1].headers["Authorization"] == f"Bearer {TOKEN}"
    assert_no_leaks(text, str(token_file))


# --- Live snapshot ------------------------------------------------------------


def test_current_snapshot_uses_only_allowed_gets_and_reports_no_export_claim(
    setup,
):
    client, version, _ = setup
    complete(client, version, 0)
    transport = Transport(snapshot_bytes(client, version.project_id))
    code, report, text = run_cli([], transport, project_id=version.project_id)
    assert code == 0, text
    assert transport.calls() == [
        ("GET", "/api/health"),
        ("GET", f"/api/projects/{version.project_id}/proof"),
    ]
    assert "Authorization" not in transport.requests[0].headers
    assert transport.requests[1].headers["Authorization"] == f"Bearer {TOKEN}"
    assert all(r.body is None for r in transport.requests)
    assert report["status"] == "ok"
    assert report["artifact_verification"] == "not_requested"
    assert report["json_export"] == {"status": "not_requested"}
    assert report["text_export"] == {"status": "not_requested"}
    assert report["physical_verification"] == "not_checked"
    assert report["measurements"] == "unknown"
    snapshot = report["snapshot"]
    assert snapshot["status"] == "ok" and snapshot["failed_checks"] == []
    assert snapshot["event_count"] == 1 and snapshot["versions"] == 1
    assert snapshot["state_counts"] == {"active": 1, "historical": 0, "preview": 0}
    assert all(snapshot["checks"].values())
    assert any("not_exact_text" in item for item in report["coverage_limits"])
    assert_no_leaks(text, version.project_id)


def test_repaired_history_snapshot_is_coherent_with_scoped_invalidations(repair_setup):
    client, version, _ = repair_setup
    repaired(client, version)
    code, report, text = run_cli(
        [],
        Transport(snapshot_bytes(client, version.project_id)),
        project_id=version.project_id,
    )
    assert code == 0, text
    snapshot = report["snapshot"]
    assert snapshot["state_counts"] == {"active": 1, "historical": 1, "preview": 0}
    assert snapshot["revision_count"] == 1
    assert snapshot["invalidation_count"] >= 1
    assert snapshot["photos_omitted"] >= 1


def persisted_third_version(client, version, directory, *, unrelated_preview=False):
    """Construct persisted software history, not a second repair approval."""

    repaired(client, version)
    project_id = version.project_id
    with ProjectStore(directory).transaction() as connection:
        project = Project.model_validate_json(
            connection.execute(
                "SELECT body FROM projects WHERE id=?", (project_id,)
            ).fetchone()[0]
        )
        row = connection.execute(
            "SELECT body, process, parameters FROM plans WHERE version_id=?",
            (project.active_version_id,),
        ).fetchone()
        second = PlanVersion.model_validate_json(row[0])
        revision = PlanRevision.model_validate_json(
            connection.execute(
                "SELECT body FROM plan_revisions WHERE id=?", (second.version_id,)
            ).fetchone()[0]
        )
        third_id = "version-constructed-third"
        plan = second.plan.model_copy(
            update={"version_id": third_id, "parent_version_id": second.version_id}
        )
        third = second.model_copy(
            update={
                "version_id": third_id,
                "candidate_id": "candidate-constructed-third",
                "plan": plan,
                "manual": second.manual.model_copy(update={"version_id": third_id}),
            }
        )
        third_revision = revision.model_copy(
            update={
                "version_id": third_id,
                "base_version_id": second.version_id,
                "base_last_event_id": None,
                "preview_id": "preview-constructed-third",
                "patch": revision.patch.model_copy(
                    update={
                        "id": "patch-constructed-third",
                        "base_version_id": second.version_id,
                    }
                ),
                "simulation": revision.simulation.model_copy(
                    update={"base_version_id": second.version_id, "plan": plan}
                ),
            }
        )
        connection.execute(
            "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)",
            (
                third_id,
                project_id,
                third.inventory_revision_id,
                third.model_dump_json(),
                row[1],
                row[2],
            ),
        )
        connection.execute(
            "INSERT INTO plan_revisions VALUES (?, ?, ?, ?)",
            (third_id, project_id, second.version_id, third_revision.model_dump_json()),
        )
        evidence_id = connection.execute(
            "SELECT evidence_id FROM evidence_invalidations WHERE project_id=? LIMIT 1",
            (project_id,),
        ).fetchone()[0]
        invalidation = EvidenceInvalidation(
            id="invalidation-constructed-third",
            evidence_id=evidence_id,
            invalidated_for_version_id=third_id,
            reason="Constructed software history: an ancestor check is invalidated again.",
            recorded_at=revision.approved_at,
        )
        connection.execute(
            "INSERT INTO evidence_invalidations VALUES (?, ?, ?, ?, ?)",
            (
                invalidation.id,
                project_id,
                evidence_id,
                third_id,
                invalidation.model_dump_json(),
            ),
        )
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?",
            (
                project.model_copy(
                    update={"active_version_id": third_id}
                ).model_dump_json(),
                project_id,
            ),
        )
        if unrelated_preview:
            preview_id = "version-constructed-unrelated-preview"
            preview = version.model_copy(
                update={
                    "version_id": preview_id,
                    "candidate_id": "candidate-constructed-unrelated-preview",
                    "plan": version.plan.model_copy(update={"version_id": preview_id}),
                    "manual": version.manual.model_copy(
                        update={"version_id": preview_id}
                    ),
                }
            )
            connection.execute(
                "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)",
                (
                    preview_id,
                    project_id,
                    preview.inventory_revision_id,
                    preview.model_dump_json(),
                    row[1],
                    row[2],
                ),
            )
    return snapshot_bytes(client, project_id)


def test_persisted_multigeneration_ancestor_invalidations_verify(
    repair_setup, tmp_path
):
    client, version, directory = repair_setup
    body = persisted_third_version(client, version, directory)
    document = json.loads(body)
    first, second, third = document["versions"]
    assert [item["state"] for item in document["versions"]] == [
        "historical",
        "historical",
        "active",
    ]
    assert third["plan"]["parent_version_id"] == second["plan"]["version_id"]
    assert second["plan"]["parent_version_id"] == first["plan"]["version_id"]
    original_evidence = {item["id"] for item in first["progress"]["evidence"]}
    assert any(
        item["evidence_id"] in original_evidence
        and item["invalidated_for_version_id"] == third["plan"]["version_id"]
        for item in first["invalidations"]
    )
    code, report, text = run_cli([], Transport(body), project_id=version.project_id)
    assert report["snapshot"].get("failed_checks", []) == []
    assert code == 0, report
    # These are actual formatter outputs over constructed persisted software
    # history, not proof of another feasible repair or a physical outcome.
    code, report, text = run_cli(
        [
            "--json-export",
            write_json_export(tmp_path, body),
            "--text-export",
            write_text_export(tmp_path, body),
        ],
        Transport(snapshot_bytes(client, version.project_id)),
        project_id=version.project_id,
    )
    assert code == 0, report
    assert report["artifact_verification"] == "json_semantic+text_structural"
    assert_no_leaks(text, version.project_id)


@pytest.mark.parametrize(
    "corruption", ["unrelated_preview", "self", "missing", "cycle"]
)
def test_persisted_invalidation_requires_complete_strict_ancestry(
    repair_setup, corruption
):
    client, version, directory = repair_setup
    # Construct the unrelated saved preview in the same explicitly software-only
    # history; initial preview creation is blocked after plan activation.
    document = json.loads(
        persisted_third_version(
            client,
            version,
            directory,
            unrelated_preview=corruption == "unrelated_preview",
        )
    )
    first = next(
        item
        for item in document["versions"]
        if item["plan"]["version_id"] == version.version_id
    )
    third = next(item for item in document["versions"] if item["state"] == "active")
    invalidation = next(
        item
        for item in first["invalidations"]
        if item["invalidated_for_version_id"] == third["plan"]["version_id"]
    )
    if corruption == "unrelated_preview":
        invalidation["invalidated_for_version_id"] = (
            "version-constructed-unrelated-preview"
        )
    elif corruption == "self":
        invalidation["invalidated_for_version_id"] = first["plan"]["version_id"]
    elif corruption == "missing":
        third["plan"]["parent_version_id"] = "version-missing-parent"
    else:
        first["plan"]["parent_version_id"] = third["plan"]["version_id"]
    code, report, text = run_cli(
        [], Transport(json.dumps(document).encode()), project_id=version.project_id
    )
    assert code == 1
    assert "invalidations_consistent" in report["snapshot"]["failed_checks"]
    assert_no_leaks(text, version.project_id)


@pytest.mark.parametrize(
    ("name", "change"),
    [
        (
            "progress_recomputes",
            lambda d: d["versions"][0]["progress"].update(status="passed"),
        ),
        (
            "progress_recomputes",
            lambda d: d["versions"][0]["progress"].update(last_event_id="event-x"),
        ),
        (
            "progress_recomputes",
            lambda d: d["versions"][0]["progress"].update(
                completed_operation_ids=d["versions"][0]["progress"][
                    "completed_operation_ids"
                ][:-1]
            ),
        ),
        (
            "scope_consistent",
            lambda d: d["versions"][0]["plan"].update(project_id="other-project"),
        ),
        (
            "scope_consistent",
            lambda d: d["versions"][0]["progress"]["events"][0].update(
                version_id="other-version"
            ),
        ),
        (
            "states_match_ancestry",
            lambda d: d["versions"][0].update(state="preview"),
        ),
        (
            "active_pointer_consistent",
            lambda d: d["project"].update(active_version_id=None),
        ),
        (
            "photos_excluded",
            lambda d: d["versions"][0]["plan"]["stocks"][0].update(image_ids=[LEAK]),
        ),
        (
            "photos_excluded",
            lambda d: d["versions"][0]["progress"]["evidence"][0].update(asset_id=LEAK),
        ),
        (
            "event_ids_unique",
            lambda d: d["versions"][0]["progress"]["events"].append(
                d["versions"][0]["progress"]["events"][0]
            ),
        ),
        (
            "references_resolve",
            lambda d: d["versions"][0]["progress"]["events"][0].update(
                evidence_ids=["evidence-missing"]
            ),
        ),
        (
            "references_resolve",
            lambda d: d["versions"][0]["progress"]["evidence"][0].update(
                part_ids=["part-missing"]
            ),
        ),
        (
            "expected_stock_recomputes",
            lambda d: d["versions"][0]["progress"]["expected_remaining_stock"][1][
                "remaining_length_mm"
            ].update(value=1.0),
        ),
        (
            "version_ids_unique",
            lambda d: d["versions"].append(copy.deepcopy(d["versions"][0])),
        ),
    ],
)
def test_contradictory_snapshots_fail_without_leaking(setup, name, change):
    client, version, _ = setup
    complete(client, version, 0)
    complete(client, version, 1)
    body = mutated(snapshot_bytes(client, version.project_id), change)
    code, report, text = run_cli([], Transport(body), project_id=version.project_id)
    assert code == 1
    assert report["status"] == "failed"
    assert report["snapshot"]["status"] == "failed"
    assert name in report["snapshot"]["failed_checks"], report["snapshot"]
    assert report["errors"] == [{"check": "snapshot", "code": "snapshot_incoherent"}]
    assert_no_leaks(text)


@pytest.mark.parametrize(
    ("name", "change"),
    [
        (
            "revisions_consistent",
            lambda d: d["versions"][1]["revision"].update(base_version_id="x-other"),
        ),
        (
            "revisions_consistent",
            lambda d: d["versions"][1].update(revision=None),
        ),
        (
            "invalidations_consistent",
            lambda d: d["versions"][0]["invalidations"][0].update(
                invalidated_for_version_id=d["versions"][0]["plan"]["version_id"]
            ),
        ),
        (
            "invalidations_consistent",
            lambda d: d["versions"][0]["invalidations"][0].update(
                evidence_id="evidence-missing"
            ),
        ),
        (
            "photos_excluded",
            lambda d: d["versions"][1]["revision"]["simulation"]["plan"]["stocks"][
                0
            ].update(image_ids=[LEAK]),
        ),
        (
            "states_match_ancestry",
            lambda d: d["versions"][0].update(state="preview"),
        ),
        (
            "progress_recomputes",
            lambda d: d["versions"][1]["progress"].update(carried_operation_ids=[]),
        ),
    ],
)
def test_contradictory_revision_history_fails(repair_setup, name, change):
    client, version, _ = repair_setup
    repaired(client, version)
    body = mutated(snapshot_bytes(client, version.project_id), change)
    code, report, text = run_cli([], Transport(body), project_id=version.project_id)
    assert code == 1
    assert name in report["snapshot"]["failed_checks"], report["snapshot"]
    assert_no_leaks(text)


def test_missing_no_store_header_and_wrong_project_fail(setup):
    client, version, _ = setup
    body = snapshot_bytes(client, version.project_id)
    code, report, _ = run_cli(
        [], Transport(body, headers={}), project_id=version.project_id
    )
    assert code == 1 and report["snapshot"]["failed_checks"] == ["cache_prevented"]
    code, report, text = run_cli([], Transport(body), project_id="project-other")
    assert code == 1
    assert "project_matches_request" in report["snapshot"]["failed_checks"]
    assert_no_leaks(text)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff\xfe",
        b'{"project": 1}',
        b'{"a": 1, "a": 2}',
        b'{"generated_at": NaN}',
        b"[]",
    ],
)
def test_malformed_live_snapshot_is_safe(body):
    code, report, text = run_cli([], Transport(body), project_id="project-abc")
    assert code == 1
    assert report["errors"] == [{"check": "snapshot", "code": "invalid_response"}]
    assert report["snapshot"] == {"status": "failed"}


def test_transport_and_http_failures_never_leak_server_text():
    cases = [
        (
            Transport(health=HttpResponse(500, {}, LEAK.encode())),
            "health",
            "http_error",
        ),
        (
            Transport(health=HttpResponse(200, {}, LEAK.encode())),
            "health",
            "invalid_response",
        ),
        (Transport(health=HttpResponse(302, {}, b"")), "health", "redirect_rejected"),
        (
            Transport(proof_status=401, proof_body=LEAK.encode()),
            "snapshot",
            "unauthorized",
        ),
        (
            Transport(proof_status=404, proof_body=LEAK.encode()),
            "snapshot",
            "not_found",
        ),
        (
            Transport(proof_status=307, proof_body=LEAK.encode()),
            "snapshot",
            "redirect_rejected",
        ),
        (
            Transport(proof_body=b"x" * (proof_smoke.MAX_RESPONSE_BYTES + 1)),
            "snapshot",
            "response_too_large",
        ),
    ]
    for transport, check, code_name in cases:
        code, report, text = run_cli([], transport, project_id="project-abc")
        assert code == 1
        assert report["errors"][0]["check"] == check
        assert report["errors"][0]["code"] == code_name
        assert_no_leaks(text)

    def timeout(_request):
        raise TransportError("timeout")

    def boom(_request):
        raise RuntimeError(f"{LEAK} {TOKEN}")

    for transport, expected in ((timeout, "timeout"), (boom, "network_error")):
        code, report, text = run_cli([], transport, project_id="project-abc")
        assert code == 1
        assert report["errors"] == [{"check": "health", "code": expected}]
        assert_no_leaks(text)


# --- Exports ------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", ["setup", "repair_setup"])
def test_current_downloaded_exports_verify(request, tmp_path, fixture_name):
    client, version, _ = request.getfixturevalue(fixture_name)
    if fixture_name == "setup":
        complete(client, version, 0)
        complete(client, version, 1)
    else:
        repaired(client, version)
    exported = snapshot_bytes(client, version.project_id)
    json_path = write_json_export(tmp_path, exported)
    text_path = write_text_export(tmp_path, exported)
    # The live snapshot is fetched later, so its generated_at differs.
    live = snapshot_bytes(client, version.project_id)
    assert json.loads(live)["generated_at"] != json.loads(exported)["generated_at"]
    transport = Transport(live)
    code, report, text = run_cli(
        ["--json-export", json_path, "--text-export", text_path],
        transport,
        project_id=version.project_id,
    )
    assert code == 0, text
    assert report["artifact_verification"] == "json_semantic+text_structural"
    assert report["json_export"]["status"] == "verified"
    assert report["json_export"]["semantic_match_excluding_generated_at"] is True
    assert report["text_export"] == {
        "status": "verified",
        "structural_match": True,
        "comparison": "structural_only",
    }
    assert len(transport.requests) == 2
    assert_no_leaks(text, json_path, text_path, version.project_id)


def test_each_export_can_be_verified_alone(setup, tmp_path):
    client, version, _ = setup
    exported = snapshot_bytes(client, version.project_id)
    code, report, _ = run_cli(
        ["--json-export", write_json_export(tmp_path, exported)],
        Transport(snapshot_bytes(client, version.project_id)),
        project_id=version.project_id,
    )
    assert code == 0 and report["artifact_verification"] == "json_semantic"
    assert report["text_export"] == {"status": "not_requested"}
    code, report, _ = run_cli(
        ["--text-export", write_text_export(tmp_path, exported)],
        Transport(snapshot_bytes(client, version.project_id)),
        project_id=version.project_id,
    )
    assert code == 0 and report["artifact_verification"] == "text_structural"
    assert report["json_export"] == {"status": "not_requested"}


def test_stale_exports_fail_after_a_new_report(setup, tmp_path):
    client, version, _ = setup
    complete(client, version, 0)
    exported = snapshot_bytes(client, version.project_id)
    json_path = write_json_export(tmp_path, exported)
    text_path = write_text_export(tmp_path, exported)
    complete(client, version, 1)
    live = Transport(snapshot_bytes(client, version.project_id))
    code, report, text = run_cli(
        ["--json-export", json_path, "--text-export", text_path],
        live,
        project_id=version.project_id,
    )
    assert code == 1
    assert report["artifact_verification"] == "failed"
    assert report["json_export"]["status"] == "failed"
    assert report["json_export"]["semantic_match_excluding_generated_at"] is False
    assert report["text_export"]["status"] == "failed"
    assert {e["code"] for e in report["errors"]} == {
        "snapshot_changed",
        "text_structure_mismatch",
    }
    assert_no_leaks(text)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["versions"][0]["progress"].update(status="passed"),
        lambda d: d["versions"][0]["progress"]["events"][0].update(
            observation="SYNTHETIC altered"
        ),
        lambda d: d["versions"][0].update(candidate_id="candidate-other"),
        lambda d: d.update(photos_omitted=d["photos_omitted"] + 1),
        lambda d: d["project"].update(goal="SYNTHETIC another goal"),
        lambda d: d["versions"].pop(),
    ],
)
def test_json_export_differences_fail_without_leaking(setup, tmp_path, change):
    client, version, _ = setup
    complete(client, version, 0)
    exported = mutated(snapshot_bytes(client, version.project_id), change)
    code, report, text = run_cli(
        ["--json-export", write_json_export(tmp_path, exported)],
        Transport(snapshot_bytes(client, version.project_id)),
        project_id=version.project_id,
    )
    assert code == 1
    assert report["json_export"]["status"] == "failed"
    assert report["artifact_verification"] == "failed"
    assert_no_leaks(text)


def test_incoherent_or_future_json_export_fails_even_when_content_matches(
    setup, tmp_path
):
    client, version, _ = setup
    live = snapshot_bytes(client, version.project_id)
    future = mutated(live, lambda d: d.update(generated_at="2999-01-01T00:00:00Z"))
    code, report, text = run_cli(
        ["--json-export", write_json_export(tmp_path, future)],
        Transport(live),
        project_id=version.project_id,
    )
    assert code == 1
    assert report["json_export"]["failed_checks"] == ["generated_not_after_current"]
    assert report["json_export"]["semantic_match_excluding_generated_at"] is True
    assert_no_leaks(text)


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"\xff\xfe\x00", "invalid_encoding"),
        (b"not json", "invalid_json"),
        (b'{"a": 1, "a": 2}', "invalid_json"),
        (b'{"project": {}}', "invalid_schema"),
        (b"x" * (proof_smoke.MAX_EXPORT_BYTES + 1), "export_too_large"),
    ],
)
def test_bad_json_export_files_fail_before_any_request(tmp_path, content, code):
    path = tmp_path / "secret-name-export.json"
    path.write_bytes(content)
    transport = Transport()
    result, report, text = run_cli(
        ["--json-export", str(path)], transport, project_id="project-abc"
    )
    assert result == 1
    assert report["errors"] == [{"check": "json_export", "code": code}]
    assert transport.requests == []
    assert "secret-name-export" not in text and str(tmp_path) not in text


@pytest.mark.parametrize("kind", ["--json-export", "--text-export"])
def test_missing_and_non_regular_export_paths_are_safe(tmp_path, kind):
    transport = Transport()
    for path, code in (
        (tmp_path / "missing-secret.txt", "export_unreadable"),
        (tmp_path, None),
    ):
        result, report, text = run_cli(
            [kind, str(path)], transport, project_id="project-abc"
        )
        assert result == 1
        assert report["errors"][0]["check"] == kind[2:].replace("-", "_")
        assert report["errors"][0]["code"] in {
            code or "export_not_regular_file",
            "export_unreadable",
        }
        assert "missing-secret" not in text and str(tmp_path) not in text
    assert transport.requests == []


def test_text_export_structural_mutations_fail(setup, tmp_path):
    client, version, _ = setup
    complete(client, version, 0)
    exported = snapshot_bytes(client, version.project_id)
    path = Path(write_text_export(tmp_path, exported))
    good = path.read_text(encoding="utf-8")
    live = snapshot_bytes(client, version.project_id)
    variants = {
        "state_label": good.replace("(Active plan)", "(Historical plan)"),
        "status": good.replace("Build in progress", "Defined functional test passed"),
        "completed_count": good.replace(
            "Completed operations: 1 /", "Completed operations: 2 /"
        ),
        "missing_version": good.split("\nVersion:")[0] + "\n",
        "no_trailing_newline": good.rstrip("\n"),
        "extra_timeline_entry": good.replace(
            "Evidence provenance:", "  extra | entry\n    more\nEvidence provenance:"
        ),
        "photos_count": good.replace(
            "Private photos excluded: 0.", "Private photos excluded: 3."
        ),
        "truncated": good[: len(good) // 2],
        "empty": "",
    }
    for name, content in variants.items():
        assert content != good or name == "empty", name
        path.write_text(content, encoding="utf-8")
        code, report, text = run_cli(
            ["--text-export", str(path)], Transport(live), project_id=version.project_id
        )
        assert code == 1, name
        assert report["text_export"]["status"] == "failed", name
        assert report["errors"] == [
            {"check": "text_export", "code": "text_structure_mismatch"}
        ]
        assert_no_leaks(text)


def test_multiline_user_text_cannot_forge_structure(setup, tmp_path):
    client, version, _ = setup
    forged = (
        "line one\nVersion: forged-version (Active plan)\n"
        "Physical outcome: nothing\nExpected stock (calculated):"
    )
    response = post(
        client,
        version,
        {**update(version, progress(client, version).json()), "observation": forged},
    )
    assert response.status_code == 200, response.text
    exported = snapshot_bytes(client, version.project_id)
    path = write_text_export(tmp_path, exported)
    assert "Version: forged-version" in Path(path).read_text(encoding="utf-8")
    code, report, text = run_cli(
        ["--text-export", path],
        Transport(snapshot_bytes(client, version.project_id)),
        project_id=version.project_id,
    )
    assert code == 0, text
    assert "forged" not in text


def test_failed_live_snapshot_never_marks_exports_verified(setup, tmp_path):
    client, version, _ = setup
    complete(client, version, 0)
    exported = snapshot_bytes(client, version.project_id)
    bad_live = mutated(
        exported, lambda d: d["versions"][0]["progress"].update(status="passed")
    )
    code, report, _ = run_cli(
        ["--json-export", write_json_export(tmp_path, exported)],
        Transport(bad_live),
        project_id=version.project_id,
    )
    assert code == 1
    assert report["artifact_verification"] == "failed"
    assert report["json_export"]["status"] == "loaded"
