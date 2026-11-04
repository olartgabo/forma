# Architecture

Status: November 2, 2026. The workspace implements typed domain contracts,
offline compiler/stand renderer/replanner, a bounded model gateway and proposal
service, and private project/inventory/photo persistence. The web connects
consented Muse intake, design, diagnosis and repair proposals to saved manual
review, physical reports, explicit revision approval and versioned Proof.
One EC2 host serves the stack with SQLite and photos on an encrypted volume
([hosted deployment](deploy.md)); hosted sign-in and physical build/recovery
acceptance remain pending.
Recorded live software observations used synthetic imagery; see the
[connected handoff](handoffs/connected-muse-demo.md).

```mermaid
flowchart TD
  User[Builder] --> Web[Next.js mobile web]
  Web --> API[FastAPI project-scoped API]
  API --> Store[(Versions, material ledger, events, evidence)]
  API --> Assets[Private photo and SVG storage]
  API --> Coordinator[Bounded orchestrator]
  Coordinator --> Gateway[Meta model gateway]
  Gateway --> Proposals[Untrusted typed proposals]
  Proposals --> Compiler[Offline deterministic compiler]
  Compiler --> Replanner[Preservation, undo, stock cost, rechecks]
  Replanner --> Renderer[Deterministic SVG renderer]
  Renderer --> Review[User reviews revision diff]
  Review --> Approval[Explicit approval and expected-version check]
  Approval --> API
```

## Module boundaries

| Module        | May depend on                                           | Must not own                                        |
| ------------- | ------------------------------------------------------- | --------------------------------------------------- |
| domain        | Pydantic and basic value types                          | Provider calls, persistence, UI                     |
| compiler      | domain                                                  | Network, physical success claims, state commits     |
| replanner     | domain, compiler                                        | Provider calls, database writes, automatic approval |
| renderer      | domain and compiled geometry                            | Independent model-created geometry                  |
| API services  | domain, compiler, replanner, renderer, storage adapters | Unvalidated state mutation                          |
| model gateway | Provider client and bounded proposal schemas            | Physical event completion or plan activation        |
| web           | Generated API types and API client                      | Server keys, stock/repair authority                 |
| evaluation    | Offline modules and explicit live/physical adapters     | Fabricated results                                  |

The root Python project installs `forma_api` under `apps/api/src`, plus
`forma_domain`, `forma_compiler`, `forma_renderer` and `forma_replanner` from
their package source directories. Pydantic remains the domain schema source;
`contracts:generate` exports JSON Schema, OpenAPI components and TypeScript,
and `contracts:check` rejects drift. See the [domain handoff](handoffs/issue-3-domain.md).
Directory boundaries are conceptual and may be simplified without changing
these rules.

## Three records

1. **Plan:** immutable versioned intended geometry, stock allocations, operations
   and checkpoints.
2. **Execution:** append-only user-confirmed actions, measurements, damage and
   functional tests.
3. **Evidence:** photos, provenance, interpretations, checks and invalidation
   records. Historical evidence remains visible after it becomes stale.

These three record types exist in domain contracts. Persistence currently stores
projects, private photos, confirmed pre-plan inventory and immutable initial plans
with rendered manuals. Append-only user reports persist evidence and material
receipts with a version/history cursor. Approved revisions carry compatible
completions and append evidence invalidations while preserving original reports.
Proof reads those records in one consistent owner-scoped snapshot and excludes
structured photo references from exports. Expected stock remains calculated;
measured waste, salvage and actual recovery evidence remain pending.

The development API uses SQLite and configured owner bearer credentials.
Project create/read, inventory confirmation and logical deletion are scoped to
the owner. Mutations require idempotency keys; inventory edits compare a separate
inventory revision token and reject stale writes with 409. Initial approval activates
a server-compiled stored version against that revision. Inventory image IDs must resolve to the same project's private decoded
photos. Evidence IDs remain rejected. See the
[persistence handoff](handoffs/issue-6-persistence.md) and
[media handoff](handoffs/issue-6-private-media.md).

PostgreSQL and private object storage remain the production targets in the spec.
The hackathon demo keeps SQLite and local media on one EC2 volume with daily
snapshots (D033). Hosted sign-in and provider-side retention remain
[pending decisions](decisions.md). Connected Muse actions require explicit
transfer consent per request; storing a photo alone does not transfer it.

The local web workbench creates/reopens projects, uploads and links private
photos, and saves measured/unknown stock through the scoped API. A same-origin
rewrite forwards the caller's development credential to a fixed configured API
origin. The credential stays in React memory; no shared server owner credential
is inserted. API-local Pydantic envelopes generate separate browser types while
domain generation remains offline. See the [intake handoff](handoffs/issue-7-intake.md).

## Revision transaction

The local flow implements this transaction through saved repair previews and
explicit approval. See the [repair handoff](handoffs/issue-12-adapt-revision.md).

