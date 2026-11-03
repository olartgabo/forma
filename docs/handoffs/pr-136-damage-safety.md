# PR 136 damage safety repair

Status: implemented locally; independent review and publication pending.

- Issue and acceptance criteria: #11 / PR #136. A confirmed report naming two
  damaged parts must stay unresolved when a candidate replaces only one.
  Project deletion must remove private damage replay snapshots.
- Owner and reviewer: native bounded repair; independent reviewer assigned by
  the parent workflow before publication.
- Branch: `issue/11-damage-reports`; merged `origin/main` before repair.
- Changed files: `packages/replanner/src/forma_replanner/simulation.py` and its
  simulation tests; `apps/api/src/forma_api/projects.py`, adaptation tests and
  progress/deletion tests. No generated contracts or browser files changed.
- Behavior: the replacement target must equal the complete damaged-part set
  collected across all evidence linked to each damage event. Multi-part reports
  remain supported, but incomplete single-part candidates block. Blocked preview
  approval leaves the active version and original damage history unchanged.
- Deletion: the existing owner-scoped deletion transaction also purges `:damage`
  receipts, alongside progress and adaptation receipts and cascaded history.
- Contract/schema changes: none; generation unnecessary.
- Checks: affected API tests returned `49 passed in 14.75s` (exit 0).
  Replanner simulation tests returned `54 passed in 0.28s` (exit 0).
- Self-review: checked full diff for complete target validation, authenticated
  project scope, atomic deletion and revision refusal, private response retention,
  unchanged schema generation, and assertions against persisted state.
- Live model and physical evidence: not attempted. Tests use synthetic data and
  establish software behavior only. No guard settings changed.
- Next action: independent review of the green candidate, then parent workflow
  handles authorized publication and exact-head remote checks before merge.
- Full CI command: `NEXT_TELEMETRY_DISABLED=1 npm run check` exited 0.
  Exact summaries: `1114 passed, 4 skipped in 75.20s (0:01:15)`;
  production build `Compiled successfully in 1272ms` and static generation
  `(4/4) in 547ms`. Formatting, Ruff, contract freshness, web typecheck,
  web tests and devloop tests also exited 0 within that command.
  Full local log: `%TEMP%/forma-pr136-check.log`.
