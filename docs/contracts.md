# Contract handoff

Status: Pydantic domain contracts and private project/inventory/media routes are
implemented. Plan, execution, evidence and model HTTP integration remain pending.
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

## API surface

Implemented routes are POST `/api/projects`, GET/DELETE `/api/projects/{id}`,
PUT `/api/projects/{id}/inventory`, GET/POST `/api/projects/{id}/media` and
GET/DELETE `/api/projects/{id}/media/{media_id}`. Health remains public at
`/api/health`; project routes require configured owner credentials. API-local
Pydantic envelopes reuse domain Stock records. Inventory revisions remain
separate from active plan versions. See the [persistence handoff](handoffs/issue-6-persistence.md)
and [media handoff](handoffs/issue-6-private-media.md); runtime OpenAPI documents
these envelopes. Domain-generated OpenAPI contains components only.

`python -m forma_api.generate` exports the route-owned Pydantic envelopes to
`apps/web/src/lib/generated/api-contracts.ts`, importing shared Stock from the
domain-generated contracts. Both generation and freshness checks run through
the root `contracts:generate` and `contracts:check` scripts. The offline domain
exporter never imports the API or its persistence/provider dependencies.

Project-scoped interpret, candidates, compile, versions, manual, events,
diagnose, adapt/simulate, adapt/commit, functional-test, proof and job-status
routes remain pending. Offline service implementations do not imply HTTP wiring.

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

## Implemented contract interface (#3)

Import runtime contracts from `forma_domain.models`. The exact schemas, error
codes, mutation wrappers and deferred enforcement duties are in the
[issue #3 handoff](handoffs/issue-3-domain.md). Requirements above are backed
by Pydantic records and generated components. Only the project/inventory/media
HTTP surfaces above are implemented.
