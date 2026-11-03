# Issue 151 handoff: bounded repair search

Status: repair search implemented on `issue/151-repair-search`, stacked on the
#150 branch. The attached-base replacement carried from #44 is a separate
bounded PR in this issue and is not part of this branch. All histories in tests
and the browser check are SYNTHETIC; no physical repair was attempted.

- Issue and acceptance criteria: #151. Finite candidate generation from the
  current resize, replacement and profile operators with explicit limits,
  deterministic ties, cycle rejection and separate exhausted/infeasible
  statuses; every candidate passes the simulator, compiler and family checks
  plus the #150 rules; ranking by known preservation, undo and material terms
  with unknown time/price/strength and unverified stability shown separately;
  a connected ranked preview reusing the manual diff and atomic approval.
- Owner and reviewer: @olartgabo; @ResniDev reviews. Independent Sol/Terra
  review and remote checks on the published head are still required.
- Branch: `issue/151-repair-search`, based on `issue/150-fabrication-report`
  (PR #154). Merge #154 first.
- Changed files and module boundary:
  - Owned: `packages/repair_search/**`,
    `packages/domain/src/forma_domain/repair_search_contracts.py`,
    `apps/api/src/forma_api/repair_search_runtime.py`,
    `apps/api/src/forma_api/routes/repair_search.py`,
    `apps/web/src/components/repair-options/**`, `apps/web/src/lib/repair-search.ts`,
    `apps/api/tests/test_repair_search.py`, `apps/web/tests/repair-search.test.mjs`,
    this handoff.
  - Serialized integration edits: `pyproject.toml`, `deploy/api.Dockerfile`,
    `package.json`, `projects.py` (router mount), `generate.py`
    (`API_RECORDS`), regenerated `api-contracts.ts`, `api.ts`
    (`searchRepairs`), `adapt-workbench.tsx`, `globals.css`,
    `docs/contracts.md`, `docs/decisions.md` (D037).
  - Adapter edits in `adapt.py`: the preview render-and-store loop moved into
    `save_previews`, used by both simulate and search; `_Base`, `_remaining`
    and `_require_base` became public `RepairBase`, `confirmed_remaining`
    (now taking the measurements) and `require_current_base`. Simulate and
    commit behavior are unchanged. `fabrication_runtime.py` gained
    `ProposedReports`, which loads the base lineage once and schedules several
    simulations; the preview report uses it.
  - No compiler, replanner, renderer, stability or geometry file changed.
- Implemented behavior: see the [package README](../../packages/repair_search/README.md).
  `POST /api/projects/{id}/repairs/search` takes the expected version and
  history cursor, an idempotency key, confirmed remaining stock and connector
  measurements, optional targets and measured sizes, and an evaluation limit
  (at most 12). Without targets it searches the damaged parts, else the parts of
  failed operations, else returns 409. The top three ranked candidates are stored
  as ordinary previews; the summary lists every candidate with its status and
  exact blockers. Adapt adds "Find repair options" beside "Simulate repairs";
  results appear as the usual options with diff, #150 panel and approval.
- Contract/schema changes and generation command: new
  `forma_domain.repair_search_contracts` (`ResizeMeasurement`,
  `RepairSearchLimits`, `CandidateOutcome`, `RepairSearchSummary`) and API
  envelopes `RepairSearchRequest`/`RepairSearchResult`; regenerated with
  `npm run contracts:generate`. No existing contract changed.
- Checks actually run, exact output and exit status: see the PR body for the
  final `npm run check` output. Targeted: `packages/repair_search/tests`
  5 passed; `apps/api/tests/test_repair_search.py` 5 passed; `test_adapt.py`
  24 passed after the refactor; web tests 118 passed.
- Connected browser check (real API and Next dev server, SYNTHETIC project with
  six steps reported and a damaged brace): "Find repair options" checked 3 of 3
  candidates, ranked the brace replacement from the spare sheet first, and
  listed both tape-to-fold joint swaps as not passing with the simulator's
  blocker. The option showed kept, undo, new and lost work, the panel diff and
  the "If approved" next step (rear peel). Approving it activated the revision,
  and the manual's next-step check then named the rear peel.
- Live model/physical evidence: not attempted. No provider call was made.
- Pending decisions and blockers: the attached-base replacement from #44
  (front/rear peels, apex preserved) changes replanner `tape_undo.py` and the
  renderer continuation validator, both @ResniDev-owned modules; it follows as
  its own PR. Optional stability-result consumption stays with #17.
- Next concrete action and receiving owner: @olartgabo opens the attached-base
  replacement PR; reviewers take #154 then this PR.