1. Capture the active version, actual events and remaining stock.
2. Obtain at most three typed patch proposals with bounded model/tool rounds.
3. Simulate each patch on a copy; reject schema, stock, geometry, operation and
   tested-profile violations before ranking feasible candidates.
4. Compute compatible preserved work, required physical undo, irreversible loss,
   replacement material and transitive checkpoint invalidation.
5. Render a diff with kept/redo/undo/waste/new-stock/recheck fields.
6. On explicit user approval, re-simulate the stored preview against the expected
   active version and history cursor, then atomically store the new version,
   revision and invalidations. Physical receipts are recorded separately when
   the user reports doing the work; approval consumes no material itself.
7. Return 409 for a stale base. Rejection changes no active state. Retrying an
   idempotent mutation cannot consume material twice.
8. Re-render changed dependency hashes only; render reuse never implies a
   physical checkpoint is still valid.

A second repair on a repaired version remains unsupported. Generic joint-strategy
and stand-angle changes also remain blocked. The supported attached-brace
and attached-base continuations add explicit tape peels and fresh checks; it does not erase the
original completed operations or their material use.

## Physical and model limits

The first family is a small cardboard/paperboard tabletop stand. Measured stock
and tested joint profiles bound supported geometry. Code checks machine-readable
constraints; a person checks actual joint grip, stability and function.

Spark interprets, diagnoses and proposes. SAM assists object review with manual
box/label fallback. Neither determines exact photo scale, hidden strength or
physical success. The offline `forma_photo_measure` package estimates flat sizes
against a verified printed reference; its values stay unconfirmed estimates
(D061). Provider details stay in the API gateway. The compiler works
without an API key. See [contracts.md](contracts.md) and
[model-compatibility.md](model-compatibility.md).

## Implemented services and remaining boundaries

- `forma_compiler.validate_plan` replays stock regions, parts, connectors and
  operations, checking allocation, dependencies, measured process limits and
  compatible profiles. Unused unknown inventory is retained without allocation;
  material used by the plan still requires its critical measurements. Inputs
  remain immutable. See the [compiler handoff](handoffs/issue-5-compiler.md).
- `forma_renderer.compile_stand` builds one three-panel triangular stand with a
  folded lip and tape hinges. `render_manual` independently validates supported
  geometry and emits eight deterministic SVG panels and a BOM, including tape
  balances and explicit offcut regions when present in the plan. Unallocated
  sheet area remains waste. Panel hashes permit reuse of unchanged diagrams.
  Synthetic fixtures require explicit opt-in and visible labels; default calls
  require measured stock/process and reviewed profile evidence. See the
  [renderer handoff](handoffs/issue-8-stand-manual.md).
- `forma_replanner.simulate_patch` validates copied snapshots and history,
  reconciles actual remaining stock, and returns preservation, loss, rechecks
  and continuation blockers. `rank_feasible` ranks at most three feasible
  reports using known cost terms; time, prices and waste estimates remain
  unknown. Completed modifications requiring undo block until an explicit
  continuation exists. Joint-strategy/stand-angle changes require family
  regeneration and currently block; known stand plans require an injected
  family continuation validator. The runtime supplies the stand validator,
  including bounded replacement, base resize and attached-brace or
  attached-base tape undo.
  No simulation commits state. See the
  [replanner interface](../packages/replanner/README.md).
- The server-only Meta gateway validates structured outputs and allowlisted
  read-only tools, bounds calls, and records safe traces. SAM/manual boxes use
  media pixels and establish no physical dimensions. The smoke script separates
  Spark validation from SAM failure and makes no request without explicit live
  prerequisites. Historical compatibility prerequisites remain in
  [model compatibility](model-compatibility.md); later live software observations
  are recorded in the [connected handoff](handoffs/connected-muse-demo.md).
  Real-team-photo SAM acceptance and physical results remain pending.
- `ProposalService.run` supports intake, design, diagnosis and repair against a
  validated scoped snapshot. Candidate and round caps span retries; injected
  deterministic validators gate usable designs/repairs. Diagnosis can reference
  current-plan features without expanding repair targets. Authenticated runtimes
  load saved scoped context and connect compiler/replanner validation. Design
  context must match the exact project and inventory revision; missing measured
  inputs return blockers. See the [proposal handoff](handoffs/issue-9-bounded-proposals.md)
  and [demo runbook](demo-runbook.md).

The API mounts health, private project/inventory/photo routes and immutable
plan/manual reads with explicit initial activation. The internal preview producer
compiles saved inputs with trusted measured context and binds versions to an
inventory revision. The browser reviews saved previews and manuals; step navigation
records no physical work. Active manuals support explicit scoped physical reports,
failed-check gating and expected material accounting. Muse repair results feed
the Adapt review; only an approved stored preview can activate a revision.
Versioned Proof shows historical evidence, carried work and invalidations. See
the [Proof handoff](handoffs/issue-14-proof-summary.md). Compilation and approval
never record a physical test pass.
