# Issue 148 handoff: stock-feasible design search and checked comparison

Status: second review repairs implemented; locally green; final independent
Sol/Terra review pending.

- Issue: #148. Owner @ResniDev; feature reviewer @olartgabo.
- Base: `main` at `8a05546` (#147 merged as PR #168). Not stacked.
- Branch: `issue/148-stock-feasible-search`. Candidates `20fdbb5` (first),
  `91b28b1` (first repair); the second repair commit follows them.

## Behavior

See [packages/synthesizer/README.md](../../packages/synthesizer/README.md) and D055.

- `POST /api/projects/{id}/synthesis/search` with the expected inventory
  revision, active version (null) and last event ID. Read-only. Returns at most
  two acceptable designs with named pieces, dimensions, material use, steps,
  the cut-layout SVG, a check matrix and unresolved assumptions.
- `POST .../synthesis/probe` with the `search_id`, a design, one allowlisted
  parameter and a grid value. Read-only. With an active build, the change maps
  to a `resize_part` patch and runs the existing `RepairBase.simulate` without
  saving a preview; a width change returns an explicit unsupported blocker.
- `POST .../synthesis/select` with the `search_id`, design, idempotency key and
  `user_selected: true`. A completed selection replays by key before any
  freshness check. Otherwise the server rechecks domain membership, re-evaluates
  and saves an ordinary preview through `PlanService.compile_preview`. The
  two-preview limit and an active build return named `blocked` blockers.
  Approval stays `POST .../plans/{version}/activate`.
- `POST .../synthesis/muse-explanations` (consent required). The server reruns
  the search and requires the same `search_id`, then gives MetaMuse one
  allowlisted read-only tool, `compare_stand_designs`. Its strict arguments
  pick the authorized search, one or two authorized candidate IDs and at most
  one probe whose value comes from `allowed_probe_values`; extra fields such as
  masses are rejected. The probe runs the deterministic engine and is returned
  as `engine_probe`, apart from the model's prose. The explanation may cite only
  returned designs. Pending, unknown-outcome, stale and replay receipts follow
  the #147 route. Nothing is saved besides the receipt.
- Every request rechecks owner (404), inventory revision, active version, last
  event (409) and, for probe/select/MetaMuse, the search ID. That ID hashes the
  server context fingerprint (process, stand parameters, profiles and
  evidence), stock, requirements, tools, measurement record IDs and budget.
- Web: **Search designs from your saved stock** in the plan step, shown only
  without an active build. Two-column comparison (stacks on phones), a probe
  using server grid values, a consented **Ask MetaMuse** comparison, and
  **Use design A/B**. Selection and MetaMuse bodies are retained in
  owner/project-scoped browser storage before sending. After a reload,
  **Retry saving that design** resends the exact body and key. Only definite
  refusals release a receipt; malformed responses keep it. A probe answer
  attaches only to the controls that were submitted. The existing checkbox and
  **Approve this plan** remain the only activation.

## Review repairs (Codex review of `20fdbb5`)

1. Selection keys were memory-only and dropped on malformed 2xx: now durable
   receipts (`design-candidates/pending.ts`) plus server replay before
   freshness checks. Regressions: web receipt/malformed tests, route replay
   after an inventory change, browser lost response + reload + same-key retry.
2. Late probe answers attached to changed controls: now matched to the
   submitted candidate, parameter and value. Browser race regression; it fails
   when the guard is removed (checked).
3. Unconfirmed tools/access became `infeasible`: now upfront
   `needs_confirmation`, and any compiler input rejection (missing measurement,
   confirmation, unsupported profile) yields `needs_input`, never `infeasible`.
4. The candidate list was built before budgets applied: generation is lazy,
   and the time budget covers preparation and finalist evaluation.
5. A 90° requirement raised a validation error: now an explicit `unsupported`
   blocker for search, probe and selection.
6. Every `blocked` read as an active build: messages are now neutral and the
   server names the preview limit or active build.
7. Missing MetaMuse adapter: added as above.

## Second review repairs (Codex review of `91b28b1`)

1. A MetaMuse answer recovered after a new search appeared under the new
   designs with a usable changed design: it is now labelled as an earlier
   comparison and offers no choice. Browser regression (fails without the fix).
2. The final freshness check and the MetaMuse receipt save were separate: the
   save transaction (BEGIN IMMEDIATE) now rechecks inventory revision, active
   version, last event and measurement records before writing
   (`stored_identity_matches`). Route regression changes inventory after the
   last resolve; it fails without the fix.
3. The preview committed before its selection receipt: a same-key retry now
   also finds the plan service receipt for that key, checks it saved this
   design (otherwise `idempotency_conflict`), repairs the selection receipt
   and replays. Route regression deletes the selection receipt and changes
   inventory; it fails without the fix.
4. Clearing one unreadable receipt cleared both: selection and MetaMuse
   receipts now load, block and clear independently. Browser regression with a
   corrupt MetaMuse receipt beside a pending selection (fails without the fix).
5. Incomplete MetaMuse engine probes passed validation and crashed rendering:
   candidate, probe and explanation validators now check every rendered field
   before a receipt is released; a malformed answer keeps it for retry. Web
   unit regressions.

## Files

- Owned: `packages/synthesizer/**`;
  `packages/domain/src/forma_domain/synthesis_contracts.py`;
  `apps/api/src/forma_api/synthesis_runtime.py`, `synthesis_muse.py`,
  `routes/synthesis.py`, `routes/synthesis_muse.py`;
  `apps/web/src/components/design-candidates/{client.ts,index.tsx,pending.ts}`;
  tests `apps/api/tests/test_synthesis_routes.py`, `test_synthesis_muse.py`,
  `apps/web/tests/design-candidates.test.mjs`,
  `design-candidates-fixture.py`, `design-candidates.browser.mjs`.
- Declared shared integration edits: `pyproject.toml` (package path and test
  path), `apps/api/src/forma_api/projects.py` (two router registrations),
  `apps/api/src/forma_api/model_gateway.py` (one tool name added to the
  read-only allowlist, no behavior change), `packages/domain/src/forma_domain/generate.py`
  (module registration), `apps/api/src/forma_api/generate.py` (API records),
  regenerated `packages/domain/generated/*` and `apps/web/src/lib/generated/*`,
  `apps/web/src/components/plan-workbench.tsx` (mount and MetaMuse availability),
  `apps/web/src/app/globals.css` (layout block at the end), `package.json`
  (`test:web` entry), `docs/decisions.md` (D055), `docs/handoffs/README.md`.
- Consumed unchanged: `compile_stand`, `validate_plan`, `render_manual`,
  `project_nominal_geometry`, `piece_reference`, `fabrication_report`,
  `RepairBase`/`confirmed_remaining`, `PlanService.compile_preview`, the design
  context resolver and the #147 receipt helpers in `routes/designs.py`. No #147
  report contract, fabrication rule, repair search, scheduler or viewer change.
  No new dependency.

## Checks actually run (Windows, Node 22.21.0, npm 11.16.0, Python 3.12)

- `npm run check`: exit 0. Python 1724 passed; web 169 pass; devloop 18 pass;
  production build compiled; formatting, Ruff and contract freshness clean.
- Feature tests: `packages/synthesizer/tests/test_search.py` (18),
  `apps/api/tests/test_synthesis_routes.py` (9),
  `apps/api/tests/test_synthesis_muse.py` (12),
  `apps/web/tests/design-candidates.test.mjs` (10).
- Browser, local Edge via Playwright, `next dev` at 127.0.0.1:3024: `PASS 390px`
  and `PASS 1280px` — search/compare two named designs, probe race ignored and
  regenerated brace shown, consented MetaMuse comparison with engine probe,
  recovered earlier answer shown as history without actions, lost selection
  recovered after reload with one key while a corrupt MetaMuse receipt is
  cleared alone, separate explicit approval; no horizontal overflow; replayed responses only. Reproduce with
  `uv run --locked python apps/web/tests/design-candidates-fixture.py <out.json>`
  then `node apps/web/tests/design-candidates.browser.mjs <playwright index.mjs> http://127.0.0.1:3024 <out.json>`.

## Evidence limits

All inputs are SYNTHETIC fixtures. MetaMuse tests and the browser fixture use
the real gateway with an offline scripted transport; no provider call was made,
and no live MetaMuse result is claimed. The expired verification window still
blocks agent live probes. Candidate stability is not compared numerically: an
unbuilt geometry has no measured stand mass, centre of mass or contact, and
measurements of another stand never transfer. Those rows stay missing,
incompatible or unsupported. No physical result is claimed.

## Remaining unsupported cases

- Shapes other than the triangular tape stand; multi-region or rotated sheets.
- Searching the support angle (it is the confirmed requirement) or the lip.
- Global optimality: rejection inside the finite grid proves nothing beyond it.
- Numerical stability, retention, joint strength and observed access for
  unbuilt designs (needs a built stand and #149 measurement selection).
- Active-build width changes, and any resize the existing replanner blocks
  (for example a completed cut). The active-build probe has no UI; the panel is
  hidden during a build and the repair flow remains the path.
- Live MetaMuse acceptance (needs the finite verification window).
- Spanish copy for the new panel.

## Next

One final independent Sol/Terra review of the complete diff from `main`, then
feature review and exact-head remote checks before merge. #149 measurement
selection can consume `SynthesisResult`/`CandidateReport` once reviewed.
