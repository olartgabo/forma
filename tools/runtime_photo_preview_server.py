"""One finite, loopback-only photo-preview run; all provider attempts are journaled."""

import argparse
import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from fastapi.responses import JSONResponse

from forma_api import design_runtime
from forma_api.main import create_app
from forma_api.model_gateway import GatewayError, MetaGateway, MetaHTTP

MODEL = "muse-spark-1.3"
MAX_CALLS = 4
INPUT_RESERVATION = 64_000
OUTPUT_LIMIT = 8_192


def now():
    return datetime.now(timezone.utc)


def append(path, event):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": now().isoformat(), **event}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def restrict_routes(app):
    """Expose only the mutations needed by this isolated preview run."""

    @app.middleware("http")
    async def bounded_routes(request, call_next):
        path = request.url.path
        allowed_write = request.method == "POST" and (
            path == "/api/projects"
            or re.fullmatch(r"/api/projects/[^/]+/(?:media|construction/propose)", path)
        )
        if request.method not in ("GET", "HEAD", "OPTIONS") and not allowed_write:
            return JSONResponse(
                {"detail": "Outside the bounded preview run"}, status_code=403
            )
        return await call_next(request)


class GuardedTransport:
    def __init__(self, transport, directory, expires_at):
        self.transport = transport
        self.directory = directory
        self.expires_at = expires_at
        self.lock = threading.Lock()
        self.calls = 0
        self.halted = False

    def post(self, path, payload, timeout):
        schema = (
            payload.get("response_format", {}).get("json_schema", {}).get("schema", {})
        )
        if (
            path != "/chat/completions"
            or payload.get("model") != MODEL
            or schema.get("title") != "ApproximateProposals"
            or payload.get("tools")
        ):
            raise GatewayError("runtime_scope_violation")
        payload = {**payload, "max_completion_tokens": OUTPUT_LIMIT}
        encoded = json.dumps(payload).encode()
        text = json.dumps(payload, default=str)
        for message in payload.get("messages", []):
            for part in (
                message.get("content", [])
                if isinstance(message.get("content"), list)
                else []
            ):
                if part.get("type") == "image_url":
                    text = text.replace(part.get("image_url", {}).get("url", ""), "")
        if len(encoded) > 7_000_000 or len(text.encode()) > 48_000:
            raise GatewayError("runtime_input_limit")
        with self.lock:
            if self.halted or self.calls >= MAX_CALLS:
                raise GatewayError("runtime_run_halted")
            if now() >= self.expires_at:
                raise GatewayError("runtime_window_expired")
            request_id = uuid.uuid4().hex
            append(
                self.directory / "ledger.jsonl",
                {
                    "event": "reserved",
                    "id": request_id,
                    "stage": "approximate_construction",
                    "model": MODEL,
                    "max_input_tokens_reservation": INPUT_RESERVATION,
                    "max_output_tokens": OUTPUT_LIMIT,
                    "request_bytes": len(encoded),
                },
            )
            self.calls += 1
            # Serialize attempts so an unknown result always halts the whole run.
            started = time.monotonic()
            try:
                remaining = (self.expires_at - now()).total_seconds()
                if remaining <= 0:
                    raise GatewayError("runtime_window_expired")
                result = self.transport.post(path, payload, min(timeout, remaining))
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
                        "elapsed_ms": round((time.monotonic() - started) * 1000),
                    },
                )
                return result
            except BaseException:
                self.halted = True
                append(
                    self.directory / "ledger.jsonl",
                    {
                        "event": "unknown",
                        "id": request_id,
                        "elapsed_ms": round((time.monotonic() - started) * 1000),
                        "action": "halt; reconcile before retry",
                    },
                )
                raise GatewayError("network_error") from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8017)
    parser.add_argument("--aws-profile", default=os.environ.get("AWS_PROFILE"))
    args = parser.parse_args()
    token = os.environ.get("FORMA_RUNTIME_OWNER_TOKEN", "")
    if len(token) < 32:
        parser.error(
            "FORMA_RUNTIME_OWNER_TOKEN must be set to a private value of at least 32 characters"
        )
    # stdout remains in this private pipe and is never included in logs or errors.
    result = subprocess.run(
        [
            "aws",
            "ssm",
            "get-parameter",
            "--name",
            "/forma/model-api-key",
            "--with-decryption",
            "--region",
            "us-east-1",
            "--query",
            "Parameter.Value",
            "--output",
            "text",
            "--no-cli-pager",
        ]
        + (["--profile", args.aws_profile] if args.aws_profile else []),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode or not result.stdout.strip():
        parser.error(
            "Provider credential unavailable from the configured local AWS profile"
        )
    key = result.stdout.strip()
    # The key remains in this loopback server process for its configuration check.
    os.environ["MODEL_API_KEY"] = key
    args.output.mkdir(parents=True, exist_ok=False)
    expires = now() + timedelta(minutes=30)
    append(
        args.output / "ledger.jsonl",
        {
            "event": "authorization",
            "stage": "approximate_construction",
            "model": MODEL,
            "max_calls": MAX_CALLS,
            "input_tokens_reservation_per_call": INPUT_RESERVATION,
            "input_limit_note": "reservation, not a provider-enforced token ceiling",
            "max_output_tokens_per_call": OUTPUT_LIMIT,
            "max_request_bytes": 7_000_000,
            "max_text_bytes": 48_000,
            "expires_at": expires.isoformat(),
            "automatic_retries": 0,
        },
    )
    transport = GuardedTransport(MetaHTTP(key), args.output, expires)
    design_runtime.default_gateway_factory = lambda: MetaGateway(
        transport, spark=MODEL, max_rounds=1, max_retries=0, timeout=60, budget=60
    )
    app = create_app(data_dir=args.output / "data", credentials={"runtime": token})
    restrict_routes(app)
    uvicorn.run(
        app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False
    )


if __name__ == "__main__":
    main()
