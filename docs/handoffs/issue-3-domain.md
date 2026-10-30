# Issue #3 domain handoff

Status: implemented; consumer and independent review pending. Issue #3.
Owner: @ResniDev. Reviewer/consumer: @olartgabo.
Branch: `issue/3-domain-contracts`, stacked on the issue #1 workspace.

## Exact interface

All runtime imports use `from forma_domain.models import ...`. The root wheel
installs `forma_domain` from `packages/domain/src` alongside `forma_api`; no
separate dependency or competing handwritten API model is required.

- `Measurement`: nullable value, `mm|g|deg`, source, confirmation, evidence IDs.
  Unknown values require unknown source and no confirmation. Stock dimension
  fields enforce mm; remaining connector length can be zero. No inferred scale.
- `Stock`: stable ID, kind/material/condition, measurements, identified rectangular
  regions, image IDs, allowed rotations. Coordinates use mm, top-left origin.
  `Part`: source stock/region, geometry and typed identified features.
- `JointProfile`: experimental/tested, material, measured thickness limits,
  tolerance, test evidence. Tested requires limits/evidence. Consumers resolve
  that evidence against real bench results before offering a profile.
- `Operation`: discriminated by `type`, exactly measure, mark, cut_rect, cut_slot,
  fold, insert_tab, tape_joint, tie_joint, attach_brace, detach, inspect,
  functional_test. Each variant has typed `args`, `preconditions`, `effects`,
  reversibility, expected-state ID and dependencies. Cuts force confirmation and
  irreversible semantics. `confirmed_measurement_ids` refer to `Measure.args`
  measurement IDs declared in the plan; the compiler must resolve the user
  evidence confirming those measurements before execution. They are not stock IDs.
- `BuildPlan`: immutable project/version/parent, stocks/parts/profiles/joints,
  operations/checkpoints, typed constraints, compiler version and aware timestamp.
  Validation rejects duplicate global plan IDs, bad references and dependencies
  that do not precede the operation. Geometry/stock bounds are compiler duties.
- `PhysicalEvent`, `Evidence`, `EvidenceInvalidation`, `MaterialTransaction`:
  separate immutable chronological reports and ledger records. Evidence
  invalidation adds a record; never rewrite the historical evidence.
  Physical completion/test events require user actor; test result/state must
  agree. This validates a report, never authenticates the reporter.
- `DesignProposals` has at most 2 candidates; `RepairProposals` at most 3 flat
  typed parameter patches. `DiagnosisProposal` separates visible observations,
  hypotheses and questions. Extra fields are rejected. All lists/text are bounded
  on model proposal schemas; provider rounds remain capped at 4 by orchestrator.
  Never send BuildPlan/AdaptProposal as the model structured-output schema.
- `CompilerInput`: project/version/time, candidate, stock, tested-profile inputs,
  constraints, measured process kerf/margin and evidence IDs. `CompilerResult`
  accepts only plan without blockers or rejection without plan plus blockers.
  Future #5 interfaces: `validate_plan(plan: BuildPlan) -> CompilerResult` and
  `compile_candidate(request: CompilerInput) -> CompilerResult`. These functions
  are interfaces for future implementation, not provided by this package.
- `ReplannerInput`: base plan, ordered events, evidence/ledger, remaining stock,
  flat patch. Checks base version, history IDs/project scope and chronology.
  Future #10: `simulate_patch(request: ReplannerInput) -> AdaptProposal`.
  `AdaptProposal` includes proposed plan, preserved/undo/redo/new work, invalidated
  checkpoints, ledger changes/new stock and blockers. Consumer resolves these
  cross-version IDs and rejects incompatible preservation before offering approval.

All models forbid extras and freeze assignment; collections are tuples, nested
records frozen. Use `model_validate`/`model_validate_json` at input boundaries.
Do not use Pydantic `model_copy(update=...)` to bypass validation.

## API mutations and error ownership

`ConfirmInventory`, `AppendPhysicalEvent`, `CommitRevision` inherit `Mutation`:
project ID, expected active version, idempotency key. Inventory/event/revision
payloads add user confirmation, a scoped typed event, or proposal ID plus literal
user approval. `MutationResult` returns active version/idempotency/replayed.
`ErrorEnvelope` codes: validation_error, not_found, forbidden, stale_version,
idempotency_conflict, blocked. `Blocker` codes identify missing measurement,
stock exhaustion, geometry/profile/order, irreversible conflict, confirmation,
unsupported and no-feasible-repair outcomes (see generated enum for full list).

#6 must authenticate project access, resolve version/operation/evidence IDs,
validate allowed execution state and actual predecessor completion, reject stale
writes with HTTP409, enforce idempotency payload equality, and atomically commit
version/ledger/invalidations. Schema wrappers do not implement these checks.
Rejecting/simulating proposals changes no active state. No routes or persistence
are introduced by #3; generated OpenAPI is a component catalog with empty paths.

## Generation and verification

`npm run contracts:generate` runs `uv run --locked python -m forma_domain.generate`.
`npm run contracts:check` runs the same with `--check`; included in root check.
Outputs: `packages/domain/generated/contracts.schema.json`, `openapi.json`,
`synthetic-inventory-a.json`, and `apps/web/src/lib/generated/contracts.ts`.
TS is derived from exported Pydantic schemas with readonly object/array types;
JSON Schema enforces units/ranges/bounds at runtime. Generated output has its
own deterministic formatting and is excluded by existing Prettier rules.
Unsupported schema constructs fail generation instead of silently weakening TS.

Checks actually run locally:

- `uv sync --locked --python <bundled Python3.12.14>`: exit0, 25 packages installed.
  The host's automatic pinned3.12.6 install failed creating its minor-version
  link; explicit compatible3.12.14 used. No lockfile hand edit or dependency change.
- `.venv/Scripts/ruff check .`: All checks passed.
- `.venv/Scripts/ruff format packages/domain`: successful.
- `.venv/Scripts/python -m forma_domain.generate --check`: Generated contracts are current.
- `.venv/Scripts/pytest -q`: 20 passed (18 domain, 2 API). Tests include frozen
  nested collections, bad units/unknowns/IDs/operation names/args/order,
  experimental profiles, contradictory physical claims, mutation scope,
  proposal bounds and byte-for-byte checked-in artifacts plus CLI root paths.

`npm ci`: exit0, 29 packages added, 31 audited, zero vulnerabilities.
`npm run check`: exit0 with Node22.21.0/npm11.16.0 and explicit bundled
Python3.12.14. Prettier matched; Ruff44files formatted/lint passed; generated
contracts current; Next route types/TypeScript succeeded; pytest20passed;
production build compiled and generated3/3 static pages. No live model or physical attempts were made.
Synthetic inventory A is labelled unconfirmed; unknown thickness is preserved.
Next: @olartgabo reviews contract scope for #6; #5 validates geometry/conservation,
#10 resolves historical preservation, and #2 supplies measured stock/profiles.
