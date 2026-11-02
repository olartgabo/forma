# Issue #12 repair revision handoff

Status: in review. First complete vertical slice; physical recovery unverified.

- Issue and acceptance criteria: #12, preview adaptation diffs and atomically
  activate approved revisions. Builds on #11 physical reports and the
  replanner/renderer continuations from #60-#67.
- Owner and reviewer: @olartgabo owns the API/web transaction; @ResniDev reviews
  the replanner failed-check rule because it changes compiler-adjacent behavior.
- Branch and commit: `issue/12-adapt-revision`, a merge of `issue/14-proof-summary`,
  `agent/muse-design-generation` and `agent/muse-peel-tape-undo` plus this work.
- Changed files and module boundary: `apps/api/src/forma_api/adapt.py` (new routes),
  `plans.py` (`PlanRevision`, shared `manual_document`), `progress.py` (carried
  completions, detach reports), `projects.py` (tables, router, purge),
  `generate.py`; web `adapt-workbench.tsx`, `manual-diagram.tsx`,
  `lib/operation-titles.ts`, `plan-workbench.tsx`, `physical-progress.tsx`,
  `lib/api.ts`; replanner `simulation.py` (`_failed_check`).
- Implemented behavior:
  - `POST /api/projects/{id}/adapt/simulate` takes 1-3 typed `RepairPatch`
    candidates, the expected active version and history cursor, explicit
    confirmation of remaining material and an actual measurement for every
    connector that confirmed work has used. The server loads the saved plan,
    process, stand parameters/profile evidence, ancestor plans and all lineage
    events/evidence/receipts, then runs `simulate_patch` with the stand family
    validator and `rank_feasible`. Feasible candidates are rendered; the panel
    diff comes from `diff_manuals`. Each candidate is stored as a draft preview.
    Previews change no active state or history. A mismatched tape measurement
    blocks honestly instead of being reconciled.
  - `POST /api/projects/{id}/adapt/commit` requires `user_approved: true`, the
    expected active version, the history cursor and a stored preview ID. Inside
    one transaction it re-runs the simulation from saved history and requires an
    identical result, checks that every carried completion was actually recorded,
    inserts the new plan, a `PlanRevision` record and `EvidenceInvalidation` rows,
    then switches the active version. Stale bases return 409, retries replay,
    concurrent approvals activate one revision, blocked previews cannot be approved.
  - The new version carries the replanner-preserved completions
    (`plan operations - incomplete_operation_ids`), so expected stock is not
    charged twice and finished steps are not asked again. Its own history starts
    empty; failed checks of the parent stay with the parent version.
  - Explicit `detach` (peel tape) steps can be reported like other work.
  - The replanner treated a user-reported failed inspection/test as uncertainty
    and refused every repair. Such a report is now a known outcome: the check
    never completes, so every repair keeps it as incomplete work. System-reported
    failures, failures on non-check operations and unknown/invalidated states
    still block. The tape-undo rename guard ignores failed-check records for the
    same reason.
  - The web Adapt panel builds replace/resize candidates, asks for measured
    remaining tape, shows kept/undo/redo/new work, lost parts/work, stock used,
    checks to repeat, invalidated evidence count, known cost terms (time, waste
    and price stay unestimated) and the updated SVG steps, then activates only
    after explicit approval. The workbench follows a newly activated version.
- Contract/schema changes and generation command: new API records (Adapt*,
  `ConnectorMeasurement`, `PanelDiff`, `PlanRevision`) and replanner
  `SimulationResult`/`RepairCost`/`MaterialDelta` exported to browser types;
  `ProgressSnapshot.carried_operation_ids`. `npm run contracts:generate`.
  No domain model changed.
- Checks actually run: format, ruff, `contracts:check`, web typecheck, web tests
  `# pass 37 # fail 0`, pytest `740 passed`, production build; exit 0. Nine adapt
  API tests cover attached-brace and cut-only repairs, failed-check resolution
  with invalidations, stale cursor/active version, concurrent approvals, replay,
  tape measurement required/mismatch, blocked ranking, owner scope and deletion
  purge. Browser check at 390 px on a seeded synthetic project: failed fit check,
  simulate brace replacement (cost 8, two peel undos, steps 7-14 updated),
  approve, workbench switches to the 14-step revision with 6 carried steps, and
  the first peel step records.
- Live model/physical evidence: not attempted. All projects, credentials, reports
  and manuals were synthetic. No physical recovery or test pass is claimed.
- Pending decisions and blockers:
  - Candidates come from the builder's typed choices. Feeding Muse repair
    proposals (`ProposalService.run("repair")`, PR #63) into the same simulate
    route is the next slice.
  - A second repair on top of a repaired version is not supported: the replanner
    blocks historical evidence about changed definitions and does not yet consume
    the stored invalidation records.
  - Proof does not yet show revision records or invalidations (#14).
- Next concrete action and receiving owner: @olartgabo runs the physical build and
  a real failure through this flow under #13; @ResniDev reviews the failed-check
  replanner rule.
