# Issue #6: immutable initial plans and approval

Owner: @olartgabo. Branch: `issue/6-plan-activation`, stacked on requirements #68.

## Contract handoff before implementation

Add an API-owned plan service and router, without changing domain/compiler/provider
contracts. The internal service receives an authenticated owner/project, expected
inventory revision, an untrusted `DesignCandidate` and trusted server-resolved
cutting process, stand parameters and joint profiles. It reads saved stocks and
constraints, runs the real compiler and renderer, and persists only accepted
outputs with a server-generated version ID/time and exact inventory revision.
Synthetic evidence remains an explicit service-test opt-in; HTTP cannot enable it.

Selected `kerf_mm` and `edge_margin_mm` are explicit trusted inputs, independent
of process minimums. Missing/invalid values produce blockers without a preview.
The compiler checks chosen allowances against the supplied process. The saved
plan's cut arguments retain the actual selected values. Compile retry receipts
bind the complete producer invocation, including process, parameters, profiles
and selected allowances, so changed context cannot replay a different plan.

Plan and manual bytes are immutable. A project-owned version stores the process
and profile/stand context for later revalidation. Public read envelopes reuse domain
`BuildPlan` and API-local Pydantic manual/panel/BOM records; the exporter generates
browser types. Reads use the existing owner credential and cache prevention.

`GET /projects/{id}/plans` lists saved version summaries. Version and manual reads
resolve only rows under the authorized project. Approval posts to
`/projects/{id}/plans/{version}/activate` with expected inventory revision,
idempotency key and literal `user_approved: true`. It accepts no plan JSON. A
transaction checks the preview revision and current inventory revision, permits
only initial activation, sets the active pointer and records the retry receipt.
Stale/competing activation returns 409. Exact retry returns the original outcome.
Activation creates no physical events, consumption or test results. Project
deletion also purges plan/manual rows and activation receipts.

The browser can inspect saved previews/manuals and explicitly approve a current
preview. Manual step navigation records no physical completion. This does not add
a disconnected compile button or production fixtures. Live model generation and
real measured process/profile/usable-region inputs remain the producer's next
integration boundary. No empty preview is presented as a generated plan.

## Validation

Implemented in `forma_api.plans`, the project transaction/router integration,
generated API contracts and the browser plan workbench. Manual panels include
written renderer instructions and image-isolated SVG with a full-size scroll view.
Preview browsing records no completion. Approval locks pre-plan inventory edits;
an ambiguous approval locks intake until the identical request is retried.

Independent review caught a compile-retry fingerprint that omitted trusted
context. The final digest binds all producer inputs, and changed-context retry
tests verify conflict without changing saved versions. Final independent review
reported no remaining blockers. The MCPJam review-lessons checklist covered scope,
concurrency, deletion, parsing, cancellation, resource cleanup and false-green tests.

After fetching the requirements base and confirming it was current, root
`npm run check` exited 0 with these actual output excerpts:

```text
All matched files use Prettier code style!
81 files already formatted
All checks passed!
Generated contracts are current
Generated API contracts are current
# tests 11
# pass 11
# fail 0
============================= 297 passed in 8.90s =============================
✓ Generating static pages using 5 workers (4/4) in 521ms
```

The command also completed route generation, strict TypeScript and production
compilation. Existing Node module-type/experimental MockTimers warnings remain.
The 28 plan tests use real compiler/renderer calls with explicitly synthetic test
context, and cover default synthetic rejection, missing/invalid inputs, preserved
selected cut allowances, changed-context retries, stale snapshots, two-preview
caps, concurrent compile/activation, exact replay, rollback, deletion and restart.

Browser checks used an isolated database, synthetic credentials and visibly
synthetic generated manuals. Observed eight rendered panels with readable written
instructions, next/previous navigation, approval disabled until review, unsaved
edits blocking approval and an active plan restoring after refresh. A dropped
committed approval response locked intake; its retry sent identical bytes and
returned `replayed: true`. A separate project changed inventory in another session;
approval conflicted and its active version stayed null. At 390 pixels, diagrams
loaded without page overflow; enlarged diagrams scrolled within a focusable region.
Desktop/mobile screenshots were inspected. These checks establish software
behavior only; no provider request, real measurement or physical pass occurred.

## Remaining producer and physical integration

The internal compile service has no HTTP producer endpoint yet. The live design
runtime must authenticate the owner, resolve actual measured cutting/stand inputs,
reviewed profiles/evidence and explicit usable regions, then call the service.
There are no runtime fixture defaults or browser plan-upload routes. Tools and
constraints saved by #7 are inputs, not substitutes for these missing facts.

Initial plan/manual approval is implemented. #6 remains open for chronological
physical/material/evidence history, hosted identity and consented provider transfer;
#11 remains open for physical confirmations. Repair activation remains #12.
