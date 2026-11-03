# Issue 147 handoff: saved stability reports and MetaMuse tools

Status: implemented locally; independent Sol/Terra review pending.

- Issue and acceptance criteria: #147. Immutable content-addressed reports,
  owner-scoped history with stale marking, bounded read-only MetaMuse tools,
  at-most-two comparison, and the listed failure-mode tests. Live MetaMuse
  acceptance is outstanding (see below).
- Owner and reviewer: @ResniDev; feature reviewer @olartgabo.
- Branch and commit: `issue/147-stability-reports`, based on `main` at `98e7966`.
- Changed files and module boundary:
  - Dedicated (owned): `apps/api/src/forma_api/stability_reports.py`,
    `stability_muse.py`, `routes/stability_muse.py`, `routes/stability.py`,
    `stability_runtime.py`, `stability_measurements.py`;
    `apps/web/src/components/stability-report/history-client.ts`,
    `report-history.tsx`, `index.tsx` (mount); tests below.
  - Declared shared integration edits:
    `apps/api/src/forma_api/projects.py` (`stability_reports` table, router
    registration, delete-scope cleanup); `model_gateway.py` (two tool names
    added to the read-only allowlist, no behavior change); `generate.py` and the
    regenerated `apps/web/src/lib/generated/api-contracts.ts`; `package.json`
    (new web test file in `test:web`).
  - Untouched: geometry solvers (`packages/stability/**`), fabrication, repair
    and viewer code.
- Implemented behavior: see "Saved reports and MetaMuse tools (#147)" in
  [engine-stability.md](engine-stability.md) and D053.
- Contract/schema changes and generation command: new API records only; no
  domain contract change. `npm run contracts:generate`.
- Checks actually run (Windows, Node 22.21.0, npm 11.16.0, Python 3.12.6):
  - `npm run check`: exit 0. Python 1683 passed; web 154 pass; devloop 18
    pass; production build compiled.
  - New tests: `test_stability_reports.py` (10), `test_stability_muse.py` (12),
    `stability-history.test.mjs` (7).
  - Browser, local Edge via Playwright: `stability-history.browser.mjs` PASS at
    390px and 1280px; existing `stability-report.browser.mjs` PASS at both
    widths. The first run caught a duplicate React key that stacked measurement
    forms; it is fixed.
- Live model/physical evidence: none. MetaMuse tests use the real gateway with
  an offline scripted transport. They are not a live pass. A live check needs
  the existing finite provider controls; the verification window is currently
  expired, so live acceptance is outstanding. No physical observations.
- Pending decisions and blockers: an independent Sol/Terra review of this diff
  before publication; feature review and exact-head remote checks before merge.
- Next concrete action and receiving owner: Codex review (user to start), then
  publish the PR. #148 consumes the saved-report and comparison contracts.
