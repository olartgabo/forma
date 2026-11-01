# Dev loop (@ResniDev lane)

Development tooling, not part of the product. The original runner has Muse Spark write every code
change. Claude acts as architect and judge through headless `claude -p`, with
read-only tools: Sonnet handles routine work and Opus handles hard or
contract-affecting work. Claude's text is never applied as code.

The runner remains draft: do not dispatch provider calls until PR #33's accounting,
worktree ownership, path containment and complete-review blockers are resolved.
Budget descriptions below state intended behavior, not a verified account-wide
spending guarantee.

On October 31 the user authorized Codex coding agents as a fallback, while
preferring Muse implementation and Codex architecture/review. Provider accounting
requirements still apply. See decision D013.

## Per iteration

1. Pick work: your open PRs first, then your assigned issues. Partner PRs are
   read-only context.
2. Sonnet (medium effort) writes a small `TaskSpec` (at most 3 files), using a
   precomputed lane file list instead of exploring. It may answer
   `already_done`. Opus is used only when the spec touches `packages/domain/src`.
3. Muse returns whole-file contents. Every path is checked by `scope.py`:
   lane only, no generated, lock or secret files.
4. The loop runs `ruff format`, `ruff check` and `pytest`, plus
   `contracts:check` for contract changes. On failure Muse gets the output and
   retries up to 3 times **without any Claude call**.
5. Only green changes reach the Claude review (low effort). A "revise" verdict
   goes back to Muse; there are at most 3 reviewed candidates, then the item is
   skipped for this run.
6. Approved changes are committed and pushed. Issues get a **draft** PR; PRs get
   a summary comment. The loop never merges or pushes to `main`.
7. When nothing is left, Opus proposes up to 3 new issues, labeled
   `loop-proposed` and assigned to you. These are then worked the same way.

Everything runs in `.devloop/worktree`, so your own checkout is untouched.
`.devloop/` also holds `ledger.jsonl` (Meta spend) and `state.json` (blocked
items; delete an entry to retry it).

## Stops

- **Meta budget:** each call reserves its worst case first. The loop stops
  before spend could pass `DEVLOOP_CAP_USD` (default 90). Calls without usage
  data are charged at the worst case.
- **Claude usage limit:** the loop stops cleanly. Rerun it after the reset.
- Meta API errors, Ctrl-C, or no work left.

## Run

```sh
export MODEL_API_KEY=...                 # Meta key
export MUSE_PRICE_IN_PER_MTOK=...        # USD per 1M input tokens, from your Meta billing page
export MUSE_PRICE_OUT_PER_MTOK=...       # USD per 1M output tokens
git config core.hooksPath .githooks
uv run --locked python tools/devloop/devloop.py --dry-run --max-iterations 1
uv run --locked python tools/devloop/devloop.py
```

The loop refuses to start without prices; it never guesses them. It needs a
logged-in `gh` and `claude` on PATH.

## Attribution

There are three checks:

1. `.claude/settings.json` sets empty commit and PR attribution.
2. The `.githooks/commit-msg` hook rejects the patterns in
   `.githooks/attribution-patterns.txt`.
3. The `attribution` CI job scans PR commits and the PR body.

The original Claude review role is disclosed in docs/decisions.md D012.
