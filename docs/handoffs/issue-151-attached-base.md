# Issue 151 handoff: attached-base tape recovery

Status: implemented on `issue/151-attached-base` from `origin/main`, as the
separate bounded PR #151 asks for. Independent of the repair-search PR. All
histories are SYNTHETIC; no physical recovery was attempted.

- Issue and acceptance criteria: #151 carries forward the unfinished
  attached-base replacement from #44: front/rear tape peels, the apex
  preserved, explicit partner checks, no tape refund, new incomplete
  attachments and reconciled remaining stock, unsupported until compiler,
  renderer and history checks pass. Completed-fold support replacement and
  repeated-repair depth stay excluded.
- Owner and reviewer: @olartgabo; @ResniDev owns `forma_replanner` and
  `forma_renderer` and reviews these compiler-affecting changes. Independent
  Sol/Terra review and remote checks are still required.
- Changed files and module boundary:
  - `packages/replanner/src/forma_replanner/tape_undo.py`: a `TapeRole` table
    for brace and base (touching joints in peel order, partners, required
    completed work, extra peel prerequisites). New joints keep the original
    part order with the replacement in the retired slot; the new functional
    test requires the untouched joint plus the two new joints.
  - `simulation.py`: the rename guard applies to both roles.
  - `packages/renderer/src/forma_renderer/continuation.py`: the validator infers
    the retired part from the staged joints and checks the same invariants per
    role. It now returns a blocker, not a `KeyError`, when a historical part is
    missing.
  - `svg.py`: active parts are read from the new rear joint for either role.
  - Tests: `packages/renderer/tests/test_attached_base_replacement.py`,
    `apps/api/tests/test_attached_base_recovery.py`; the old "attached base
    blocks" case in `test_stand_continuation.py` is now support-only.
  - Docs: README, architecture, replanner/renderer READMEs, D043.
- Implemented behavior: after the fold and all three joins, `replace_part` on
  `stand-base` peels front then rear (the first peel also waits on the apex
  attachment so the new test's required apex joint is an ancestor), cuts and
  inspects a replacement base from measured remaining stock, reattaches with
  new front/rear joints and adds or retargets the final fit/test. Brace plans,
  manuals and goldens are unchanged.
- Checks actually run: see the PR body for the final `npm run check` output.
  Targeted: renderer, replanner, `test_adapt.py` and the new API test, 295
  passed.
- Evidence of what the tests cover: front/rear peels with support/brace partner
  checks; apex attach preserved; lost work is the two original joins; only
  two 80 mm reattachments consume tape and 100 mm remains; 6/7/8 completed
  layouts render 14/15/16 panels; reattach and final panels draw the
  replacement, never the retired base; an incomplete attachment (5 completed),
  399 mm of tape and an irreversible front join block; API approval keeps the
  damage history and accepts a reported front peel on the revision.
- Live model/physical evidence: not attempted.
- Pending decisions and blockers: none known. A bench test of the base peel
  is part of #13 physical recovery acceptance.
- Next concrete action and receiving owner: ResniDev reviews the replanner and
  renderer changes.
