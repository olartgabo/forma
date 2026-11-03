# Issue 150 handoff: next executable fabrication step

Status: implemented on `issue/150-fabrication-report` as two commits: the
report contract, then the connected feature. All histories in tests and the browser check are
SYNTHETIC; no physical step was attempted and no physical result is claimed.

- Issue and acceptance criteria: #150. A pure `FabricationReport` with exact
  snapshot identity, deterministic execution-state IDs, transitions and a
  supported order, tool/access assumptions, per-operation blockers and required
  confirmations; chronological replay that keeps completed work immovable and
  revision boundaries intact; conservative declared family/tool/access rules;
  the report shown read-only in the manual and the repair preview.
- Owner and reviewer: @olartgabo; @ResniDev reviews. Independent Sol/Terra
  review and remote checks on the published head are still required.
- Branch and commit: `issue/150-fabrication-report` from `origin/main`
  `6c419d1`.
- Changed files and module boundary:
  - Owned: `packages/fabrication/**`,
    `packages/domain/src/forma_domain/fabrication_contracts.py`,
    `apps/api/src/forma_api/fabrication_runtime.py`,
    `apps/api/src/forma_api/routes/fabrication.py`,
    `apps/web/src/components/fabrication-report/**`,
    `apps/web/src/lib/fabrication-report.ts`, `apps/api/tests/test_fabrication.py`,
    `apps/web/tests/fabrication-report.test.mjs`, this handoff.
  - Serialized integration edits: `pyproject.toml` (package and test path),
    `deploy/api.Dockerfile` (copies `packages/fabrication/src` into the image),
    `package.json` (`test:web` file list), `apps/api/src/forma_api/projects.py`
    (router mount), `apps/api/src/forma_api/generate.py` (`API_RECORDS`),
    `apps/web/src/lib/generated/api-contracts.ts` (regenerated),
    `apps/web/src/lib/api.ts` (two loaders), `plan-workbench.tsx` and
    `adapt-workbench.tsx` (panel mounts), `globals.css`, `docs/contracts.md`,
    `docs/decisions.md` (D036).
  - Narrow adapter in `adapt.py`: `_ancestors` is now public `plan_ancestors`;
    preview loading and carried-work derivation moved into `read_preview` and
    `carried_operation_ids` so commit and the preview report share one
    definition. Commit behavior is unchanged.
  - No compiler, replanner, renderer, stability or geometry file changed.
- Implemented behavior: see the [package README](../../packages/fabrication/README.md).
  GET `/api/projects/{id}/versions/{version_id}/fabrication` reports the active
  version (409 if it is no longer active). GET
  `/api/projects/{id}/adapt/previews/{preview_id}/fabrication` reports a saved
  preview as if approved, using the same carried work and expected-stock ledger
  commit would produce, and returns 409 once the base history moves. Both are
  owner scoped (foreign and missing projects are 404), `no-store`, and write no
  rows. The manual panel refreshes after each physical report; the preview panel
  sits above "Choose this revision". Neither panel completes a step or approves.
- Contract/schema changes and generation command: new
  `forma_domain.fabrication_contracts` (`VersionHistory`, `FabricationInput`,
  `ToolCheck`, `OperationReadiness`, `OrderStep`, `FabricationSnapshot`,
  `FabricationReport`); output records listed in `API_RECORDS`; regenerated
  with `npm run contracts:generate`. No existing contract changed.
- Checks actually run, exact output and exit status:
  - `npm run check` on the final tree: exit 0. Prettier "All matched files use
    Prettier code style!", Ruff "All checks passed!", "Generated contracts are
    current", "Generated API contracts are current", `tsc` clean, web tests
    "# tests 115 / # pass 115 / # fail 0", pytest "1177 passed", devloop
    "# tests 18 / # pass 18", Next build "Compiled successfully".
  - `uv run --locked pytest packages/fabrication/tests`: 18 passed.
    `apps/api/tests/test_fabrication.py`: 6 passed.
  - Connected browser check against the real API and Next dev server with a
    seeded SYNTHETIC project (six steps reported): the manual panel named
    `stand-inspect-fit` next with the declared ruler; "Show this step" moved
    the manual to step 7 of 8; at 390 px wide the page had no horizontal scroll.
    A UI-driven brace-replacement simulation showed "If approved, next step"
    with the rear peel and its plan checks. This run found and fixed a reload
    loop: an inline progress callback re-triggered `PhysicalProgress` loading.
- Live model/physical evidence: not attempted. No provider call was made.
- Pending decisions and blockers: tool gaps are required confirmations, not
  blockers, because saved tools are locked while a plan is active (D036).
  Independent Sol/Terra review, publication and required remote checks remain.
- Next concrete action and receiving owner: @olartgabo publishes the contract
  and feature PR after review; #151 consumes `FabricationReport` read-only.
