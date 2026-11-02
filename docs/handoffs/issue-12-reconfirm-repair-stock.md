# Reconfirm remaining repair materials

Issue: [#12](https://github.com/olartgabo/forma/issues/12). Branch:
`issue/12-reconfirm-repair-stock`, stacked on the Proof refresh branch/PR #123.
Owner: @olartgabo; fresh independent review required before publication.

## Problem and behavior

Repair review retained checked confirmation after editing a remaining connector
length or reloading newer physical history. It also retained previews based on
earlier measurements. An ambiguous simulation could be retried with the earlier
payload after inputs changed.

Editing a connector length unchecks confirmation, invalidates previews and
discards the obsolete simulation retry. Withdrawing confirmation does the same.
Reloading recorded work first clears lengths, confirmation and those previews,
even if the read fails. Users must measure and confirm again. The preview input
generation advances so a late old result cannot become current. Candidates stay
available, and uncertain activation retains its exact retry: that operation may
already have committed. Its material inputs stay locked until the outcome is
resolved, with a browser case verifying the identical retry payload. D031 records
the product behavior.

No domain/API schema, compiler, provider or physical-event changes. Owned paths:
`apps/web/src/components/adapt-workbench.tsx`,
`apps/web/src/lib/repair-workbench-state.ts`, `apps/web/tests/api.test.mjs`,
`apps/web/tests/diagnosis-proof.browser.mjs`, `apps/web/README.md`,
`docs/decisions.md` and this handoff.

## Verification

Before implementation the browser reproduced the checked-confirmation defect
after editing the connector length (`true !== false`). The extended browser
runner passes editing, history reload (new cursor and quantity), withdrawing
confirmation and removing an ambiguous simulation retry; both earlier Proof
cases still pass. It also verifies that explicit fresh confirmation sends the
current measurement/history cursor and that no automatic simulation occurs.

The browser harness needed selector corrections; after two setup failures one
targeted independent diagnosis identified the heading-name collision. The bounded
selector correction reached the real red assertion. The retry case initially
used a definite HTTP failure and was corrected to a transport failure to exercise
the actual ambiguous-outcome path. These were harness setup failures, not failed
physical tests or successful product behavior.

A reducer regression checks preview/choice/approval clearing, removal of obsolete
simulation retries, rejection of late results, immutable prior state, retained
candidates and preservation of the exact uncertain activation retry.

`PATH=/tmp/forma-tools/bin:$PATH UV_CACHE_DIR=/tmp/forma-uv-cache npm run check`
exited 0 on the final code: formatting, Ruff lint, generated domain/API contracts,
strict TypeScript and production build passed; web `90` passed, `0` failed;
Python `1099 passed in 59.61s`; guarded Node `18` passed, `0` failed.

The browser command documented in the web README exited 0 with all seven `PASS`
lines, using `/tmp/forma-browser/node_modules/playwright/index.mjs`,
`CHROME_PATH=/opt/google/chrome/chrome` and the local Next server on port 3007.
That server was stopped after verification. `git diff --check` passed. A fresh
independent Sol review approved the seven-path diff with no blockers. All browser API data is explicitly synthetic and
intercepted; no Meta request, measurement or physical test was run.
