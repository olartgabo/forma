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

## November 4 follow-up: bounded Muse focus on current main

This follow-up ports the closed model-output boundary onto the implementation
merged by PR #168. It reuses the existing storage, exact-body retained browser
receipts, provider usage and synthesis consumers. It introduces no parallel
report storage or solver.

The gateway output is `StabilityMuseFocus`: an exact report ID, one or two
distinct authorized case IDs and one to five distinct closed check types. Every
selected case/check pair must exist in the actual saved report and the cases
must have been returned by the tool. Empty, duplicate, unknown and extra prose
fields are rejected. The tool still executes once within the existing four-round
budget. The user's question remains untrusted input to select a focus.

`StabilityMuseResult` adds required `focus` and `focused_results` fields. The
latter contains at most ten actual engine `CheckResult` rows, including original
explanations and unresolved predicates. The public `explanation` envelope remains
available for consumers, but the server generates its text: aggregate saved
report status, selected status counts, case/check statuses and fixed physical
pass/certification/approval limitations. Selecting a passing row cannot hide an
aggregate failed or unresolved report. Model-authored summary, notes, questions
and cautions are never accepted or displayed. The browser labels the response
“Muse-selected report focus” and shows the actual selected engine reasons.

The new prompt identity is `stability-focus-v2`. Retrying the exact retained
request may match its current digest or its original `stability-explanation-v1`
digest. A settled legacy receipt is reconciled from its owner-scoped immutable
report before parsing the new response schema; its old prose is ignored and its
provider usage retained. Freshness is recomputed and no provider is dispatched.
A legacy report with no authorized check results returns a controlled blocker,
also without dispatch. Legacy pending and unknown outcomes continue to block the
same key and new keys across prompt versions. Existing lost-response and reload
semantics remain unchanged.

The current production gateway tests reject malicious physical-pass and
certification prose, foreign/absent selectors, duplicate and empty focus, and
oversized selection. Failed and indeterminate cases retain their actual status
and selected engine rows. Tests also cover legacy completed/unknown/pending and
zero-result receipts, retained usage, freshness and replay without another call.
The history client additionally accepts the combined follow-up's `engine_changed`
stale reason instead of discarding readable historical results.

Actual local verification against the `d21334f` baseline:

- `pytest apps/api/tests/test_stability_muse.py`: 27 passed in 10.42s.
- Combined Muse and saved-report tests after final edits: 38 passed in 14.64s.
- Native Node history client tests: 13 passed, zero failed.
- Web TypeScript: exit 0, “Types generated successfully”.
- Current `stability-history-fixture.py` exports real production-route responses
  using the actual gateway and scripted offline transport. The current history
  browser passed at 390px and 1280px against this checkout's own local server,
  including focus/engine reasons and retained lost-response/reload behavior.

API generation is serialized through `forma_api.generate`; generated TypeScript
was regenerated. No live provider call or physical pass is claimed. Final
combined checks and the existing independent reviewer remain the parent's gate.
