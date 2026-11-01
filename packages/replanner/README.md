# Replanner

Owner: @ResniDev. Reviewer: @olartgabo. Issue: #10. Status: offline simulation implemented; physical recovery unverified.

Consume domain snapshots, physical events, remaining stock and typed patches.
Use the offline compiler to validate copies before ranking feasible repairs.
Return kept/undo/redo, lost material, new stock, invalidated checks, cost terms
and concrete blockers. API services own persistence and approval.

Preservation requires compatible geometry, interfaces, dependencies and evidence.
Incompatible completed cuts require replacement stock or rejection. Consumed
material never returns without a real salvage transaction. Changed dependencies
invalidate downstream checks; replacements remain incomplete.

First deliverable: minimal Oct 31 repair simulation, followed by Nov 1 coverage
for irreversible loss, dependent rechecks and preserved unaffected work.
See [revision architecture](../../docs/architecture.md).

## Interface and trusted inputs

`simulate_patch(snapshot: ReplannerInput, *, process: CutProcess | None = None,
allow_synthetic=False, historical_plans: tuple[BuildPlan, ...] = (),
family_validator: Callable[[BuildPlan], tuple[Blocker, ...]] | None = None)
-> SimulationResult` is pure, offline and deterministic. It returns a draft
preview and never commits a revision, creates physical events, marks work done,
or fabricates salvage transactions. Callers supply authenticated project scope,
reviewed cutting limits and a server-owned tested joint catalogue. Opaque profile
evidence IDs are trusted catalogue references, not proof supplied by a model.

If `patch.base_version_id` differs from `base_plan.version_id`, the call
returns `status='blocked'` with a `stale_version` blocker before any
simulation runs. The snapshot and each supplied historical plan are dumped
with warnings disabled and rebuilt through `ReplannerInput`/`BuildPlan`
validation, because `model_copy` can bypass validators. When that rebuild
fails, including malformed numeric data, the result is blocked with an
`invalid_reference` blocker and a fixed message; validator details and
serializer warnings are not exposed, and only `AttributeError`,
`TypeError` and `ValueError` are handled this way. Caller inputs are not
mutated, and blocked results are excluded by `rank_feasible`.

Supported targets: `resize_part` and `replace_part` name a part;
`replace_joint_profile` names a joint; `change_angle` names the base version.
Resize affects future cuts only. Compatible same-strategy catalogue profile
changes can preserve completed cuts. A completed unjoined part can be replaced
from an actually remaining, measured source region: the old part and cut remain
historically present, a new part/features/cut receive new IDs, and unfinished
consumers reference the replacement. The whole replacement parent region is
consumed; unallocated area is waste, never an invented offcut. Retired parts and
cut operations are reported as loss, not useful preservation.

Changed completed joins, folds or other physical modifications require an explicit
undo continuation and currently block with the affected operation IDs. The engine
does not invent inverses, connector rerouting, purchases or replacement stock.
Changing joint strategy and changing stand angle require family regeneration and
currently return `unsupported`. Pass `forma_renderer.stand_continuation_blockers`
as `family_validator` for `triangular-tape-stand-v1` plans. It supports replacement
of a cut, unjoined panel with the same dimensions from measured remaining stock.
The retired panel and original cut remain historical records. A grouped cut stays
preserved while any of its other outputs remain useful; the retired panel's area
is reported separately. Future access checks reference the replacement and depend
on its new cut. Resource checks alone cannot validate the support triangle.

For the original uncut stand, `resize_part` can extend `stand-base` depth while
keeping its width fixed. The replanner recomputes brace length and the original
three-panel cut layout using the recorded margin and kerf. Confirmed footprint
and stock bounds still gate the result. Shrinking, other panel targets, rotated
or replacement-bearing layouts, declared offcuts and completed cuts remain
unsupported. The family validator checks the result without mutating it.

A `family_validator` result is fully materialized and each item validated as a `Blocker`
before any of it is added. A validator that raises an ordinary `Exception` (including during
lazy iteration) or returns an invalid result adds one stable `unsupported` blocker
(`Family continuation validator did not return a valid result.`). Independent resource
checks may add other blockers. The blocked result has no plan or cost, so `rank_feasible`
excludes it. Blockers yielded before a lazy failure are
discarded, the exception type and message are never exposed in the result. `KeyboardInterrupt` and `SystemExit` are not swallowed and propagate to the caller.

## Execution, material and evidence accounting

Completion is chronological, user-confirmed and once per operation, after its
prerequisites. Linked evidence must exist and support the user's current claim.
Historical events remain unchanged. Supply their original plans through
`historical_plans` so ancestry, definitions, geometry, interfaces and prerequisite
compatibility can be checked; unknown branches/versions block rather than being
rewritten into the current version.

Confirmed cuts and joins project original stock into an expected remaining ledger.
Remaining source IDs, measurements, conditions, region geometry and connector
length must agree exactly with that ledger. Optional material transactions must
reference confirmed events and match the physical transformation. Whole-region
loss is supported; partial loss requires measured region splits. Salvage can
restore an exactly known lost offcut through a real user-confirmed transaction;
it cannot resurrect a consumed parent. Duplicate accounting and duplicate regions
block. After whole-plan geometry/profile checks, only unfinished operations replay
against the actual remaining ledger, so lost stock cannot be spent again.

The result explicitly names preserved, lost, required-undo, redo, newly required
and incomplete operations; changed/lost parts; lost regions; additional source
usage; invalidated checkpoints and evidence; and outstanding physical checks.
Changed operations receive new IDs and remain incomplete. Checkpoint invalidation
follows all affected operation dependencies transitively. Evidence invalidation is
a preview list; old records are never erased. `additional_material_stock_ids`
names sources for changed/new operations, not purchase claims or available stock.

`rank_feasible` accepts at most three reports and excludes blocked candidates.
It sorts only known heuristic terms (`5 * lost irreversible actions +
3 * required undos + 2 * new irreversible actions`), then fewer unknown human
checks/new cuts and stable patch ID. Time, waste fraction and price estimates
remain null and `complete_estimate=False`; this partial ordering is not the
complete repair-cost formula. No fixture establishes a real physical pass.

## Checks

After the parent integrates package/test discovery, run
`python -m pytest packages/replanner/tests` and
`python -m ruff check packages/replanner` in the repository environment.
Before packaging integration, add `packages/replanner/src`,
`packages/compiler/src` and `packages/domain/src` to `PYTHONPATH`.
