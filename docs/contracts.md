# Contract handoff

Status: requirements for #3, not an implemented schema or endpoint guarantee.
@ResniDev owns domain models; @olartgabo consumes generated contracts in API
services and web. Source: formspec.md sections 4, 5 and 12.

## Domain

Use Pydantic as the schema source. Export JSON/OpenAPI and generate TypeScript
types through a reproducible command selected in #1/#3. Reserve
[packages/domain](../packages/domain/README.md) for the source and future
generated artifacts. Do not hand-edit generated contracts.

Define Stock, Measurement, Part, JointProfile, Joint, Operation, Checkpoint,
BuildPlan, PhysicalEvent, Evidence, MaterialTransaction and AdaptProposal.
Use stable IDs, millimeters/grams/degrees, explicit measurement provenance and
confirmation, and a closed discriminated operation union.

Supported operation names from the spec: `measure`, `mark`, `cut_rect`,
`cut_slot`, `fold`, `insert_tab`, `tape_joint`, `tie_joint`, `attach_brace`,
`detach`, `inspect`, `functional_test`. Each needs typed arguments,
preconditions, effects and reversibility. Unknown operations are rejected.

## Service handoff

| Boundary            | Required input                                                  | Required result                                                           |
| ------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Compiler            | Typed candidate, confirmed stock, tested profiles               | Valid plan or concrete errors/missing measurements                        |
| Renderer            | Compiled geometry, operation, expected state, camera/style      | SVG, render dependency hash, referenced part/operation IDs                |
| Replanner           | Base version, confirmed execution, remaining stock, typed patch | Feasible continuation or blockers; kept/undo/redo/loss/new stock/rechecks |
| Model gateway       | Bounded task snapshot and consented images                      | Validated proposal/observations/questions with safe trace metadata        |
| Revision activation | User approval, expected base version, idempotency key           | Atomic new active version or conflict; no partial ledger writes           |

Agree exact signatures and error codes in #3/#5 before consumers implement them.
Keep proposal schemas flat/bounded for model structured output.

## API surface to implement

Reserve `/api/projects` and project-scoped routes for photos, interpret,
inventory, candidates, compile, versions, manual, events, diagnose,
adapt/simulate, adapt/commit, functional-test and proof. Reserve `/api/jobs/{id}`
and `/api/health` as in spec section 12. Exact routes are finalized with OpenAPI.

Every mutation validates authenticated project scope, runtime input and
idempotency. `adapt/commit` checks expected active version and returns 409 for
stale writes. Neither simulation nor provider tools activate a plan.

## State semantics

```text
DRAFT -> INVENTORY_CONFIRMED -> DESIGN_PROPOSED -> VALIDATED -> BUILDING
BUILDING -> DIAGNOSING -> REVISION_PROPOSED -> REVISION_APPROVED -> BUILDING
BUILDING -> TESTING -> COMPLETE
TESTING -> FAILED -> DIAGNOSING
```

Expose blocked, needs-measurement, unsupported and no-feasible-repair outcomes
with reasons. A defined user-observed passing functional test gates COMPLETE.
Job states are queued, running, waiting_for_user, succeeded, failed and cancelled.
Historical observations remain true as reports even when invalidated for a new plan.
