import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from judge import ClaudeLimitReached, Judge, JudgeError, Review, run_claude

HOOK = Path(__file__).resolve().parents[3] / ".githooks" / "commit-msg"
DEVLOOP_DIR = Path(__file__).resolve().parents[1]
DEVLOOP = DEVLOOP_DIR / "devloop.py"
RETIRED_MODULES = ("budget", "muse", "scope")


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


def _clean_env():
    env = os.environ.copy()
    for name in list(env):
        if name.startswith(("MODEL_API_KEY", "MUSE_PRICE", "DEVLOOP_", "META_")):
            env.pop(name, None)
    env["PYTHONPATH"] = str(DEVLOOP_DIR)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_importing_devloop_has_no_side_effects(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-c", "import devloop"],
        cwd=tmp_path,
        env=_clean_env(),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert list(tmp_path.iterdir()) == []
    assert not (tmp_path / ".devloop").exists()


def test_importing_devloop_does_not_load_retired_or_effectful_modules(tmp_path):
    code = (
        "import sys, devloop; "
        "bad = [m for m in ('budget', 'muse', 'scope', 'subprocess') "
        "if m in sys.modules]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=_clean_env(),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("module", RETIRED_MODULES)
def test_retired_modules_are_not_importable(module):
    assert importlib.util.find_spec(module) is None


def test_devloop_exposes_no_legacy_dispatch_surface():
    import devloop

    for name in (
        "Budget",
        "Muse",
        "Judge",
        "build_budget",
        "prepare_worktree",
        "next_task",
        "checkout",
        "work_on",
        "commit",
        "propose_goals",
    ):
        assert not hasattr(devloop, name), name


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--dry-run"],
        ["--max-iterations", "1"],
        ["--max-iterations=1"],
        ["--help"],
        ["-h"],
        ["--unknown"],
        ["--skip", "1"],
        ["positional"],
        ["--dry-run", "--unknown-flag"],
    ],
)
def test_every_cli_invocation_fails_closed(tmp_path, args):
    proc = subprocess.run(
        [sys.executable, str(DEVLOOP), *args],
        cwd=tmp_path,
        env=_clean_env(),
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "tools/devloop/guarded/run.mjs" in output
    assert "permanently disabled" in output.lower()
    assert list(tmp_path.iterdir()) == []
    assert not (tmp_path / ".devloop").exists()


def test_main_returns_nonzero_and_directs_to_guarded_launcher(capsys):
    import devloop

    assert devloop.main() == 1
    captured = capsys.readouterr()
    assert "tools/devloop/guarded/run.mjs" in captured.err


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
