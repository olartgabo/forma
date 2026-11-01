# Dev loop (@ResniDev lane)

## Current control path

Use [guarded/run.mjs](guarded/run.mjs) for Muse implementation, tests, offline
checks and repairs. A premium model (Codex or Claude) plans a feature once,
reviews the final green diff, or diagnoses after two failed Muse repairs.
See [the policy](guarded/POLICY.md).

The machine's existing audited guard must already be provisioned outside Git.
Default guard home is `~/.meta-budget`; `META_GUARD_HOME` can select that
existing installation. Never copy credentials, settings, billing records or
journals into this repository and never initialize a second allowance. Put
`uv`, Node and npm on PATH (or set `MUSE_TOOLS_BIN` to the existing uv tools
directory).

Create a task JSON containing `goal`, `acceptance_criteria` and
`files_allowed` (exact source AND test paths; at most 12). Then run:

```sh
node tools/devloop/guarded/run.mjs --workspace /path/to/owned/forma-worktree --task-file /path/to/task.json
node --test tools/devloop/guarded/*.test.mjs
```

The workspace must be a clean registered FORMA checkout on an `agent/muse-`
branch. No reset/clean is performed. No resume/continue flag is accepted: each
feature starts fresh from a bounded task packet. Native automatic compaction
is enabled. Premium plan/review calls are fresh and bounded.

The shared verified free-credit funding ceiling, minimum $30 free-credit
reserve plus lag buffer, append-only shared accounting, STOP, pending/unknown
usage handling and finite billing verification remain in force. Expired
billing verification must be reviewed before dispatch; the launcher never
renews it. No paid provider fallback and no automatic merge.

## Retired Python entry point

`devloop.py` is permanently disabled. Importing it has no provider,
accounting, network, checkout, cleanup, queue or publication effects.
Executing it with any arguments — including no arguments, `--dry-run`,
`--max-iterations`, `--help` or unknown flags — exits nonzero and directs
callers to `tools/devloop/guarded/run.mjs`. No flag dispatches work. The
retired implementation is retained only in Git history; do not restore or
copy it back as executable code.

## Attribution

There are three checks:

1. `.claude/settings.json` sets empty commit and PR attribution.
2. The `.githooks/commit-msg` hook rejects the patterns in
   `.githooks/attribution-patterns.txt`.
3. The `attribution` CI job scans PR commits and the PR body.

The original Claude review role is disclosed in docs/decisions.md D012.
