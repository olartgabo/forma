# Issue 147 handoff: saved stability reports and MetaMuse tools

Status: second review repair verified after rebase; re-review pending.

- Issue and acceptance criteria: #147. Immutable content-addressed reports,
  owner-scoped history with stale marking, bounded read-only MetaMuse tools,
  at-most-two comparison, and the listed failure-mode tests. Live MetaMuse
  acceptance is outstanding (see below).
- Owner and reviewer: @ResniDev; feature reviewer @olartgabo.
- Branch and commit: `issue/147-stability-reports`, rebased onto `main` at `a4f0bfb`.
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
  - `npm run check`: exit 0. Python 1685 passed; web 159 pass; devloop 18
    pass; production build compiled.
  - New tests: `test_stability_reports.py` (10), `test_stability_muse.py` (12),
    `stability-history.test.mjs` (12).
  - Browser, local Edge via Playwright: `stability-history.browser.mjs` PASS at
    390px and 1280px; existing `stability-report.browser.mjs` PASS at both
    widths. The first run caught a duplicate React key that stacked measurement
    forms; it is fixed.
- Live model/physical evidence: none. MetaMuse tests use the real gateway with
  an offline scripted transport. They are not a live pass. A live check needs
  the existing finite provider controls; the verification window is currently
  expired, so live acceptance is outstanding. No physical observations.
- Review repair (first Codex review of `9f49b2b`):
  1. A replayed save or MetaMuse answer returns its original immutable result,
     but freshness is recomputed when it is replayed.
  2. MetaMuse requests are retained (`muse-pending.ts`, localStorage, scoped to
     owner and project) before sending, and retried with the exact body and key.
     The server looks up a completed receipt before consent and stale checks, so
     a lost response replays instead of dispatching again. Only a definite answer
     clears the receipt. A connection failure, a cut-off body,
     `generation_in_progress` or `generation_outcome_unknown` keeps it. A history
     refresh failure no longer hides a saved report or answer. The cancellation
     message no longer claims that nothing changed.
  3. Refreshing history re-judges open detail, comparison, save and MetaMuse
     views.
  Regressions: backend replay-after-change and lost-response replay (both fail
  on `9f49b2b`), web receipt, lost-response and ambiguity tests, and the browser
  flow with a lost POST, a reload, a refresh failure and a change from another tab.
- Second review repair (Codex re-review of `15a9e98`, one P2): a JSON error
  without a code was read as the string `"undefined"` and treated as definite,
  and a 2xx with an invalid body threw a plain error. Both released the
  retained MetaMuse request, so the next click used a new key. Now only a
  known definite refusal (`consent_required`, `blocked`, `stale_version`,
  `not_found`, `idempotency_conflict`, `provider_not_configured`,
  `invalid_response`) releases it. Any other code, a missing or non-string
  code, and an invalid 2xx answer keep it for a retry with the same body and
  key. Regressions: web unit tests for those codes and for a code-less error
  then an invalid 2xx then a replay with one key (both fail on `15a9e98`); the
  browser flow now goes through a lost, a code-less and an invalid response
  before the reload and the replay, with all four POSTs identical.
- Rebase onto `a4f0bfb`: the only conflict was the decision number. Main took D052
  for the vector artwork, so this entry is now D053. After the rebase,
  `npm run check` and both browser checks passed again at both widths.
- Pending decisions and blockers: an independent Sol/Terra review of this diff
  before publication; feature review and exact-head remote checks before merge.
- Next concrete action and receiving owner: Codex review (user to start), then
  publish the PR. #148 consumes the saved-report and comparison contracts.
