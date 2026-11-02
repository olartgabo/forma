# Muse-first feature loop

Current workflow (November 1, 2026):

1. **Plan once.** One premium model (Codex or Claude) plans one coherent
   feature with explicit acceptance criteria, an exact allowlist of source
   and test paths, and any contract decisions. Do not run two planners, and
   reuse a sufficient existing plan instead of buying another call.
2. **Muse implements.** The supervisor writes a small task JSON (`goal`,
   `acceptance_criteria`, `files_allowed`) and launches
   `node tools/devloop/guarded/run.mjs --workspace <approved-worktree> --task-file <task.json>`.
   Muse owns the code, regression tests, execution of the exact offline
   checks allowed by `worker-policy.mjs`, and ordinary repairs. It must not
   weaken tests or oracles to make checks pass. Missing prerequisites are
   blockers.
3. **Repair, then stop.** After two unsuccessful Muse repairs, return STUCK
   with the smallest reproducible failure, files changed, checks run, and a
   concrete question for the planner. One premium diagnosis may follow;
   Muse implements the advice and re-runs the checks. If still stuck,
   checkpoint and stop — no indefinite loops.
4. **Final review.** One premium model reviews the entire green diff,
   including new and untracked tests, against the acceptance criteria and
   actual check output. Review only for correctness, scope and material
   risk. Muse repairs concrete findings; re-review covers those findings and
   their regression impact only, with at most two final-review repair attempts.
5. **Publication is supervisor-only.** The supervisor verifies the final
   reviewed path set and check evidence, then publishes under existing
   authorizations. There is no automatic merge and no physical-evidence
   claim from offline checks.

## Sessions and context

Each worker and each premium plan/review starts a fresh, bounded feature
session from the task packet only; no historical transcripts, resume or
continue. Use task-appropriate context and keep a concise checkpoint (task,
branch, acceptance criteria, owned paths, decisions, actual checks,
failed-repair count, blockers, next action). Native automatic compaction
stays enabled. Muse generation and compaction use the same guarded Meta
provider and accounting. Codex and Claude planning/review use their existing
native subscription sessions and native compaction; they do not share Meta's
guard or free-credit budget. No paid API fallback is implied.

## Budget and stopping

Funding uses verified free credit only: keep at least the $30 free-credit
reserve plus a lag buffer below the verified funding ceiling. Shared
accounting is append-only; STOP, durable reservations, one in-flight
request, and pending/unknown outcomes block further dispatch until resolved.
Billing verification is finite and is never renewed automatically; do not
start while it is expired, STOP is set, accounting is uncertain, or
prerequisites are missing. There is no paid provider fallback and no direct
provider key use.

Offline shell permissions are the exact permitted check commands, not
unrestricted shell. When stopped, save one checkpoint and stay quiet until
a prerequisite changes.

The retired Python engine cannot run: its compatibility entry point always
exits nonzero and directs callers to the guarded Node launcher. Its old
provider client, separate accounting implementation and destructive worktree
cleanup code are removed; historical journals remain outside the repository.
