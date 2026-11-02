"""Reproducible connected-demo smoke command.

Default operation is read-only: health, plus owner-authorized saved project,
design-readiness and saved-media eligibility checks when selectors are
supplied. A live saved photo intake runs only with ``--live-intake`` and
``--transfer-consent``. A live failure-photo diagnosis runs only with
``--live-diagnosis``, ``--transfer-consent`` and a required ``--problem``
text (optionally scoped to the active plan with ``--operation-id``);
``--live-intake`` and ``--live-diagnosis`` are mutually exclusive so at most
one provider-backed request is made per invocation.

Example live diagnosis run::

    python -m forma_api.demo_smoke --project-id project-abc \
        --media-id media-abc --live-diagnosis --transfer-consent \
        --problem "The leg split at the slot"

A passing live-diagnosis smoke proves only that the provider returned one
validated response for that photo. It does not prove physical repair
success, and this command never claims a physical test pass.

The owner credential is read only from the ``FORMA_SMOKE_OWNER_TOKEN``
environment variable or an optional credential file. It is never accepted as
a command-line value and never printed. No provider key is read and no direct
provider call is made; live intake and live diagnosis use the existing
consented API routes.

This command never uploads files, activates plans, changes inventory, or
claims a physical test pass. Photo-derived measurements remain unknown.
"""

import argparse
import http.client
import json
import os
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

from pydantic import ValidationError

from forma_api.design_runtime import DesignReadiness
from forma_api.diagnosis_runtime import (
    MAX_REPORTED_PROBLEM_LENGTH,
    DiagnosisRequest,
    DiagnosisResult,
)
from forma_api.intake_runtime import (
    MAX_PROVIDER_IMAGE_BYTES,
    SUPPORTED_IMAGE_TYPES,
    IntakeRequest,
    IntakeResult,
)
from forma_api.media import MediaList
from forma_api.projects import Project
from forma_api.routes.health import HealthResponse

CREDENTIAL_ENV_VAR = "FORMA_SMOKE_OWNER_TOKEN"
DEFAULT_ORIGIN = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 0.1
MAX_TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 1_000_000
MAX_CREDENTIAL_BYTES = 4096
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,95}$")

