"""Muse Spark as the only code author. Returns whole-file replacements."""

import json

from budget import Budget
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_OUT = 32000
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


class Muse:
    def __init__(self, transport, budget: Budget, model: str, timeout: float = 240):
        self.transport, self.budget, self.model = transport, budget, model
        self.timeout = timeout

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
        result = self.transport.post("/chat/completions", payload, self.timeout)
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
