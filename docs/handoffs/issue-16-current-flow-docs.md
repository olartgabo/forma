# Issue #16: current connected-flow documentation

Owner: @olartgabo. Branch: `issue/16-current-flow-docs`.
Base: `1282193`, after merged PR #110. Documentation-only slice of #16.

## Acceptance and scope

Update the root README, architecture, development plan and handoff index to
describe the merged local flow: consented Muse requests, saved manual approval,
physical reports, deterministic repair simulation, explicit atomic revision
approval and versioned Proof. Link the existing demo runbook and implementation
handoffs. Remove obsolete claims that these boundaries remain unconnected.

No source, API/schema, generated contract or product behavior changes. No new
product decision is introduced. Historical handoff evidence stays historical.
Review documentation against actual route composition, revision commit behavior,
Proof records and the existing connected runbook. Run the full repository check
against the pulled code and report actual results below.

## Evidence and next action

Independent read-only review found no factual blockers against the scoped repair
routes/UI, Adapt commit, Proof redaction/invalidations and the existing runbook.
The repository formatter ran on all five changed Markdown files; `git diff --check`
passed. `origin/main` remained at `1282193` when fetched before publication, and
its latest Offline checks run was successful.

`npm run check` exited 0 on the pulled code with this documentation slice:

```text
All matched files use Prettier code style!
145 files already formatted
All checks passed!
Generated contracts are current
Generated API contracts are current
# tests 82
# pass 82
# fail 0
====================== 1018 passed, 4 skipped in 45.01s =======================
# tests 17
# pass 17
# fail 0
✓ Compiled successfully in 1822ms
✓ Generating static pages using 5 workers (4/4) in 515ms
```

Next route generation and TypeScript also passed. Four Python tests require a
POSIX shell and were skipped on Windows. Existing Node module-type and
experimental MockTimers warnings appeared. Markdown is outside the root check's
format glob, so its targeted formatter and content review are separate evidence.
No source behavior changed or new regression test was needed. This documentation
update establishes no provider call, hosted deployment, physical attempt or pass.

The next product/validation work remains actual measured inputs and build/recovery
under #2/#13, comparable second-inventory/held-out/baseline outcomes under #15,
and persistent hosting, fresh-session access, backup recording and verified
portal requirements under #16. No gate or parent acceptance is closed here.
