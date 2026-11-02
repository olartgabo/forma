# Refresh Proof after a saved diagnosis

Issue: [#14](https://github.com/olartgabo/forma/issues/14), with diagnosis under
#11. Branch: `issue/14-diagnosis-proof-refresh`. Owner: @olartgabo; independent
native review required before publication.

## Change and boundary

An active-step diagnosis persists unverified model evidence. Its success callback
refreshed the manual evidence and photo metadata, but did not notify Proof. An
open Proof snapshot stayed stale, and a pending export could finish with a
snapshot from before the known evidence change.

The callback now uses the existing physical-progress notification to refresh
Proof and photo metadata, retaining its separate manual evidence refresh. The
existing Proof epoch rejects a superseded export. No API/domain, compiler,
model prompt, provider call or physical-event behavior changes.

Owned paths: `apps/web/src/components/intake-workbench.tsx`,
`apps/web/tests/diagnosis-proof.browser.mjs`, `apps/web/README.md`, this handoff
and `docs/decisions.md`. The decisions file also records the user's DigitalOcean
preference; no infrastructure is provisioned or credits assumed available.

## Verification

The browser regression runs the actual local Next app with intercepted API
responses, not a live model. Before the fix, diagnosis succeeded and the test
timed out waiting for `Evidence provenance (1)`; Proof still showed `(0)`.
The initial browser harness needed its photo/readiness paths corrected to match
the client; those setup failures were not app failures. After the one-line fix,
both browser cases pass: automatic open-Proof refresh and rejection of a pending
stale JSON export with no download. The runner also rejects unexpected API calls
and browser crashes. Playwright lives under `/tmp`; no dependency/lockfile changes.

`PATH=/tmp/forma-tools/bin:$PATH UV_CACHE_DIR=/tmp/forma-uv-cache npm run check`
exited 0: formatting, Ruff lint, generated domain/API contracts, strict TypeScript
and production build passed; web `89` passed, `0` failed; Python `1099 passed in
56.36s`; guarded Node `18` passed, `0` failed. This branch starts at main and does
not include the separate timeout regressions from PR #122.

`CHROME_PATH=/opt/google/chrome/chrome node apps/web/tests/diagnosis-proof.browser.mjs
/tmp/forma-browser/node_modules/playwright/index.mjs http://127.0.0.1:3007`
exited 0 with both `PASS` lines. `git diff --check` passed. A fresh independent Sol
review approved all five paths without blockers and independently checked script
syntax and diff whitespace. No live Meta request or physical test was run. The existing external
verification-window and physical-input gates remain unchanged.
