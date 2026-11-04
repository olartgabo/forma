# Saved stability output and assembly overlay follow-up

The relevance check on November 4 found #147 merged through #168 and the assembly
viewer merged through #169, with deployment repair #178. This follow-up preserves
those implementations and closes two remaining integration gaps: untrusted model
prose could claim physical success, and the viewer did not consume saved reports.

Issue branch: `issue/147-152-current-completion`, based on `d21334f`.
Product decision: D060. No new solver, report store or physical pose producer.

Owned changes are the existing stability Muse runtime/route and history UI, the
assembly display adapter/route/domain contract, and their regression tests.
The saved-report freshness check also marks engine/dependency upgrades stale.
The shared API generator and generated contracts are integrated serially after
the two source changes. Current intake, photo localization, measurement decisions
and deployment configuration remain the baseline.

The combined source was checked at `365aa71` with `npm run check`, exit 0:
formatting, Ruff, generated-contract freshness, TypeScript, web unit tests, the
complete Python suite, devloop tests and the production build all passed.
Actual summaries: `1815 passed, 4 skipped in 187.18s`; web `# tests 194`,
`# pass 194`, `# fail 0`; devloop `# tests 18`, `# pass 18`, `# fail 0`.
All three intercepted browser flows passed at 390px and 1280px:
`assembly-view.browser.mjs`, `stability-history.browser.mjs` and
`stability-report.browser.mjs`. They use exported real API responses with synthetic
inputs and scripted gateway transport. The assembly flow checks saved case
overlays, shared camera projection, separation hiding, exact manual links,
measurement-save refresh and zero camera-driven analyses or writes. History checks
closed focus, actual engine reasons, lost/code-less/invalid responses, retained
request identity across reload and current freshness after another measurement.

The first combined check caught an optional `results` TypeScript access in the
overlay client. The client now rejects a missing completed result; the full check
above is the subsequent passing run.

Local Docker image checks could not run: Docker Desktop returned an internal
server error for its version API. The unchanged repository image jobs will run
on the published PR. Independent review and exact-head remote results are recorded
with that PR. No live model call or physical observation is claimed. The external
provider verification window remains expired.
