import json
import shutil
import subprocess
from pathlib import Path

import pytest
from budget import Budget, BudgetExhausted
from judge import ClaudeLimitReached, Judge, JudgeError, Review, run_claude
from muse import Muse, MuseError
from scope import ScopeError, check_path, touches_contract

HOOK = Path(__file__).resolve().parents[3] / ".githooks" / "commit-msg"


def change(path="packages/compiler/src/x.py"):
    return json.dumps(
        {
            "summary": "s",
            "commit_message": "m",
            "files": [{"path": path, "content": "x"}],
        }
    )


class FakeMeta:
    def __init__(self, content, usage=None):
        self.content, self.usage, self.calls = content, usage, 0

    def post(self, path, payload, timeout):
        self.calls += 1
        body = {"choices": [{"message": {"content": self.content}}]}
        if self.usage is not None:
            body["usage"] = self.usage
        return body


def test_budget_records_and_refuses_over_cap(tmp_path):
    budget = Budget(tmp_path / "l.jsonl", 1.0, price_in=10, price_out=10)
    assert budget.record("m", 50_000, 40_000) == pytest.approx(0.9)
    budget.reserve(1000, 9000)  # exactly 1.0
    with pytest.raises(BudgetExhausted):
        budget.reserve(1000, 9001)


def test_budget_rejects_missing_prices(tmp_path):
    with pytest.raises(ValueError):
        Budget(tmp_path / "l.jsonl", 90, 0, 1)


def test_muse_refused_before_call_when_budget_spent(tmp_path):
    budget = Budget(tmp_path / "l.jsonl", 0.01, 1, 1)
    meta = FakeMeta(change())
    with pytest.raises(BudgetExhausted):
        Muse(meta, budget, "muse-spark-1.3").write({}, {})
    assert meta.calls == 0


def test_muse_charges_worst_case_when_usage_missing(tmp_path):
    budget = Budget(tmp_path / "l.jsonl", 90, 1, 1)
    result = Muse(FakeMeta(change()), budget, "muse-spark-1.3").write({}, {})
    assert result.files[0].content == "x"
    assert budget.spent() > 24000 / 1e6


def test_muse_rejects_malformed_output(tmp_path):
    budget = Budget(tmp_path / "l.jsonl", 90, 1, 1)
    meta = FakeMeta("not json", {"prompt_tokens": 10, "completion_tokens": 5})
    with pytest.raises(MuseError):
        Muse(meta, budget, "m").write({}, {})
    assert budget.spent() == pytest.approx(15 / 1e6)  # failed calls still cost


@pytest.mark.parametrize(
    "path",
    [
        "apps/web/src/app/page.tsx",
        "packages/domain/generated/schema.json",
        "uv.lock",
        "../outside.py",
        "/abs/packages/compiler/x.py",
        "packages/compiler/../../apps/web/x.ts",
        "packages/compiler/.env",
        ".github/workflows/checks.yml",
    ],
)
def test_scope_rejects(path):
    with pytest.raises(ScopeError):
        check_path(path)


def test_scope_allows_lane_and_flags_contracts():
    assert check_path("packages\\compiler\\src\\a.py") == "packages/compiler/src/a.py"
    assert touches_contract(["packages/domain/src/forma_domain/x.py"])
    assert not touches_contract(["packages/renderer/src/x.py"])


def test_judge_validates_output():
    judge = Judge(".", runner=lambda *a: {"verdict": "ship it", "feedback": ""})
    with pytest.raises(JudgeError):
        judge.ask("sonnet", "p", Review)
    ok = Judge(".", runner=lambda *a: {"verdict": "approve", "feedback": "fine"})
    assert ok.ask("sonnet", "p", Review).verdict == "approve"


def test_usage_limit_stops(monkeypatch):
    class Proc:
        returncode = 1
        stdout = json.dumps({"is_error": True, "result": "Claude usage limit reached"})
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(ClaudeLimitReached):
        run_claude("p", "sonnet", {}, ".")


def test_judge_fresh_bounded_session_keeps_native_compaction(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTO_COMPACT", "1")
    monkeypatch.setenv("DISABLE_COMPACT", "1")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd, 0, json.dumps({"structured_output": {"verdict": "approve"}}), ""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_claude("review", "sonnet", {}, ".")
    cmd, kwargs = calls[0]
    assert "--no-session-persistence" in cmd
    assert cmd[cmd.index("--max-turns") + 1] == "8"
    assert "--resume" not in cmd and "--continue" not in cmd
    assert "DISABLE_AUTO_COMPACT" not in kwargs["env"]
    assert "DISABLE_COMPACT" not in kwargs["env"]


def test_legacy_entrypoint_stops_before_budget_or_checkout(monkeypatch):
    import devloop

    monkeypatch.setattr("sys.argv", ["devloop", "--dry-run"])
    monkeypatch.setattr(
        devloop, "build_budget", lambda: pytest.fail("must not initialize budget")
    )
    with pytest.raises(SystemExit, match="Legacy runner disabled"):
        devloop.main()


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
@pytest.mark.parametrize(
    "message,rejected",
    [
        ("fix: compiler\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n", True),
        ("fix: compiler\n\nGenerated with [Claude Code]\n", True),
        ("fix: compiler handles claude-shaped stock names\n", False),
        ("fix: compiler\n\nCo-authored-by: Gabo <g@example.com>\n", False),
    ],
)
def test_commit_msg_hook(tmp_path, message, rejected):
    msg = tmp_path / "MSG"
    msg.write_text(message)
    proc = subprocess.run(["sh", str(HOOK), str(msg)], capture_output=True)
    assert (proc.returncode != 0) is rejected


class Flaky(FakeMeta):
    def __init__(self, failures, code):
        super().__init__(change(), {"prompt_tokens": 1, "completion_tokens": 1})
        self.failures, self.code = failures, code

    def post(self, path, payload, timeout):
        if self.failures:
            self.failures -= 1
            exc = Exception(self.code)
            exc.code = self.code
            raise exc
        return super().post(path, payload, timeout)


def test_muse_retries_transient_errors(tmp_path):
    muse = Muse(Flaky(2, "provider_http_error"), Budget(tmp_path / "l", 90, 1, 1), "m")
    muse.sleep = lambda s: None
    assert muse.write({}, {}).files


def test_muse_does_not_retry_auth_errors(tmp_path):
    muse = Muse(Flaky(1, "authentication"), Budget(tmp_path / "l", 90, 1, 1), "m")
    muse.sleep = lambda s: None
    with pytest.raises(Exception, match="authentication"):
        muse.write({}, {})
