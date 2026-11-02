# Issue #14: versioned plans, repairs and evidence Proof

## Revision Proof contract handoff, November 2, 2026

The next slice on `issue/14-revision-proof` extends `ProofVersion` with
`state: active | historical | preview`, optional `revision: PlanRevision` and
`invalidations: tuple[EvidenceInvalidation]`. Historical versions are ancestors
of the active plan; unselected designs remain previews. Invalidations attach to
the version that owns the source evidence and retain the destination version,
reason and timestamp. Original evidence verification states remain unchanged.
Coverage becomes `versioned_plan_reports`. Revision simulation plans receive the
same photo-ID exclusion as ordinary plans. The browser separates carried work
from newly reported completions and displays stored repair/recheck details.
These are read-only additions within the existing owner-scoped transaction.
Pydantic generates the consumer types; no domain or compiler contract changes.

## Revision Proof implementation and checks

The snapshot now reads approved revisions and source-evidence invalidations in
the same transaction as projects, plans and progress. Both the panel and text
export distinguish historical plans from unused previews, carry earlier work
separately from new completion reports, and show approved kept/undo/redo/new/lost
work, material proposals, changed parts and required rechecks. Planned material
deltas are labelled as proposals; original physical receipts remain separate.
Evidence keeps its recorded provenance and outcome, with checkpoint IDs and
dated notices naming the revision that invalidated it. Historical failed tests
remain failed; approval does not create a physical pass or new report.

The full npm run check exited 0: `807 passed in 42.36s`, formatting, Ruff,
generated contracts, TypeScript and production build passed.
The affected API suite reported `9 passed in 2.54s`; the web suite reported
`# tests 44`, `# pass 44`, `# fail 0`. Web TypeScript completed successfully.
Real compiled synthetic repair tests cover failed history, carried work,
source-scoped invalidations, owner scope and unchanged canonical records.
Photo exclusion covers the nested plan in `revision.simulation`, with a saved
photo-linked repair proving the private revision remains intact. Text tests
exercise historical/preview/active labels, required undo/rechecks, planned stock
use and unchanged failed evidence. These are offline software checks.

Measured waste/salvage, physical attempts, timing and actual recovery evidence
remain pending. The implementation does not close every acceptance criterion
of #14. The notes below record the original slice and its historical checks.

## Original slice

Owner: @olartgabo. Branch: `issue/14-proof-summary`, stacked on physical progress #81.

## Contract handoff before implementation

Add a read-only API snapshot and browser Proof panel using the existing immutable
plan, progress, evidence and material records. No domain/provider/replanner changes
or new storage. GET `/projects/{id}/proof` authenticates ownership and reads the
project, saved versions, progress and media count through one SQLite transaction.
This prevents mixed event/evidence/receipt frontiers during concurrent reporting.

`ProofSnapshot` contains `project: Project`, `generated_at`,
`versions: tuple[ProofVersion]`, `photos_omitted`, literal `photo_policy: excluded`
and literal `coverage: initial_plan_reports`. `ProofVersion` contains
`inventory_revision_id`, `candidate_id`, `plan: BuildPlan`,
`progress: ProgressSnapshot`. API Pydantic records generate browser types.

Export redacted copies: all Stock image IDs in project/plan/expected stock become
empty; every Evidence asset ID becomes null. Structured photo references, bytes,
paths and URLs are excluded; user-authored goal/notes remain text. Original private records stay unchanged. Existing event
and evidence IDs still identify the claims within the snapshot. There is no public
sharing route or implicit permission to transfer photos.

The panel displays a dated snapshot of versions, confirmed/uncompleted operations,
chronological user reports, evidence provenance, named test conditions/results,
material receipts and expected stock. Expected balances remain unconfirmed
calculations. Whole-region consumption is not a measured waste quantity. Recorded
timestamps are ingestion times, not measured build durations. Compiler/profile
acceptance never becomes a physical pass. Empty previews remain unattempted.

Explicit local JSON/text downloads fetch a fresh scoped snapshot and exclude
photos. Notes and goal text remain part of the user's chosen report. The UI uses
text rendering/serialization, not unescaped HTML. A report refreshes when opened
or after known physical-report changes while visible.

Repair activation, preservation diffs, invalidation/freshness across revisions and
damage/salvage reconciliation are not integrated. Display that coverage limit;
never invent zero repair metrics or claim all checks are current. This is the
first Proof slice and does not close all of #14.

## Validation and remaining work

Implemented in the API Proof router, generated records, browser panel and text
formatter. The API opens no new tables and mutates no canonical project/plan,
evidence, material or photo records. UI updates are dated snapshots; explicit
downloads fetch fresh data and use ordinary text/JSON serialization.

Independent review found a stale export side effect and a closed-panel variant.
The request epoch now invalidates exports before Blob/download creation on every
known data change, whether the panel is open or closed. Stale export errors are
guarded too. Review also caught missing tape width in the unknown-input list;
it is now included with a regression fixture. Final review found no blockers.

After fetching and confirming the physical-progress base current, root
`npm run check` exited 0 with actual excerpts:

```text
All matched files use Prettier code style!
87 files already formatted
All checks passed!
Generated contracts are current
Generated API contracts are current
# tests 14
# pass 14
# fail 0
============================ 330 passed in 15.03s =============================
✓ Generating static pages using 5 workers (4/4) in 483ms
```

Route generation, strict TypeScript and production compilation also completed.
Existing Node module-type/experimental MockTimers warnings remain. Seven API tests
exercise real compiled/reported fixtures: scope, empty/unattempted/failed/passed
snapshots, multiple previews, structural redaction in all nested stock/evidence
locations with unchanged canonical/private-photo reads, and a concurrent append
blocked until a complete old snapshot finishes; the next read gets a complete new
frontier. Client tests cover scoped reads, unknowns/tape width and text report
wording for failed versus unattempted defined tests.

Browser probes used isolated synthetic data. Proof refreshed after local reports.
Holding an export response across a physical report suppressed the stale download
and displayed newer progress. The same probe passed while Proof was closed, then
reopening restored current progress. Actual JSON/text downloads were saved and
parsed: all structured photo references were excluded, one private photo was
counted, two user-reported completions were retained and the final test remained
unattempted. Inspected the 390-pixel panel screenshot; no horizontal overflow was
present. These were simulated software reports, not physical attempts.

The first Proof slice is implemented. Full #14 acceptance still needs repair
activation/invalidation integration and physical evidence. No provider call,
actual measurement or independent physical verification is implied by these tests.
