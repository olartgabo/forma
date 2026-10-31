"""Muse writes the code, Claude specs and judges. Runs in its own git worktree.

Stops when the Meta budget is spent, Claude usage runs out, or no work remains.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from budget import Budget, BudgetExhausted
from judge import ClaudeLimitReached, Goals, Judge, JudgeError, Review, TaskSpec, Triage
from muse import Muse, MuseError
from scope import ScopeError, check_path, touches_contract

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / ".devloop"
WORKTREE = STATE_DIR / "worktree"
REPAIRS = 3  # AGENTS.md: repair candidates capped at three
MAX_FILE = 60_000
SENIOR, JUNIOR = "opus", "sonnet"
LOOP_LABEL = "loop-proposed"
PARTNER = "olartgabo"


def sh(*cmd: str, cwd: Path = WORKTREE, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{proc.stdout}{proc.stderr}")
    return proc.stdout + proc.stderr


def gh_json(*args: str) -> list[dict]:
    return json.loads(sh("gh", *args, cwd=ROOT) or "[]")


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {"blocked": []}
        self.visited: set[str] = set()  # one pass per item per run

    def block(self, key: str):
        self.data["blocked"].append(key)
        self.path.write_text(json.dumps(self.data, indent=2))

    def blocked(self, key: str) -> bool:
        return key in self.data["blocked"] or key in self.visited


def prepare_worktree():
    sh("git", "fetch", "origin", cwd=ROOT)
    if not WORKTREE.exists():
        sh("git", "worktree", "add", "--detach", str(WORKTREE), "origin/main", cwd=ROOT)
    sh("git", "config", "core.hooksPath", ".githooks")
    sh("git", "reset", "--hard")
    sh("git", "clean", "-fd")


def next_task(state: State, skip: set[int]) -> dict | None:
    """Your open PRs first, then your open issues without a loop branch PR."""
    prs = gh_json(
        "pr", "list", "--author", "@me", "--state", "open",
        "--json", "number,title,body,headRefName",
    )  # fmt: skip
    for pr in prs:
        if not state.blocked(f"pr#{pr['number']}"):
            return {"kind": "pr", **pr}
    pr_heads = {pr["headRefName"] for pr in prs}
    issues = gh_json(
        "issue", "list", "--assignee", "@me", "--state", "open",
        "--json", "number,title,body",
    )  # fmt: skip
    for issue in issues:
        branch = f"issue/{issue['number']}-loop"
        if (
            branch not in pr_heads
            and issue["number"] not in skip
            and not state.blocked(f"issue#{issue['number']}")
        ):
            return {"kind": "issue", "headRefName": branch, **issue}
    return None


def checkout(task: dict):
    branch = task["headRefName"]
    sh("git", "fetch", "origin")
    if task["kind"] == "pr":
        sh("git", "checkout", "-B", branch, f"origin/{branch}")
        out = sh("git", "merge", "--no-edit", "origin/main", check=False)
        if "CONFLICT" in out:
            sh("git", "merge", "--abort")
            raise RuntimeError("merge conflict with main; needs a human")
    else:
        sh("git", "checkout", "-B", branch, "origin/main")


def read_files(paths: list[str]) -> dict[str, str]:
    files = {}
    for rel in paths:
        path = WORKTREE / rel
        if path.is_file():
            files[rel] = path.read_text(encoding="utf-8")[:MAX_FILE]
    return files


def run_checks(contract: bool) -> tuple[bool, str]:
    cmds = [
        ["uv", "run", "--locked", "ruff", "format", "."],
        ["uv", "run", "--locked", "ruff", "check", "."],
        ["uv", "run", "--locked", "pytest", "-q"],
    ]
    if contract:
        cmds.append(["npm", "run", "contracts:check"])
    log, ok = [], True
    for cmd in cmds:
        proc = subprocess.run(cmd, cwd=WORKTREE, capture_output=True, text=True)
        tail = (proc.stdout + proc.stderr)[-4000:]
        log.append(f"$ {' '.join(cmd)}  -> exit {proc.returncode}\n{tail}")
        ok = ok and proc.returncode == 0
    return ok, "\n".join(log)


def partner_context() -> str:
    prs = gh_json(
        "pr", "list", "--author", PARTNER, "--json", "number,title,headRefName"
    )
    return json.dumps(prs)


def work_on(task: dict, judge: Judge, muse: Muse, dry_run: bool) -> str:
    checkout(task)
    brief = (
        f"Task: {task['kind']} #{task['number']}: {task['title']}\n\n{task['body']}\n\n"
        f"Branch diff vs main:\n{sh('git', 'diff', '--stat', 'origin/main...HEAD')}\n"
        f"Partner PRs (read-only context, never edit their files): {partner_context()}"
    )
    triage = judge.ask(JUNIOR, "Rate the difficulty of this task.\n" + brief, Triage)
    model = SENIOR if triage.difficulty == "hard" else JUNIOR
    spec = judge.ask(
        model,
        "Write the next concrete, reviewable step that polishes or finishes this "
        "task as a TaskSpec for the Muse programmer. Explore the repo first.\n" + brief,
        TaskSpec,
    )
    allowed = [check_path(p) for p in spec.files_allowed]
    contract = touches_contract(allowed)
    if contract:
        model = SENIOR
    feedback = ""
    for attempt in range(1 + REPAIRS):
        files = read_files(allowed + spec.files_to_read)
        change = muse.write(spec.model_dump(), files, feedback)
        for edit in change.files:
            if check_path(edit.path) not in allowed:
                raise ScopeError(f"Muse wrote unlisted file {edit.path}")
            target = WORKTREE / edit.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit.content, encoding="utf-8", newline="\n")
        ok, checks = run_checks(contract)
        diff = sh("git", "diff") + sh("git", "status", "--short")
        review = judge.ask(
            model,
            f"Review Muse's change for this spec.\nSpec: {spec.model_dump_json()}\n"
            f"Diff:\n{diff[:80_000]}\nChecks:\n{checks}",
            Review,
        )
        print(f"  attempt {attempt + 1}: checks={'pass' if ok else 'fail'} "
              f"review={review.verdict}")  # fmt: skip
        if ok and review.verdict == "approve":
            return commit(task, change.commit_message, change.summary, checks, dry_run)
        feedback = review.feedback + ("" if ok else f"\nFailing checks:\n{checks}")
    sh("git", "reset", "--hard")
    sh("git", "clean", "-fd")
    raise JudgeError(
        f"no approved change after {1 + REPAIRS} attempts: {feedback[:1500]}"
    )


def commit(task, message, summary, checks, dry_run) -> str:
    sh("git", "add", "-A")
    if dry_run:
        diff = sh("git", "diff", "--cached", "--stat")
        sh("git", "reset", "--hard")
        return f"dry run, not committed:\n{diff}"
    sh("git", "commit", "-m", message)
    sh("git", "push", "-u", "origin", task["headRefName"])
    body = (
        f"## Problem and behavior\n\n{summary}\n\nRefs #{task['number']}\n\n"
        f"## Validation\n\nOffline checks run by the dev loop:\n\n```\n"
        f"{checks[-3000:]}\n```\n\nLive provider calls and physical evidence: "
        "not run.\n\n## Handoff\n\nCode written by Muse Spark; reviewed before commit."
    )
    if task["kind"] == "issue":
        sh("gh", "pr", "create", "--draft", "--title", task["title"], "--body", body,
           "--head", task["headRefName"], "--base", "main")  # fmt: skip
        return "opened draft PR"
    sh("gh", "pr", "comment", str(task["number"]), "--body", body)
    return "pushed to PR"


def propose_goals(judge: Judge, dry_run: bool) -> int:
    goals = judge.ask(
        SENIOR,
        "All of @ResniDev's open work is done or blocked. Compare formspec.md, "
        "docs/development.md and the current code. Propose up to 3 new, small, "
        "high-value issues for @ResniDev's lane with acceptance criteria. Return "
        "none if nothing worthwhile remains.",
        Goals,
    )
    if not dry_run:
        sh("gh", "label", "create", LOOP_LABEL, "--force",
           "--description", "Proposed by the dev loop", cwd=ROOT)  # fmt: skip
    for issue in goals.issues:
        print(f"  new goal: {issue.title}")
        if not dry_run:
            sh("gh", "issue", "create", "--title", issue.title, "--body", issue.body,
               "--label", LOOP_LABEL, "--assignee", "@me", cwd=ROOT)  # fmt: skip
    return len(goals.issues)


def report_block(task: dict, reason: str, dry_run: bool):
    print(f"  blocked: {reason[:300]}")
    if not dry_run:
        kind = "pr" if task["kind"] == "pr" else "issue"
        sh("gh", kind, "comment", str(task["number"]), "--body",
           f"Dev loop stopped on this item:\n\n```\n{reason[:3000]}\n```", cwd=ROOT)  # fmt: skip


def build_budget() -> Budget:
    try:
        price_in = float(os.environ["MUSE_PRICE_IN_PER_MTOK"])
        price_out = float(os.environ["MUSE_PRICE_OUT_PER_MTOK"])
    except (KeyError, ValueError):
        sys.exit("Set MUSE_PRICE_IN_PER_MTOK and MUSE_PRICE_OUT_PER_MTOK (USD).")
    cap = float(os.environ.get("DEVLOOP_CAP_USD", "90"))
    return Budget(STATE_DIR / "ledger.jsonl", cap, price_in, price_out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="no commit/push/gh writes"
    )
    parser.add_argument("--max-iterations", type=int, default=0, help="0 = unlimited")
    parser.add_argument(
        "--skip", type=int, nargs="*", default=[17], help="issue numbers to ignore"
    )
    args = parser.parse_args()

    budget = build_budget()
    sys.path.insert(0, str(ROOT / "apps/api/src"))
    from forma_api.model_gateway import GatewayError, MetaHTTP

    muse = Muse(
        MetaHTTP(os.environ.get("MODEL_API_KEY", "")),
        budget,
        os.environ.get("META_SPARK_MODEL", "muse-spark-1.3"),
    )
    STATE_DIR.mkdir(exist_ok=True)
    state, judge = State(STATE_DIR / "state.json"), Judge(str(WORKTREE))
    prepare_worktree()
    iteration = 0
    try:
        while not args.max_iterations or iteration < args.max_iterations:
            iteration += 1
            print(f"[{iteration}] Meta spend ${budget.spent():.2f}/${budget.cap:.2f}")
            task = next_task(state, set(args.skip))
            if task is None:
                if propose_goals(judge, args.dry_run) == 0 or args.dry_run:
                    print("No work left.")
                    return
                continue
            key = f"{task['kind']}#{task['number']}"
            print(f"  working on {key}: {task['title']}")
            try:
                print("  " + work_on(task, judge, muse, args.dry_run))
            except (JudgeError, MuseError, ScopeError, RuntimeError) as exc:
                report_block(task, str(exc), args.dry_run)
                state.block(key)
                sh("git", "reset", "--hard")
                sh("git", "clean", "-fd")
            state.visited.add(key)
    except BudgetExhausted as exc:
        print(f"Stopping: Meta budget reached ({exc}).")
    except ClaudeLimitReached:
        print("Stopping: Claude usage limit reached. Rerun after it resets.")
    except GatewayError as exc:
        print(f"Stopping: Meta API error {exc.code}.")
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        print(f"Meta spend ${budget.spent():.2f}. State in {STATE_DIR}")


if __name__ == "__main__":
    main()
