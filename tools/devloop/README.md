# Dev loop (@ResniDev lane)

Development tooling, not part of the product. Meta Muse Spark writes every code
change. Claude acts as architect and judge through headless `claude -p`, with
read-only tools: Sonnet handles routine work and Opus handles hard or
contract-affecting work. Claude's text is never applied as code.

## Per iteration

1. Pick work: your open PRs first, then your assigned issues. Partner PRs are
   read-only context.
2. Sonnet triages the task. Hard tasks, or tasks touching `packages/domain/src`,
   go to Opus.
3. The judge writes a `TaskSpec` with allowed files and acceptance criteria.
4. Muse returns whole-file contents. Every path is checked by `scope.py`:
   lane only, no generated, lock or secret files.
5. The loop runs `ruff format`, `ruff check` and `pytest`, plus
   `contracts:check` for contract changes. The judge then reviews the diff and
   the check output.
6. A change needs passing checks and an approving review. Otherwise up to 3
   repairs are attempted, then the item is blocked with a comment.
7. Approved changes are committed and pushed. Issues get a **draft** PR; PRs get
   a summary comment. The loop never merges or pushes to `main`.
8. When nothing is left, Opus proposes up to 3 new issues, labeled
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

Claude's review role is disclosed in docs/decisions.md D010.
