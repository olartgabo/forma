# Issue #150: reconcile PR #154 with reviewed local work

User decision: use PR #154 as baseline and keep the best useful parts of both
implementations. Branch `issue/150-combined-report` starts at `3ee9812`;
the alternate reviewed implementation remains preserved at `d5fc301` on
`issue/150-fabrication-report-local-review` (checkpoint `ce7ba5a`).

## Bounded contract handoff before dependent integration

Keep the published `VersionHistory`, `FabricationInput`, readiness/transition/order
contracts, GET routes, manual navigation, strict revision replay and deployment
package copy. Do not merge the alternate report schema or add a second engine.

Add `FabricationInput.profile_evidence`, `FabricationSnapshot.inputs_sha256` and
`FabricationReport.required_connector_measurement_ids` from Pydantic. Hash all
typed execution, stock, tool, profile, process and validation-mode inputs.
Missing tools and unconfirmed connector balances block readiness. An explicit
read-only POST assessment of the active version may accept fresh confirmed
remaining lengths and additional available tool names for that snapshot only.
Expected inventory/version/history guard every submitted confirmation. Different
material balances require a separate material record; this endpoint records no
events, evidence, ledger changes or approvals. GET routes remain available.

Fresh length confirmation is available only for known numeric balances calculated
from recorded use. Unknown or other unconfirmed starting measurements remain
blockers requiring inventory confirmation before approval or material-history
reconciliation; they are not offered an impossible report-only measurement form.
Assessment accepts up to 32 connector measurements, matching the inventory bound;
histories beyond the declared 32-version report limit, including a prospective
preview, return an explicit 409 instead of an input-construction failure.

Reserve serialized integration edits: API fabrication runtime/routes/generator,
`adapt.py:_remaining` (report-only subset confirmation, strict existing default),
web API client and fabrication panel, domain generator (include the dedicated
domain records), dedicated tests/browser fixtures, affected module READMEs and
decisions/contracts/handoffs. Pure writing scope is exclusively
`packages/fabrication/**` and `domain/fabrication_contracts.py`; API/web are
sequential consuming edits after those fields are declared. Regenerate output;
never copy generated artifacts between implementations.

## Intended reconciliation

- Preserve PR #154's stronger approved-boundary replay and next-step navigation.
- Preserve declared family limits and existing compiler/renderer geometry.
- Add local material-projection provenance/refund checks and physical-event
  authority/evidence checks without inferring attachments from completed IDs.
- Keep explicit supported join/detach/preparation sequences executable.
- Bring confirmed measurement/withdrawal and stale-response/project-switch
  browser coverage onto the retained panel and route contracts.

## Evidence and publication

Implemented on this combined branch. Prior pass counts belong to their original
trees; the checks below were run against the combined implementation.
No provider calls or physical attempts are authorized by this reconciliation.
Preserve existing STOPs and expired live verification window.

After affected/full checks and one fresh independent Sol/Terra review, publish
the additive reconciliation for PR #154 without overwriting another head. Verify
required remote checks on the exact reviewed head before merge.

Actual checks (all exit 0):

- `npm run contracts:generate` regenerated domain JSON/OpenAPI/TypeScript and API
  types. No generated output was copied or edited by hand.
- `.venv/bin/python -m pytest apps/api/tests/test_fabrication.py apps/api/tests/test_adapt.py packages/fabrication/tests -q`:
  **73 passed in 13.52s** after the review repair.
- `npm run check`: **1,202 Python tests passed in 62.66s**, **116 web tests**,
  **18 devloop tests**, Prettier/Ruff, generated-contract freshness, TypeScript
  and production build passed. Log: `/tmp/forma-150-combined-check.log`.
- Export `apps/web/tests/fabrication-fixture.py` to
  `/tmp/forma-fabrication-combined.json`, then run `fabrication.browser.mjs`
  against the local Next server: **2 PASS** at 390px/320px. Actual synthetic API
  outputs cover fresh tool/measurement confirmations, withdrawal, keyboard
  refresh, manual-step navigation, stale/foreign/unavailable responses, delayed
  old response during project switch and a real compiled repair-preview report.
  The runner forbids provider/external requests and physical mutations.
- Existing `diagnosis-proof.browser.mjs`: **11 PASS**; existing
  `manual-mobile.browser.mjs`: **8 PASS**, including fallback while assessment
  is unavailable. No actual physical result is implied by injected UI failures.
- `uv build --wheel --offline --out-dir /tmp/forma150-combined-wheel` succeeded;
  the wheel contains the engine (including `materials.py`), domain contracts,
  runtime and routes. PR #154's Docker package copy is retained; no Docker image
  build/deployment was attempted.
- `git diff --check` and repository lint/format checks passed.

Commands used `PATH=/tmp/forma-tools/bin:$PATH` and
`UV_CACHE_DIR=/tmp/forma-uv-cache`. Browser runs used
`CHROME_PATH=/opt/google/chrome/chrome`, Playwright at
`/tmp/forma-browser/node_modules/playwright/index.mjs` and a local web server at
`http://127.0.0.1:3007`, with no model key and API origin `127.0.0.1:9`.
API/browser/full checks ran with approved external execution: the sandbox blocks
TestClient/Chrome IPC, and its Node test runner emitted only file wrappers.
Those wrapper results were not counted; external output verified actual named
tests and the full 116-test web denominator.

One fresh independent Terra review covered the complete resulting feature,
including PR #154's baseline. It found a blocked queued step hiding independent
ready work, an impossible requested measurement flow, and inconsistent input
bounds. One bounded repair round added the corresponding regressions. The same
reviewer approved the repaired scope; the final full suite and dedicated browser
replay subsequently passed. No duplicate judge or provider call was used.

Publication gate: the existing PR head remains `3ee9812` and main remains
`6c419d1` as last fetched. Publish this reviewed additive commit to PR #154 with
an ordinary fast-forward push; never force-push. Remote checks and @ResniDev's
feature review remain required before merge/issue closure.
