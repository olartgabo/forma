"""Muse Spark as the only code author. Returns whole-file replacements."""

import http.client
import json
import socket
import time

from budget import Budget
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_OUT = 24000
TRANSIENT = ("timeout", "network_error", "rate_limit", "provider_http_error")
BACKOFF = (15, 60)  # seconds between retries of transient Meta errors
SYSTEM = (
    "You are the programmer on the FORMA repository. Write production-quality, "
    "formatted Python/TypeScript matching the repository style. Follow AGENTS.md: "
    "no dead code, no swallowed errors, no invented measurements or test results. "
    "Return complete file contents for every file you change, plus tests. "
    "Only change files listed in files_allowed."
)


class FileEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=200_000)


class MuseChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=2000)
    commit_message: str = Field(min_length=1, max_length=200)
    files: list[FileEdit] = Field(min_length=1, max_length=12)


class MuseError(Exception):
    pass


class MetaError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code} {detail}".strip())


class DevMetaHTTP:
    """Dev-only Meta client: long timeout, and errors keep the HTTP status and
    a short body excerpt for diagnosis. The key never appears in errors."""

    def __init__(self, api_key: str):
        if not api_key.strip():
            raise MetaError("missing_key")
        self._key = api_key

    def post(self, path: str, payload: dict, timeout: float) -> dict:
        conn = http.client.HTTPSConnection("api.meta.ai", timeout=timeout)
        try:
            conn.request(
                "POST",
                "/v1" + path,
                body=json.dumps(payload),
                headers={
                    "Authorization": "Bearer " + self._key,
                    "Content-Type": "application/json",
                },
            )
            response = conn.getresponse()
            raw = response.read()
        except (TimeoutError, socket.timeout):
            raise MetaError("timeout") from None
        except (http.client.HTTPException, OSError) as exc:
            raise MetaError("network_error", type(exc).__name__) from None
        finally:
            conn.close()
        if response.status != 200:
            code = {401: "authentication", 403: "access_denied", 429: "rate_limit"}
            detail = f"HTTP {response.status}: {raw[:300].decode(errors='replace')}"
            raise MetaError(code.get(response.status, "provider_http_error"), detail)
        return json.loads(raw)


class Muse:
    def __init__(self, transport, budget: Budget, model: str, timeout: float = 240):
        self.transport, self.budget, self.model = transport, budget, model
        self.timeout, self.sleep = timeout, time.sleep

    def _post(self, payload: dict) -> dict:
        for delay in (*BACKOFF, None):
            try:
                return self.transport.post("/chat/completions", payload, self.timeout)
            except Exception as exc:
                code = getattr(exc, "code", None)
                if code not in TRANSIENT:
                    raise
                if delay is None:
                    # Persistent errors fail this attempt, not the whole loop.
                    raise MuseError(f"Meta {str(exc)[:300]} after retries") from None
                print(f"  Meta {str(exc)[:300]}; retrying in {delay}s")
                self.sleep(delay)

    def write(
        self, spec: dict, files: dict[str, str], feedback: str = ""
    ) -> MuseChange:
        user = json.dumps(
            {"task_spec": spec, "current_files": files, "reviewer_feedback": feedback}
        )
        # 3 chars per token over-estimates prompt size, keeping the cap safe.
        self.budget.reserve(len(SYSTEM + user) // 3 + 1, MAX_OUT)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": MAX_OUT,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "change",
                    "schema": MuseChange.model_json_schema(),
                },
            },
        }
        result = self._post(payload)
        usage = result.get("usage") or {}
        pt, ct = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if not (isinstance(pt, int) and isinstance(ct, int)):
            # Unknown usage is charged at the reserved worst case.
            pt, ct = len(SYSTEM + user) // 3 + 1, MAX_OUT
        self.budget.record(self.model, pt, ct)
        try:
            content = result["choices"][0]["message"]["content"]
            return MuseChange.model_validate_json(content)
        except (KeyError, IndexError, TypeError, ValidationError) as exc:
            raise MuseError(f"invalid Muse output: {exc}") from None
