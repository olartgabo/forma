"""Claude as architect and reviewer via headless `claude -p`. Never writes code."""

import json
import os
import subprocess
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

T = TypeVar("T", bound=BaseModel)
LIMIT_MARKERS = ("usage limit", "rate limit", "limit reached", "429", "overloaded")


class ClaudeLimitReached(Exception):
    pass


class JudgeError(Exception):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskSpec(_Strict):
    goal: str
    files_allowed: list[str] = Field(max_length=12)
    files_to_read: list[str] = Field(max_length=20)
    acceptance_criteria: list[str] = Field(min_length=1)
    design_notes: str
    already_done: bool = False


class Review(_Strict):
    verdict: Literal["approve", "revise"]
    feedback: str


class NewIssue(_Strict):
    title: str = Field(max_length=120)
    body: str


class Goals(_Strict):
    issues: list[NewIssue] = Field(max_length=3)


ROLE = (
    "You are the architect and judge for @ResniDev's lane of FORMA (domain, "
    "compiler, replanner, renderer, model gateway, prompts). Meta Muse is "
    "the programmer and test author; you only plan a feature, review its final "
    "green diff, or diagnose a stuck task after two failed Muse repairs. Never "
    "write implementation or tests. Read AGENTS.md "
    "and formspec.md as needed. Be strict: reject false-green tests, invented "
    "measurements, scope creep and anything outside the lane."
)


def run_claude(
    prompt: str, model: str, schema: dict, cwd: str, effort: str = "medium"
) -> dict:
    cmd = [
        "claude", "-p", prompt,
        "--model", model,
        "--effort", effort,
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--tools", "Read,Grep,Glob",
        "--append-system-prompt", ROLE,
        "--no-session-persistence",
        "--max-turns", "8",
    ]  # fmt: skip
    env = os.environ.copy()
    # Fresh calls avoid accumulating history; retain native compaction if a
    # single planning/review session grows. Do not modify the user's live CLI.
    env.pop("DISABLE_AUTO_COMPACT", None)
    env.pop("DISABLE_COMPACT", None)
    proc = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=1800
    )
    text = proc.stdout + proc.stderr
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        out = None
    if not isinstance(out, dict) or out.get("is_error") or proc.returncode:
        if any(m in text.lower() for m in LIMIT_MARKERS):
            raise ClaudeLimitReached(text[-500:])
        raise JudgeError(text[-1000:])
    structured = out.get("structured_output")
    if structured is None:
        structured = json.loads(out.get("result") or "null")
    return structured


class Judge:
    def __init__(self, cwd: str, runner=run_claude):
        self.cwd, self.runner = cwd, runner

    def ask(
        self, model: str, prompt: str, output: type[T], effort: str = "medium"
    ) -> T:
        raw = self.runner(prompt, model, output.model_json_schema(), self.cwd, effort)
        try:
            return output.model_validate(raw)
        except ValidationError as exc:
            raise JudgeError(f"invalid judge output: {exc}") from None