# Stable, safe server error codes that may be surfaced without server text.
_SAFE_ERROR_CODES = frozenset(
    {
        "access_denied",
        "blocked",
        "consent_required",
        "forbidden",
        "invalid_response",
        "network_error",
        "not_found",
        "provider_authentication",
        "provider_error",
        "provider_http_error",
        "provider_not_configured",
        "rate_limit",
        "stale_version",
        "timeout",
        "validation_error",
    }
)


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None
    timeout: float


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class TransportError(Exception):
    """Safe transport failure carrying only a stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # noqa: D102 - argparse hook
        raise _ArgumentError("invalid_arguments")


_WORKER_GRACE_SECONDS = 0.2


def _shutdown_sock(sock) -> None:
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # A concurrently completed/closed socket needs no cancel.


def _http_transport(request: HttpRequest) -> HttpResponse:
    """One bounded HTTP(S) request; redirects are never followed.

    ``request.timeout`` is a total per-request deadline covering DNS,
    connection, headers and body for the *caller*.

    Name resolution and TCP/TLS connect inside ``HTTPConnection.connect()``
    can block in an uninterruptible OS call before ``connection.sock`` is
    assigned, so a socket-shutdown timer alone cannot stop them. The actual
    work therefore runs on a bounded daemon worker: the caller joins it only
    until the deadline (plus a short grace for cooperative cleanup) and then
    returns ``TransportError("timeout")``.

    Cancellation limitation, honestly: a worker stuck in OS resolution /
    connect cannot be force-killed in Python and may stay blocked as a
    daemon thread until the OS call eventually returns. It is *not* allowed
    to do anything observable after that: the worker re-checks the expiry
    flag immediately after the explicit ``connect()`` and before dispatch,
    so a late connection never sends headers/body (including a live intake
    POST), never reconnects/retries, and is closed in ``finally``.
    """

    expired = threading.Event()
    shared: dict = {}
    outcome: dict = {}

    def run() -> None:
        try:
            outcome["response"] = _http_transport_once(request, expired, shared)
        except BaseException as exc:  # Propagated to caller below.
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True, name="forma-smoke-http")
    worker.start()
    worker.join(request.timeout)
    if worker.is_alive():
        expired.set()
        connection = shared.get("connection")
        _shutdown_sock(connection.sock if connection is not None else None)
        # Bounded grace for cooperative cleanup; a still-blocked daemon is
        # abandoned and will self-clean (without dispatching) on return.
        worker.join(_WORKER_GRACE_SECONDS)
        raise TransportError("timeout")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["response"]


def _http_transport_once(
    request: HttpRequest, expired: threading.Event, shared: dict
) -> HttpResponse:
    parts = urlsplit(request.url)
    host = parts.hostname
    if host is None:
        raise TransportError("invalid_origin")
    deadline = time.monotonic() + request.timeout
    active_socket: list[socket.socket] = []
    connection: http.client.HTTPConnection | None = None

    def interrupt_socket() -> None:
        expired.set()
        sock = active_socket[0] if active_socket else None
        if sock is None and connection is not None:
            sock = connection.sock
        _shutdown_sock(sock)

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0 or expired.is_set():
            raise TransportError("timeout")
        return left

    if parts.scheme == "https":
        connection = http.client.HTTPSConnection(
            host, parts.port, timeout=request.timeout
        )
    else:
        connection = http.client.HTTPConnection(
            host, parts.port, timeout=request.timeout
        )
    shared["connection"] = connection
    timer = threading.Timer(request.timeout, interrupt_socket)
    timer.daemon = True
    timer.start()
    try:
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        # Explicit connect separates the (possibly uninterruptible) DNS /
        # connect stage from dispatch. Checking the deadline immediately
        # after it returns -- and requiring an assigned socket -- means a
        # connection that only completes after expiry is closed without
        # sending anything, and ``request()`` below cannot auto-reconnect
        # (http.client only connects when ``sock is None``).
        connection.connect()
        remaining()
        if connection.sock is None:
            raise TransportError("network_error")
        active_socket.append(connection.sock)
        connection.sock.settimeout(remaining())
        connection.request(
            request.method, target, body=request.body, headers=request.headers
        )
        remaining()
        if connection.sock is not None:
            if not active_socket:
                active_socket.append(connection.sock)
            connection.sock.settimeout(remaining())
        response = connection.getresponse()
        remaining()
        headers = {key.lower(): value for key, value in response.getheaders()}
        raw = bytearray()
        while len(raw) <= MAX_RESPONSE_BYTES:
            if connection.sock is not None:
                connection.sock.settimeout(remaining())
            else:
                remaining()
            chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        remaining()
        return HttpResponse(status=response.status, headers=headers, body=bytes(raw))
    except TransportError:
        raise
    except (TimeoutError, http.client.HTTPException, OSError) as exc:
        if (
            expired.is_set()
            or time.monotonic() >= deadline
            or isinstance(exc, TimeoutError)
            or "timed out" in str(exc).lower()
        ):
            raise TransportError("timeout") from None
        raise TransportError("network_error") from None
    finally:
        timer.cancel()
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def _normalize_origin(raw: str) -> str | None:
    if not raw or raw != raw.strip() or any(ch.isspace() for ch in raw):
        return None
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    if parts.username is not None or parts.password is not None:
        return None
    if not parts.hostname:
        return None
    if parts.query or parts.fragment:
        return None
    if parts.path not in ("", "/"):
        return None
    host = parts.hostname.lower()
    display_host = f"[{host}]" if ":" in host else host
    origin = f"{parts.scheme}://{display_host}"
    if port is not None:
        origin += f":{port}"
    return origin


def _load_credential(env, credential_file: str | None) -> tuple[str | None, str | None]:
    """Return (token, error_code). Token is never logged."""

    if credential_file is not None:
        try:
            path = Path(credential_file)
            if path.stat().st_size > MAX_CREDENTIAL_BYTES:
                return None, "credential_invalid"
            raw = path.read_bytes()
        except OSError:
            return None, "credential_unavailable"
        if len(raw) > MAX_CREDENTIAL_BYTES:
            return None, "credential_invalid"
        try:
            token = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            return None, "credential_invalid"
    else:
        token = (env.get(CREDENTIAL_ENV_VAR) or "").strip()
        if not token:
            return None, "credential_missing"
    if not token or any(ch.isspace() for ch in token):
        return None, "credential_invalid"
    return token, None


def _safe_http_error_code(response: HttpResponse) -> str:
    if response.status in (301, 302, 303, 307, 308):
        return "redirect_rejected"
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        code = payload.get("code")
        if isinstance(code, str) and code in _SAFE_ERROR_CODES:
            return code
    if response.status in (401, 403):
        return "unauthorized"
    if response.status == 404:
        return "not_found"
    if response.status == 409:
        return "stale_version"
    if response.status == 429:
        return "rate_limit"
    if response.status == 504:
        return "timeout"
    return "http_error"


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="python -m forma_api.demo_smoke",
        description=(
            "Read-only connected-demo smoke checks (health, project, "
            "design readiness, media eligibility). Live intake requires "
            "--live-intake and --transfer-consent. Live diagnosis requires "
            "--live-diagnosis, --transfer-consent and --problem, and proves "
            "only one provider response for that photo, not physical repair "
            "success. Example: python -m forma_api.demo_smoke "
            "--project-id project-abc --media-id media-abc --live-diagnosis "
            "--transfer-consent --problem 'The leg split at the slot'"
        ),
    )
    parser.add_argument("--api-origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--media-id", default=None)
    parser.add_argument("--credential-file", default=None)
    live_group = parser.add_mutually_exclusive_group()
    live_group.add_argument("--live-intake", action="store_true")
    live_group.add_argument("--live-diagnosis", action="store_true")
    parser.add_argument("--problem", default=None)
    parser.add_argument("--operation-id", default=None)
    parser.add_argument(
        "--transfer-consent",
        "--provider-transfer-consent",
        action="store_true",
        dest="transfer_consent",
    )
    return parser


def _initial_report(origin: str | None) -> dict:
    return {
        "status": "failed",
        "api_origin": origin,
        "health": {"status": "not_checked"},
        "project": {"status": "not_checked"},
        "media": {"status": "not_checked"},
        "design_readiness": {"status": "not_checked"},
        "intake": {"status": "not_requested"},
        "diagnosis": {"status": "not_requested"},
        "physical_verification": "not_checked",
        "measurements": "unknown",
        "errors": [],
    }


def _fail(report: dict, check: str, code: str, http_status: int | None = None) -> None:
    error: dict = {"check": check, "code": code}
    if http_status is not None:
        error["http_status"] = http_status
    report["errors"].append(error)


def run(argv=None, *, env=None, transport=None, out: TextIO | None = None) -> int:
    """Execute the smoke checks and write one redacted JSON report."""

    env = os.environ if env is None else env
    transport = _http_transport if transport is None else transport
    out = sys.stdout if out is None else out

    try:
        args = _build_parser().parse_args(argv)
    except _ArgumentError:
        report = _initial_report(None)
        _fail(report, "arguments", "invalid_arguments")
        print(json.dumps(report, sort_keys=True), file=out)
        return 2
    except SystemExit as exc:  # --help
        return int(exc.code or 0)

    origin = _normalize_origin(args.api_origin)
    report = _initial_report(origin)

    def emit(code: int) -> int:
        report["status"] = "ok" if code == 0 else "failed"
        print(json.dumps(report, sort_keys=True), file=out)
        return code

    # --- Preflight validation: no request is made on any failure here. ---
    if origin is None:
        _fail(report, "arguments", "invalid_origin")
        return emit(2)
    if not (MIN_TIMEOUT_SECONDS <= args.timeout <= MAX_TIMEOUT_SECONDS):
        _fail(report, "arguments", "invalid_timeout")
        return emit(2)
    if args.project_id is not None and not _ID_RE.match(args.project_id):
        _fail(report, "arguments", "invalid_project_id")
        return emit(2)
    if args.media_id is not None and not _ID_RE.match(args.media_id):
        _fail(report, "arguments", "invalid_media_id")
        return emit(2)
    if args.media_id is not None and args.project_id is None:
        _fail(report, "arguments", "project_required_for_media")
        return emit(2)
    if args.live_intake:
        if args.project_id is None or args.media_id is None:
            _fail(report, "arguments", "live_intake_requires_project_and_media")
            return emit(2)
        if not args.transfer_consent:
            # Missing consent rejects before any request, including health.
            _fail(report, "intake", "consent_required")
            return emit(2)
    if args.operation_id is not None and not _ID_RE.match(args.operation_id):
        _fail(report, "arguments", "invalid_operation_id")
        return emit(2)
    problem: str | None = None
    if args.live_diagnosis:
        if args.project_id is None or args.media_id is None:
            _fail(report, "arguments", "live_diagnosis_requires_project_and_media")
            return emit(2)
        if not args.transfer_consent:
            _fail(report, "diagnosis", "consent_required")
            return emit(2)
        if args.problem is None:
            _fail(report, "arguments", "live_diagnosis_requires_problem")
            return emit(2)
        problem = args.problem.strip()
        if not 1 <= len(problem) <= MAX_REPORTED_PROBLEM_LENGTH:
            _fail(report, "arguments", "invalid_problem")
            return emit(2)
    else:
        if args.problem is not None:
            _fail(report, "arguments", "problem_requires_live_diagnosis")
            return emit(2)
        if args.operation_id is not None:
            _fail(report, "arguments", "operation_id_requires_live_diagnosis")
            return emit(2)
    # Consent alone (--transfer-consent without a live flag) never
    # triggers inference.

    needs_credential = args.project_id is not None
    token: str | None = None
    credential_error: str | None = None
    if needs_credential:
        token, credential_error = _load_credential(env, args.credential_file)
        if credential_error is not None and (args.live_intake or args.live_diagnosis):
            _fail(report, "credential", credential_error)
            return emit(2)

    timeout = float(args.timeout)

    def request(method: str, path: str, body: bytes | None = None) -> HttpResponse:
        headers = {"Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        return transport(
            HttpRequest(
                method=method,
                url=origin + path,
                headers=headers,
                body=body,
                timeout=timeout,
            )
        )

    def checked_request(check: str, method: str, path: str, body=None):
        """Return parsed-success response or None after recording failure."""

        try:
            response = request(method, path, body)
        except TransportError as exc:
            _fail(report, check, exc.code)
            return None
        except Exception:
            _fail(report, check, "network_error")
            return None
        if len(response.body) > MAX_RESPONSE_BYTES:
            _fail(report, check, "response_too_large")
            return None
        if response.status in (301, 302, 303, 307, 308):
            _fail(report, check, "redirect_rejected", response.status)
            return None
        if not 200 <= response.status < 300:
            _fail(report, check, _safe_http_error_code(response), response.status)
            return None
        return response

    # --- Health (read-only). ---
    response = checked_request("health", "GET", "/api/health")
    if response is None:
        report["health"] = {"status": "failed"}
        return emit(1)
    try:
        health = HealthResponse.model_validate_json(response.body)
    except ValidationError:
        report["health"] = {"status": "failed"}
        _fail(report, "health", "invalid_response")
        return emit(1)
    report["health"] = {"status": health.status}

    if args.project_id is None:
        return emit(0)

    # --- Saved project (owner-authorized, read-only). ---
    if credential_error is not None:
        report["project"] = {"status": "failed"}
        _fail(report, "credential", credential_error)
        return emit(1)
    response = checked_request("project", "GET", f"/api/projects/{args.project_id}")
    if response is None:
        report["project"] = {"status": "failed"}
        return emit(1)
    try:
        project: Project = Project.model_validate_json(response.body)
    except ValidationError:
        report["project"] = {"status": "failed"}
        _fail(report, "project", "invalid_response")
        return emit(1)
    if project.id != args.project_id:
        report["project"] = {"status": "failed"}
        _fail(report, "project", "invalid_response")
        return emit(1)
    report["project"] = {
        "status": "ok",
        "project_id": project.id,
        "revision_id": project.revision_id,
        "inventory_confirmed": project.inventory_confirmed,
        "active_version_present": project.active_version_id is not None,
        "stock_count": len(project.stocks),
    }

    # Operation scope requires an active plan; refuse before any POST.
    if args.live_diagnosis and args.operation_id is not None:
        if project.active_version_id is None:
            report["diagnosis"] = {"status": "failed"}
            _fail(report, "diagnosis", "active_plan_required")
            return emit(1)

    # --- Design readiness (read-only; safe fields only). ---
    response = checked_request(
        "design_readiness", "GET", f"/api/projects/{args.project_id}/designs/readiness"
    )
    if response is None:
        report["design_readiness"] = {"status": "failed"}
        return emit(1)
    try:
        readiness = DesignReadiness.model_validate_json(response.body)
    except ValidationError:
        report["design_readiness"] = {"status": "failed"}
        _fail(report, "design_readiness", "invalid_response")
        return emit(1)
    if (
        readiness.project_id != args.project_id
        or readiness.inventory_revision_id != project.revision_id
    ):
        report["design_readiness"] = {"status": "failed"}
        _fail(report, "design_readiness", "invalid_response")
        return emit(1)
    blocker_codes = [blocker.code for blocker in readiness.blockers]
    report["design_readiness"] = {
        "status": readiness.status,
        "ready": readiness.status == "inputs_complete",
        "inventory_confirmed": readiness.inventory_confirmed,
        "blocker_codes": blocker_codes,
        "blocker_count": len(blocker_codes),
        "missing_input_count": len(readiness.missing_inputs),
        "counts": {
            "blockers": len(blocker_codes),
            "missing_inputs": len(readiness.missing_inputs),
        },
    }

    if args.media_id is None:
        return emit(0 if not (args.live_intake or args.live_diagnosis) else 1)

    # --- Saved media eligibility (metadata only; no bytes downloaded). ---
    response = checked_request("media", "GET", f"/api/projects/{args.project_id}/media")
    if response is None:
        report["media"] = {"status": "failed"}
        return emit(1)
    try:
        media_list = MediaList.model_validate_json(response.body)
    except ValidationError:
        report["media"] = {"status": "failed"}
        _fail(report, "media", "invalid_response")
        return emit(1)
    selected = next((m for m in media_list.media if m.id == args.media_id), None)
    if selected is None:
        report["media"] = {"status": "failed", "media_id": args.media_id}
        _fail(report, "media", "not_found")
        return emit(1)
    if selected.project_id != args.project_id:
        # Foreign/scoped metadata: never report eligibility or POST intake,
        # and never surface the other project's details.
        report["media"] = {"status": "failed", "media_id": args.media_id}
        _fail(report, "media", "invalid_response")
        return emit(1)
    eligible = (
        selected.content_type in SUPPORTED_IMAGE_TYPES
        and 0 < selected.byte_count <= MAX_PROVIDER_IMAGE_BYTES
    )
    report["media"] = {
        "status": "ok" if eligible else "ineligible",
        "media_id": selected.id,
        "content_type": selected.content_type,
        "byte_count": selected.byte_count,
        "eligible": eligible,
    }
    if not eligible:
        _fail(report, "media", "media_ineligible")
        return emit(1)

    if not args.live_intake and not args.live_diagnosis:
        return emit(0)

    if args.live_diagnosis:
        # --- Live diagnosis: only here, with consent already verified. ---
        # Media eligibility above already refused ineligible photos with
        # no POST; operation scope was checked against the loaded project.
        report["diagnosis"] = {"status": "not_checked"}
        assert problem is not None  # Validated in preflight.
        diagnosis_payload = DiagnosisRequest(
            media_id=args.media_id,
            expected_revision_id=project.revision_id,
            reported_problem=problem,
            provider_transfer_consented=True,
            expected_active_version_id=(
                project.active_version_id if args.operation_id is not None else None
            ),
            current_operation_id=args.operation_id,
        )
        response = checked_request(
            "diagnosis",
            "POST",
            f"/api/projects/{args.project_id}/diagnose",
            body=diagnosis_payload.model_dump_json().encode(),
        )
        if response is None:
            report["diagnosis"] = {"status": "failed"}
            return emit(1)
        try:
            diagnosis_result = DiagnosisResult.model_validate_json(response.body)
        except ValidationError:
            report["diagnosis"] = {"status": "failed"}
            _fail(report, "diagnosis", "invalid_response")
            return emit(1)
        if (
            diagnosis_result.project_id != args.project_id
            or diagnosis_result.media_id != args.media_id
            or diagnosis_result.revision_id != project.revision_id
            or (
                args.operation_id is not None
                and (
                    diagnosis_result.current_operation_id != args.operation_id
                    or diagnosis_result.active_version_id != project.active_version_id
                )
            )
        ):
            report["diagnosis"] = {"status": "failed"}
            _fail(report, "diagnosis", "invalid_response")
            return emit(1)
        proposal = diagnosis_result.diagnosis
        diag = diagnosis_result.diagnostics
        counts = {
            "visible_observations": len(proposal.visible_observations),
            "hypotheses": len(proposal.hypotheses),
            "questions_or_measurements": len(proposal.questions_or_measurements),
            "affected_ids": len(proposal.affected_ids),
        }
        usage_report = (
            {
                "model_calls": diag.usage.model_calls,
                "input_tokens": diag.usage.input_tokens,
                "output_tokens": diag.usage.output_tokens,
            }
            if diag.usage is not None
            else None
        )
        report["diagnosis"] = {
            "status": diag.status,
            "failure_type": proposal.failure_type,
            "visible_observations_count": counts["visible_observations"],
            "hypotheses_count": counts["hypotheses"],
            "questions_or_measurements_count": counts["questions_or_measurements"],
            "affected_ids_count": counts["affected_ids"],
            "counts": counts,
            "model": diag.model,
            "elapsed_ms": diag.elapsed_ms,
            "diagnostics": {
                "status": diag.status,
                "model": diag.model,
                "elapsed_ms": diag.elapsed_ms,
                "usage": usage_report,
            },
            "usage": usage_report,
            "live_provider_call": True,
        }
        return emit(0)

    # --- Live intake: only here, with explicit consent already verified. ---
    report["intake"] = {"status": "not_checked"}
    payload = IntakeRequest(
        media_id=args.media_id,
        expected_revision_id=project.revision_id,
        provider_transfer_consented=True,
    )
    response = checked_request(
        "intake",
        "POST",
        f"/api/projects/{args.project_id}/intake",
        body=payload.model_dump_json().encode(),
    )
    if response is None:
        report["intake"] = {"status": "failed"}
        return emit(1)
    try:
        result = IntakeResult.model_validate_json(response.body)
    except ValidationError:
        report["intake"] = {"status": "failed"}
        _fail(report, "intake", "invalid_response")
        return emit(1)
    if (
        result.project_id != args.project_id
        or result.media_id != args.media_id
        or result.revision_id != project.revision_id
    ):
        report["intake"] = {"status": "failed"}
        _fail(report, "intake", "invalid_response")
        return emit(1)
    diagnostics = result.diagnostics
    intake_report: dict = {
        "status": diagnostics.status,
        "model": diagnostics.model,
        "elapsed_ms": diagnostics.elapsed_ms,
        "label_count": len(result.observation.labels),
        "question_count": len(result.observation.questions),
        "measurement_source": result.observation.measurement_source,
    }
    if diagnostics.usage is not None:
        intake_report["usage"] = {
            "model_calls": diagnostics.usage.model_calls,
            "input_tokens": diagnostics.usage.input_tokens,
            "output_tokens": diagnostics.usage.output_tokens,
        }
    else:
        intake_report["usage"] = None
    report["intake"] = intake_report
    return emit(0)


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
