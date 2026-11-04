# Issue 149 handoff: useful measurements and checked recalculation

Status: review repairs for a8ceb93 applied and locally green; final review pending.

- Issue: #149. Owner @ResniDev; feature reviewer @olartgabo.
- Base: `main` at `34a2c5f` (#148 merged as PR #171).
- Branch: `issue/149-measurement-decisions`.

## What works

See [packages/measurement/README.md](../../packages/measurement/README.md) and D056.

- `POST /api/projects/{id}/measurement-decisions` with the expected inventory
  revision and active version. Read-only. Returns the next useful question or
  one of the other five outcomes, with reasons, missing capabilities, the
  saved facts it depends on and the #148 search or stability summary.
- Questions name the stock, property, units, method, where to measure, the
  compiler threshold, precision basis, affected proposals or cases and why the
  answer can change the decision. Built-stand questions name the three canonical
  pieces by reference.
- Capture reuses existing services: stock and requirement answers are the
  existing `PUT /inventory` confirmation (`source: user_ruler`, `confirmed:
  true`, only the target value changed; a usable area becomes one whole-sheet
  region only after an explicit inspection). Assembled-stand answers use the
  #146 measurement form. No new measurement storage or intake schema.
- `POST .../measurement-decisions/unavailable` records that a selected value
  cannot be taken, as a marker in the existing request-receipt table. It replays
  by key before freshness checks; the identity recheck and the write share one
  write transaction. Marked values are not asked again.
- `POST .../measurement-decisions/recalculate` with the earlier decision as the
  baseline. Read-only. Recomputes the decision on the current authorized
  snapshot and reports the changed facts and whether a decision changed, or why
  not. Inventory changes invalidate #148 searches by identity; saved previews
  for an earlier inventory are listed as no longer approvable.
- Web: **The measurement that matters next** in the plan step, for designs and
  active builds. It shows one question, an explicit "I measured this myself"
  confirmation, **Save measurement**, **I can't measure this** and
  **Recalculate**. The inventory body and key, the "unavailable" body and key
  and the comparison baseline are retained separately in owner/project-scoped
  browser storage and survive reloads; only definite refusals release them.
- Nothing here activates a plan, records physical work or marks a test passed.

## Review repairs (a8ceb93 review)

1. The typed value and confirmation belong to one question ID; deciding,
   declining or recalculating to another question starts empty. Browser
   regression: decline sheet A after typing and confirming, sheet B is empty.
2. Thresholds are found in 0.1 mm steps and a confirmed value below one is
   compiled at its exact value (268.9 mm height now asks for width and, once
   measured, finds candidates; 268.7 mm is excluded).
3. Questions only cover sheet materials with a reviewed tape/fold pair; a sheet
   of another material is named with that prerequisite and the decision is
   `unsupported` when no applicable sheet remains.
4. A compiler input refusal on unlimited stock (missing profile evidence) is
   `unsupported`, not `no_feasible_candidate`.
5. Facts cover the whole inventory (contract limit 160, no truncation);
   comparisons list every change and name a changed next question.
6. A built-stand question is kept as the comparison point (owner/project
   browser storage, survives reload); after the #146 form records values,
   Recalculate shows the change, including the new measurement record.
7. The kept comparison point records whether the save is unknown, saved or
   external. A definite 409/422 says "The measurement was not saved" and drops
   a comparison point that only that answer created.
8. Rendered units and threshold comparisons are validated against the contract.
9. Design settings: no automatic carry-forward. After a confirmed measurement
   the decision is `unsupported` with the new revision ID and the operator
   prerequisite. The browser fixture and a route test use the production file
   resolver with an explicit operator step instead of rebinding.

## Files

- Owned: `packages/measurement/**`;
  `packages/domain/src/forma_domain/measurement_contracts.py`;
  `apps/api/src/forma_api/measurement_runtime.py`,
  `routes/measurement_decisions.py`;
  `apps/web/src/components/active-measurement/{client.ts,index.tsx}`;
  tests `packages/measurement/tests/*`,
  `apps/api/tests/test_measurement_routes.py`,
  `apps/web/tests/active-measurement.test.mjs`,
  `active-measurement-fixture.py`, `active-measurement.browser.mjs`.
- Declared shared integration edits: `pyproject.toml` (package and test path),
  `apps/api/src/forma_api/projects.py` (router registration),
  `packages/domain/src/forma_domain/generate.py` (module registration),
  `apps/api/src/forma_api/generate.py` (three request records), regenerated
  `packages/domain/generated/*` and `apps/web/src/lib/generated/*`,
  `apps/web/src/components/plan-workbench.tsx` (mount), `package.json`
  (`test:web` entry), `apps/web/src/components/design-candidates/pending.ts`
  (#148's receipt helper: size limit raised to 256 KB for inventory bodies),
  `docs/decisions.md` (D056), `docs/handoffs/README.md`. Open PR #169 also
  edits `projects.py`, `generate.py`, `plan-workbench.tsx` and the generated
  contracts; whichever merges second rebases those registration lines.
- Consumed unchanged: `forma_synthesizer` (search, domains, design builders),
  `compile_stand`, `piece_reference`, `synthesis_runtime.resolve`,
  `stability_reports.authorized_snapshot`/`evaluate`, the inventory route and
  the #146 measurement route. No fabrication, repair search or viewer change.
  The pure package imports only offline packages and domain contracts; the API
  adapter reads facts through the existing synthesis and stability services.

## Checks actually run (Windows, Node 22.21.0, npm 11.16.0, Python 3.12)

- `npm run check`: exit 0. Python 1744 passed at a8ceb93; web 175 pass; devloop 18 pass;
  production build compiled; formatting, Ruff and contract freshness clean.
  After the review repairs: Python 1749 passed; web 178 pass; devloop 18 pass;
  build compiled. Browser: design and built-stand flows PASS at 390px and
  1280px. The carry-over regression fails if the per-question answer state is
  removed; the new decision tests fail on a8ceb93.
- Feature tests: `packages/measurement/tests/test_decide.py` (18),
  `apps/api/tests/test_measurement_routes.py` (7),
  `apps/web/tests/active-measurement.test.mjs` (9).
- Browser, local Edge via Playwright, `next dev` at 127.0.0.1:3024: `PASS 390px`
  and `PASS 1280px` — question with compiler threshold, confirmed inventory
  answer recovered after a lost response and reload with one key, explicit
  recalculation showing what changed, unavailable answer stops the question;
  replayed real API responses. The #148 browser check still passes at both
  widths with the new panel on the page. Reproduce with
  `uv run --locked python apps/web/tests/active-measurement-fixture.py <out.json>`
  then `node apps/web/tests/active-measurement.browser.mjs <playwright index.mjs> http://127.0.0.1:3024 <out.json>`.

Acceptance coverage: a width crossing the compiler threshold (77 vs 78 mm) and
the full unknown → width → height → usable area → two proposals path;
irrelevant strips, redundant tape and rescued-by-height sheets never asked;
identical inputs and stock-ID ties; repeated and unavailable answers with
explicit stopping; no-question, no-feasible, physical-test and budget outcomes;
unconfirmed estimates shown but never used; built-stand question, #146 capture
and recalculation to a computed margin; margins inside resolution and missing
margins as unsupported; stale revision (409), cross-owner (404) and stale
question (409); unavailable replay after a change without a duplicate row;
no plan activation, physical event or measurement written by deciding.

## Evidence limits

All inputs are SYNTHETIC fixtures; browser checks replay real server responses
through intercepted transport. No provider call was made. No physical result is
claimed. MetaMuse explanation of the selected question is not implemented in
this slice; the deterministic flow needs no provider.

## Unsupported cases and next dependencies

- Stability of unbuilt candidates: no model predicts their assembled mass,
  centre of mass or contact, and measurements of another stand do not transfer.
  This returns `physical_test_required`. Next dependency: a calibrated
  areal-density/mass model with reviewed evidence, or a defined build-and-test
  step per approved design.
- Conservative uncertainty: margins inside the recorded resolution are
  `unsupported`; interval propagation is not implemented.
- Server design context is keyed by inventory revision (existing
  `FORMA_DESIGN_CONTEXT_PATH` manifest). After a confirmed measurement the
  operator must supply context for the new revision before the search can
  run; until then the decision is `unsupported`, naming the revision and the
  prerequisite. This is the main limit on the live loop. Next dependency: an
  operator-approved policy for which settings may follow measured-value-only
  inventory changes (same stock IDs, kinds and materials), applied in the
  shared resolver so #148 search and #149 decisions agree.
- The intake form records no usable region for sheets, so app-entered sheets
  reach the search only after the explicit usable-area question here.
- Requirement questions need saved requirements; if none exist the panel points
  to the inventory form.
- Unavailable markers persist for the project; there is no "ask again" control.
- Device dimensions, lip and tape overlap are server context, not questions.

## Next

One independent Sol/Terra review of the diff from `main`, then feature review
and exact-head remote checks before merge. Do not merge automatically.
