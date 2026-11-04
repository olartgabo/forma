"""Explicit, finite server-side synthetic-image intake verification. No retries."""

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from forma_api.intake_runtime import observe_photo
from forma_api.model_gateway import GatewayError, MetaGateway, MetaHTTP

MODEL = "muse-spark-1.3"
MAX_OUTPUT = 4096
MAX_REQUEST_BYTES = 7_000_000
MAX_TEXT_BYTES = 48_000
MAX_INPUT_TOKENS = 64_000
SAFE_FAILURE_CODES = frozenset(
    {
        "timeout",
        "network_error",
        "authentication",
        "access_denied",
        "rate_limit",
        "provider_http_error",
        "invalid_response",
        "response_too_large",
        "runtime_usage_unknown",
    }
)


def now():
    return datetime.now(timezone.utc)


def append(path, event):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": now().isoformat(), **event}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class ReservedTransport:
    def __init__(self, transport, directory, authorization):
        self.transport = transport
        self.directory = directory
        self.authorization = authorization
        self.halted = False
        self.calls = 0

    def post(self, path, payload, timeout):
        if self.halted or self.calls >= self.authorization["max_calls"]:
            raise GatewayError("runtime_run_halted")
        if now() >= datetime.fromisoformat(self.authorization["expires_at"]):
            raise GatewayError("runtime_window_expired")
        if path != "/chat/completions" or payload.get("model") != MODEL:
            raise GatewayError("runtime_scope_violation")
        if payload.get("tools"):
            raise GatewayError("runtime_scope_violation")
        payload = {**payload, "max_completion_tokens": MAX_OUTPUT}
        encoded = json.dumps(payload).encode()
        text_payload = json.dumps(payload, default=str)
        # Exclude image bytes from textual context accounting; image bytes have
        # a separate bound and reserve the remaining input-token allowance.
        for message in payload.get("messages", []):
            content = message.get("content")
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "image_url":
                        text_payload = text_payload.replace(
                            part.get("image_url", {}).get("url", ""), ""
                        )
        if (
            len(encoded) > MAX_REQUEST_BYTES
            or len(text_payload.encode()) > MAX_TEXT_BYTES
        ):
            raise GatewayError("runtime_input_limit")
        request_id = uuid.uuid4().hex
        append(
            self.directory / "ledger.jsonl",
            {
                "event": "reserved",
                "id": request_id,
                "stage": "intake",
                "model": MODEL,
                "max_input_tokens": MAX_INPUT_TOKENS,
                "max_output_tokens": MAX_OUTPUT,
                "request_bytes": len(encoded),
            },
        )
        self.calls += 1
        start = time.monotonic()
        try:
            result = self.transport.post(path, payload, min(timeout, 30.0))
            usage = result.get("usage", {})
            values = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
            if any(type(value) is not int or value < 0 for value in values):
                raise GatewayError("runtime_usage_unknown")
            append(
                self.directory / "ledger.jsonl",
                {
                    "event": "settled",
                    "id": request_id,
                    "input_tokens": values[0],
                    "output_tokens": values[1],
                    "elapsed_ms": round((time.monotonic() - start) * 1000),
                },
            )
            return result
        except BaseException as exc:
            self.halted = True
            failure = (
                exc.code
                if isinstance(exc, GatewayError) and exc.code in SAFE_FAILURE_CODES
                else "unclassified"
            )
            append(
                self.directory / "ledger.jsonl",
                {
                    "event": "unknown",
                    "id": request_id,
                    "elapsed_ms": round((time.monotonic() - start) * 1000),
                    "action": "halt; reconcile before retry",
                    "failure_code": failure,
                },
            )
            raise GatewayError("runtime_outcome_unknown") from None


def load_key():
    if os.environ.get("MODEL_API_KEY", "").strip():
        return os.environ["MODEL_API_KEY"]
    key_path = Path.home() / ".meta-budget" / "key.dpapi"
    if not key_path.is_file():
        raise GatewayError("missing_key")
    # The existing user-bound encrypted credential is decrypted only into
    # this private subprocess pipe and process memory. Never log the pipe.
    script = (
        "$s=Get-Content -Raw -LiteralPath '"
        + str(key_path).replace("'", "''")
        + "' | ConvertTo-SecureString; "
        "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); "
        "try {[Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))} "
        "finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode or not result.stdout.strip():
        raise GatewayError("missing_key")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("explicit --live required")
    image = args.image.read_bytes()
    if not 0 < len(image) <= 5_000_000:
        parser.error("image outside byte limit")
    content_type = (
        "image/png" if image.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
    )
    if content_type == "image/jpeg" and not image.startswith(b"\xff\xd8\xff"):
        parser.error("PNG or JPEG required")
    key = load_key()
    # A consumed run directory cannot be reused, restarted or renewed.
    args.output.mkdir(parents=True, exist_ok=False)
    authorization = {
        "authorization_date": "2026-11-04",
        "stage": "intake",
        "model": MODEL,
        "classification": "SYNTHETIC reference image; no physical validation or recognition coverage claim",
        "max_calls": 1,
        "max_input_tokens": MAX_INPUT_TOKENS,
        "max_output_tokens": MAX_OUTPUT,
        "max_image_bytes": 5_000_000,
        "starts_at": now().isoformat(),
        "expires_at": (now() + timedelta(hours=1)).isoformat(),
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "automatic_retries": 0,
        "historical_unknowns": "preserved; not settled by this run",
    }
    append(args.output / "ledger.jsonl", {"event": "authorization", **authorization})
    transport = ReservedTransport(MetaHTTP(key), args.output, authorization)
    gateway = MetaGateway(
        transport, spark=MODEL, max_rounds=1, max_retries=0, timeout=30
    )
    try:
        observation, diagnostics = observe_photo(
            gateway,
            project_goal="SYNTHETIC material reference image software test. Identify candidate objects only; all measurements, composition, stock and physical results remain unknown.",
            image_data=image,
            content_type=content_type,
        )
        report = {
            "status": "ok",
            "classification": authorization["classification"],
            "observation": observation.model_dump(mode="json"),
            "diagnostics": diagnostics.model_dump(mode="json"),
            "calls": transport.calls,
        }
    except GatewayError as exc:
        report = {
            "status": exc.code,
            "calls": transport.calls,
            "classification": authorization["classification"],
        }
    append(args.output / "result.jsonl", report)
    print(json.dumps({"status": report["status"], "calls": transport.calls}))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
