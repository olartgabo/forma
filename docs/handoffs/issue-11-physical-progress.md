# Issue #11: user-reported physical progress

Owner: @olartgabo. Branch: `issue/11-physical-progress`, stacked on plan/manual #69.

## Contract handoff before implementation

Add API-owned progress records/router without changing domain, compiler, renderer,
gateway or replanner contracts. Only an authenticated user can submit an operation
reference, result, note, checked prerequisites and optional existing private photos.
The server creates domain events/evidence/material receipts, IDs and chronological
ingestion timestamps. HTTP accepts no arbitrary event, evidence, stock delta or
material transaction. Plan/manual bytes and original inventory stay immutable.

`ProgressUpdate` contains `expected_version_id`, required nullable
`expected_last_event_id`, `idempotency_key`, `operation_id`, result
(`completed`/`passed`/`failed`), `observation`, literal `user_confirmed: true`,
literal `checks_confirmed: true` and bounded unique `photo_ids`. Actions accept
`completed`; inspection/functional-test operations accept `passed` or `failed`.

`GET /projects/{id}/versions/{version}/progress` returns `ProgressSnapshot` with
project/version IDs, `last_event_id`, chronological domain `events`, `evidence`,
`material_transactions`, completed/failed operation IDs, `expected_remaining_stock`
and status `not_started`/`building`/`needs_review`/`passed`. Reads can inspect an
authorized saved preview's empty progress; recording requires the active version.
`POST /projects/{id}/events` returns `ProgressResult {progress, replayed}`.

One serialized transaction checks ownership, complete retry payload, active
version, expected last event, known operation, completed predecessors and absence
of duplicate completion. A stale version/history returns 409. Exact retries replay
their original result. Changed-payload retries conflict. Any failed check halts
subsequent confirmations until diagnosis/revision integration exists; history is
never rewritten. Completion never follows from navigation or model output.

Passing checks append user evidence and `operation_confirmed`; functional tests
also append a distinct `test` event with the actual reported result. Failed
inspection creates a failed observation, failed functional test a failed `test`;
neither completes the operation. Functional outcomes refer to the stored named
device, duration, surface and criteria, not an inferred safety claim.

Confirmed cuts consume the whole named source region and create only declared
offcut receipts. No extra waste receipt targets the already consumed parent.
Confirmed connector joins consume the exact planned length once. Receipts link
the completion event atomically. Expected stock removes consumed regions/adds
declared offcuts and derives connector balances. Calculated connector balances
are unconfirmed estimates, not new measurements. Repair consumers must reconcile
actual remaining material before treating this projection as confirmed stock.

Private photo references must resolve in the same project. Evidence preserves
the association; individually deleting a referenced photo returns 409. Whole
project deletion cascades history/evidence/receipts and purges retry snapshots.
All API browser contracts are generated from Pydantic.

The active manual exposes an explicit per-operation report form with displayed
checks, notes and pass/fail for inspection/test steps. Navigation remains separate.
Ambiguous saves retain the original payload/key and lock editing until retry;
stale history requires reloading. Progress restores on refresh. The UI labels
outcomes user-reported and expected balances calculated. Failure shows the need
for diagnosis; this slice does not fabricate a repair or enable autonomous tests.

## Validation and remaining work

Implemented in `forma_api.progress`, project/media integration, generated API
contracts and the active manual report component. User evidence/event/material
rows and the retry receipt commit together. Private photo evidence prevents
individual asset deletion. The projection preserves original measurements and
unknowns; connector balances use exact decimal accounting and stay unconfirmed.

Independent review found a UI replay race: an older receipt could hide a newer
failed report. Replayed writes now fetch authoritative history while controls stay
locked; a failed follow-up read hides cached progress and requires refresh without
offering a duplicate-write retry. Final review reported no remaining blockers.

After fetching and confirming the base current, root `npm run check` exited 0:

```text
All matched files use Prettier code style!
84 files already formatted
All checks passed!
Generated contracts are current
Generated API contracts are current
# tests 12
# pass 12
# fail 0
============================ 323 passed in 13.77s =============================
✓ Generating static pages using 5 workers (4/4) in 502ms
```

Route generation, strict TypeScript and production compilation also completed.
Existing Node module-type and experimental MockTimers warnings remain. The 26
progress tests cover actual compiled fixtures, scope, preview rejection, ordering,
duplicates, stale cursors, retries, concurrency, rollback, project/photo deletion,
restart, monotonic ingestion, failed-check freeze, all eight steps, fractional
connector exhaustion, declared offcuts and real replanner receipt compatibility.
A changed receipt quantity is rejected by the real replanner.

Browser checks used isolated synthetic projects/credentials/manuals and simulated
user reports, with no actual physical attempt. Observed prerequisite gating,
explicit pass/fail with no default pass, required checks/notes, refresh restoration,
and an eight-step software report sequence producing eight completions, a distinct
test event, four consumption receipts and 260 mm calculated/unconfirmed tape.
The source sheet had zero remaining usable regions after its one whole-parent cut.

Dropped committed-save responses locked navigation and retried identical payloads
with `replayed: true`. A failed inspection persisted across refresh and blocked
later report forms. A second-session update caused a stale-report conflict;
reloading project/history restored one event and one receipt, without duplication.
The review repro was exercised in-browser: after a dropped cut-save response,
another session failed inspection, and retrying the older cut displayed the current
failure and no form. A failed authoritative follow-up read hid the report form,
cleared the known write retry and recovered through refresh. Inspected the
390-pixel report layout; no horizontal page overflow was present.

Live plan production, diagnosis/repair activation, actual remaining-material
reconciliation and physical evidence remain separate work. Failed checks have no
same-plan resolution path yet; the UI stops rather than inventing a repair. No
software fixture establishes an actual physical attempt or pass.
