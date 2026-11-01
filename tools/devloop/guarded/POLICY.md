# Muse-first feature loop

User direction: November 1, 2026. Supersedes older authorship and per-edit
supervision instructions in OVERNIGHT.md and external loop specifications.

1. Codex OR Claude plans one coherent feature with explicit acceptance criteria,
   source and test paths (12 maximum) and any contract decisions. Do not run two
   planners. Reuse a sufficient existing plan rather than buying another call.
2. Supervisor writes a small task JSON: goal, acceptance_criteria, files_allowed.
   Launch node tools/devloop/guarded/run.mjs --workspace <approved-worktree>
   --task-file <task.json>. Fresh session; no resume/continue flags.
3. Muse writes production code and regression tests, executes the exact offline
   checks allowed by worker-policy.mjs, and repairs failures. Two unsuccessful
   repairs trigger STUCK with a minimal diagnosis packet. Never weaken an oracle
   merely to get green checks. Missing dependencies or permissions are blockers.
4. One premium diagnosis is allowed when stuck, with advice only; Muse implements
   it and runs checks again. If still stuck, checkpoint and stop. No parallel
   premium test author, routine premium debugging, or repeated architecture calls.
5. One Codex OR Claude final reviewer inspects the entire green diff, including
   new/untracked tests, task criteria and actual check results. Review changes
   only for correctness, scope and material risk. Muse repairs concrete findings;
   re-review only those findings and their regression impact (at most two repairs).
6. Supervisor verifies the final reviewed path set and check evidence, then uses
   existing authorized publication rules. No automatic merge or physical claims.

## Context lifecycle

Each worker and each premium plan/review gets a fresh bounded feature session.
Do not feed historical chat transcripts into it. Task packets are capped at 16KB.
Keep a checkpoint below roughly 2,000 words with task/branch/PR, acceptance,
owned paths, decisions, actual checks, failed-repair count, unresolved questions,
budget/expiry references and next action. Replace current state instead of
appending the full chronological log to every prompt. Logs stay on disk and are
read by exact failure reference only when needed.

Muse/OpenCode explicitly enables native automatic compaction and tool-output
pruning with a 10,000-token buffer inside its existing 65,536-token working
window. Both normal and compaction requests use the SAME guarded provider and
budget. No separate cheap-model route or unmetered compaction request is allowed.

Codex uses native automatic compaction at its model default threshold; do not
invent a context-window size, disable compaction or force /compact every turn.
Claude reviews use fresh -p calls with --no-session-persistence, bounded turns
and automatic compaction enabled in the child environment. For a genuinely long
interactive task, checkpoint before native /compact; only report successful
compaction when the runtime reports it. This policy cannot force an already-open
desktop chat to compact through a filesystem edit.

## Budget and stopping

The existing single $90 lifetime cap, minimum $30 free-credit reserve, both
historical ledgers, durable $6 reservations, one in-flight provider request,
STOP, uncertain-outcome accounting, verification expiry, model restrictions and
no-direct-key/no-paid-fallback rules are unchanged. Do not reset or replace them.
The launcher never renews verification automatically. Do not start a worker while billing
verification is expired, STOP is set, accounting is uncertain or prerequisites
are missing. The legacy Python runner remains blocked for live use.

Offline shell permissions are exact check commands, not unrestricted shell.
Tool permissions remain monitored application controls, not OS isolation. Worker
tests execute repository code; do not claim an account-wide billing guarantee.
When stopped, save one checkpoint and stay quiet until a prerequisite changes.
