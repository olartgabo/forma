# Issue 148 handoff: stock-feasible design search and checked comparison

Status: implemented and locally green; independent Sol/Terra review pending.

- Issue: #148. Owner @ResniDev; feature reviewer @olartgabo.
- Base: `main` at `8a05546` (#147 merged as PR #168). Not stacked.
- Branch: `issue/148-stock-feasible-search`.

## Behavior

See [packages/synthesizer/README.md](../../packages/synthesizer/README.md) and D054.

- `POST /api/projects/{id}/synthesis/search` with the expected inventory
  revision, active version (null) and last event ID. Read-only. Returns at most
  two acceptable designs with named pieces, dimensions, material use, steps,
  the cut-layout SVG, a check matrix and unresolved assumptions.
- `POST .../synthesis/probe` with the `search_id`, a design, one allowlisted
  parameter and a grid value. Read-only. With an active build, the change maps
  to a `resize_part` patch and runs the existing `RepairBase.simulate` without
  saving a preview; a width change returns an explicit unsupported blocker.
- `POST .../synthesis/select` with the `search_id`, design, idempotency key and
  `user_selected: true`. The server rechecks domain membership and re-evaluates,
  then saves an ordinary preview through `PlanService.compile_preview` (two
  previews per revision, same idempotency). Approval stays
  `POST .../plans/{version}/activate`.
- Every request rechecks owner (404), inventory revision, active version, last
  event (409) and, for probe/select, the search ID, which hashes the server
  context fingerprint (process, stand parameters, profiles and evidence), stock,
  requirements, tools, measurement record IDs and budget.
- Web: **Search designs from your saved stock** in the plan step, shown only
  without an active build. Two-column comparison (stacks on phones), a probe
  with server grid values, and **Use design A/B**. An ambiguous selection keeps
  its key for **Retry saving this design**. After saving, the existing plan
  list selects the preview; the existing checkbox and **Approve this plan**
  remain the only activation.

## Files

- Owned: `packages/synthesizer/**`;
  `packages/domain/src/forma_domain/synthesis_contracts.py`;
  `apps/api/src/forma_api/synthesis_runtime.py`, `routes/synthesis.py`;
  `apps/web/src/components/design-candidates/{client.ts,index.tsx}`;
  tests `apps/api/tests/test_synthesis_routes.py`,
  `apps/web/tests/design-candidates.test.mjs`,
  `design-candidates-fixture.py`, `design-candidates.browser.mjs`.
- Declared shared integration edits: `pyproject.toml` (package path and test
  path), `apps/api/src/forma_api/projects.py` (router registration),
  `packages/domain/src/forma_domain/generate.py` (module registration),
  `apps/api/src/forma_api/generate.py` (three request records), regenerated
  `packages/domain/generated/*` and `apps/web/src/lib/generated/*`,
  `apps/web/src/components/plan-workbench.tsx` (mount), `apps/web/src/app/globals.css`
  (layout block at the end), `package.json` (`test:web` entry),
  `docs/decisions.md` (D054), `docs/handoffs/README.md`.
- Consumed unchanged: `compile_stand`, `validate_plan`, `render_manual`,
  `project_nominal_geometry`, `piece_reference`, `fabrication_report`,
  `RepairBase`/`confirmed_remaining`, `PlanService.compile_preview`, design
  context resolver. No #147 report contract, fabrication rule, repair search,
  scheduler or viewer change. No new dependency.

## Checks actually run (Windows, Node 22.21.0, npm 11.16.0, Python 3.12)

- `npm run check`: exit 0. Python 1704 passed; web 165 pass; devloop 18 pass;
  production build compiled; formatting, Ruff and contract freshness clean.
- New tests: `packages/synthesizer/tests/test_search.py` (13),
  `apps/api/tests/test_synthesis_routes.py` (6),
  `apps/web/tests/design-candidates.test.mjs` (6).
- Browser, local Edge via Playwright, `next dev` at 127.0.0.1:3024:
  `PASS 390px` and `PASS 1280px` — search/compare two named designs, read-only
  probe with regenerated brace, lost-response selection retried with one key,
  separate explicit approval; no horizontal overflow; replayed responses only.
  Reproduce with
  `uv run --locked python apps/web/tests/design-candidates-fixture.py <out.json>`
  then `node apps/web/tests/design-candidates.browser.mjs <playwright index.mjs> http://127.0.0.1:3024 <out.json>`.

Acceptance coverage: insufficient sheet and tape; identical-input determinism;
node and time budget exhaustion versus infeasibility; brace and geometry
regeneration after a depth change; missing and incompatible measurements;
hard failures excluded (search, probe and select); stale revision/active/event
and stale search ID; cross-owner 404; completed cut blocks an active-build probe
through the existing replanner; no persisted row changes from search or probe;
browser search → comparison → selection → separate approval.

## Evidence limits

All inputs are SYNTHETIC fixtures. Browser checks replay real server responses
with intercepted transport. No model provider call was made or needed. No live
or physical result is claimed; every candidate's stability remains unmeasured.

## Remaining unsupported cases

- Shapes other than the triangular tape stand; multi-region or rotated sheets.
- Searching the support angle (it is the confirmed requirement) or the lip.
- Global optimality: rejection inside the finite grid proves nothing beyond it.
- Stability, retention, joint strength and observed access for unbuilt designs.
- Active-build width changes, and any resize the existing replanner blocks
  (for example a completed cut).
- MetaMuse explanation of candidates (no tool adapter in this slice).
- Spanish copy for the new panel.
- An idempotent selection retry after a concurrent inventory change returns 409
  instead of replaying; the saved preview is visible in the plan list.

## Next

Independent Sol/Terra review of this diff, then feature review and exact-head
remote checks before merge. #149 measurement selection can consume
`SynthesisResult`/`CandidateReport` once this contract is reviewed.
