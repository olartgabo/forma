# Stability engine: mechanics and canonical nominal geometry

Current issue [#146](https://github.com/olartgabo/forma/issues/146); historical specification [#142](https://github.com/olartgabo/forma/issues/142), November 3, 2026.
Owner: ResniDev. Shared interfaces remain available to the fabrication and viewer engines.

November 3 user override: complete engine dependencies in this lane rather than
waiting for Gabo. This supersedes the earlier producer-ownership wait; see D038
and AGENTS.md. It does not waive evidence or independent review requirements.

The initial slice introduced validated quantities, identity, policy and reports.
The next packet adds the pure S1 scalar mechanics consumer, generated inputs and
overlays, scoped read-only API and an explicitly requested report in the active
manual. This packet implements the shared canonical nominal geometry producer
and connects its preview to the same authorized plan. This does not complete
S2–S7, establish physical contact, or provide missing numerical measurements.
Schema validation does not authenticate evidence, establish freshness or prove a
physical result. API consumers must resolve all references in an authorized
project snapshot before using these records.

## Consumer agreement

Import the Python records from `forma_domain.stability_contracts`. Browser types
come from the existing domain generator; do not maintain a second schema.
Measurements can be a finite scalar, ordered inclusive interval or unknown.
Units are explicit SI. Provenance, confirmation, evidence and correlated
dependencies travel with the estimate. An interval is not automatically a
defensible physical bound; the current scalar engine leaves intervals unresolved.

An analysis identifies the exact plan, inventory, construction history, geometry,
evidence and profile revisions. The server rejects stale contexts; hashes derive
from normalized authoritative inputs, never from display rounding.
Identity fields alone do not implement a cache or revision check.

Reports cover a declared case/check matrix. Missing required checks and failed
computation cannot support an overall modeled pass. Physical observations are
separate references to existing evidence; a modeled pass creates no physical
event. A tipping result does not establish phone retention, sliding resistance,
joint capacity or cardboard strength.

## Shared geometry contract and ownership override

The earlier [producer proposal](https://github.com/olartgabo/forma/issues/144#issuecomment-6597156231)
is historical. The user's November 3 instruction authorizes implementing the
needed producer here; another owner's acceptance is no longer an implementation
prerequisite. The viewer should consume this shared producer rather than create
a second geometry authority.

`forma_stability.geometry.project_nominal_geometry` projects validated canonical
stand topology into `forma_domain.assembly_geometry_contracts.CanonicalGeometryPreview`.
Pydantic generates the shared browser schema. Physical units are metres, with
x across width, y rearward and z upward. Nominal centerlines are F=(0,0,0),
R=(0,D,0), A=(0,S cos(theta),S sin(theta)), and L=(0,-lip sin(theta),lip cos(theta)).
The original support source splits into support/lip facets; area fractions sum
to one. Uniform-sheet centroids are explicitly conditional, not measured COM.
Flat cutting offsets are never world placements.

The initial supported topology is the original triangular tape stand. Nominal
planned assembly is distinct from user-reported assembly; either remains nominal
geometry, not observed contact. Unsupported intermediate, damaged, detached or
repaired configurations fail visibly. Camera, explosion and visibility controls
are absent from the physical contract. Hashes bind geometry and applicable
chronological history; the API also binds the inventory and global history cursor.

## Applicability and numeric policy for S1

| Check | Supported target | Required unresolved result |
| --- | --- | --- |
| Whole-assembly tipping | Horizontal, coplanar support; gravity only; explicitly assumed rigid assembly; measured or justified bounded mass/COM | Missing mass/contact inputs need measurement; unsupported load or stage stays unsupported |
| Phone retention and sliding | Separate contact model with evidence | No inference from a whole-assembly tipping pass |
| Joint strength and deformation | Separately calibrated later models | Not verified by dimensional joint profiles |
| Dynamic response | Separate future capability | No physical claim from animation |

Caller-selected physical clearance and numerical tolerance must be separate.
For signed clearance, a lower bound strictly above the required
clearance plus tolerance may pass; an upper bound below the required clearance
minus tolerance fails; the boundary/overlap is indeterminate. The scalar engine
implements these thresholds; conservative interval solving remains pending. No default
engineering reserve, material property or maximum payload is invented.
Finite sampling alone cannot justify a conservative interval guarantee.

## Dependencies and attribution

The numerical stack is now pinned using `uv add --bounds exact`: NumPy 2.5.4
and Shapely 2.2.0. The tested Windows Python 3.12 wheel uses GEOS 3.14.1.
NumPy supplies weighted mass calculations; Shapely supplies support geometry.
Shapely requires an
explicit projection into the support frame; it is not a 3D mechanics solver.
See the [Shapely manual](https://shapely.readthedocs.io/en/stable/manual.html).

The [Shapely source license](https://raw.githubusercontent.com/shapely/shapely/main/LICENSE.txt)
is BSD-3-Clause; [GEOS](https://libgeos.org/) has separate LGPL terms. NumPy's
[license](https://numpy.org/doc/stable/license.html) requires retained notices.
Installed distribution notices, including bundled library terms, are retained
under `docs/licenses/stability/`. The generated lock includes Python 3.12 Linux
ARM64 wheels; availability is not a deployed execution test. Linux ARM64 runtime
verification and its distribution-notice reconciliation remain pending. This is
not a legal eligibility determination for the hackathon.
SciPy/HiGHS remains P1; PyNite and dynamics remain later evidence-gated work.

## Implemented consumer and connected boundary

`forma_stability.evaluate_stability(StabilityInput, AnalysisPolicy)` consumes
already resolved world-space COM values and support polygons. It has no plan
pose reconstruction, provider, storage or UI dependency. The first model is
rigid, horizontal and gravity-only. It rejects or leaves unresolved unsupported
states, future bodies, inactive/invalid contacts, unknowns and intervals.
Each declared case is evaluated; deterministic case budgets return an explicit
exhaustion outcome. The convex support hull is the set of possible coplanar
unilateral reactions, not a claim that gaps between contacts are material.

Reports carry COM, critical edge, signed clearance, restoring moment, physical
assumptions, nominal/observed basis and scalar provenance warnings. Canonical
input, policy and actual engine/dependency versions bind the cache hash; this is
a reproducibility key, not an implemented persistent cache. Passing tipping
does not verify phone contact, sliding, joints or deformation.

The active manual's **Analyze stability** action first obtains
`GET /api/projects/{id}/stability/context?plan_version_id=...`, then posts
`POST /api/projects/{id}/stability/analyses` with that version, inventory revision
and required nullable project-history cursor. It does not send physical inputs,
call Muse, activate a plan or record evidence. Both endpoints authenticate the
owner and require the active plan. POST rejects stale inventory/history with
409 and resolves a single authorized snapshot, including historical evidence
and current invalidations. Another owner's project/plan remains inaccessible.

`StabilityResolver` is the server-side injection seam for the agreed canonical
producer plus measured context and policy. The production default resolves the
shared nominal geometry and returns a
`geometry_preview` with `needs_measurement` while typed measurements are missing.
A current authorized measurement batch resolves a numerical report through the
real evaluator; no fixture resolver is needed. Unsupported
geometry or construction states return explicit blockers. Synthetic analytical
resolvers remain test-only; the default geometry path needs no injected fixture.
The browser renders the actual typed report and SVG overlay when supplied, and
shows the missing prerequisites otherwise. No request occurs on mount. Network
failure marks any retained result historical/stale; project/version/inventory,
physical-write or diagnosis changes invalidate it. Generated browser types do
not replace the server's Pydantic cross-field validation.

## Measured point-estimate flow (#146)

`POST /api/projects/{id}/stability/measurements` records an explicit user-confirmed
batch against the active plan, inventory revision and global history cursor.
The stand must already be user-reported assembled through the supported operation
sequence. The form starts blank, converts g/mm to SI, and requires each observation
and applicability assumption to be reviewed. It cannot mark construction complete.

The bounded input model weighs the assembled stand with all source parts and
connectors together, with measured world COM. This avoids counting support/lip
facets twice or guessing sheet density. Portrait and landscape each require a
device mass/COM, measurement method/resolutions and pose description. Actual
rectangular horizontal support must lie within the canonical base. The user
chooses the required reserve; numeric tolerance is separately declared by the
versioned point-estimate policy. Conventional standard gravity is an assumption.

Typed immutable batches, their user measurement evidence and a measurement event
are appended in one transaction. Retries use the same idempotency key; changes
append a new batch. The adapter binds exact numeric fields to the typed record,
source parts, event and evidence. Inventory, geometry, history or evidence changes
invalidate reuse. Invalidated numerical evidence can be replaced without waiving
construction-evidence invalidation. Generic photos/free-text measurement evidence
still cannot authenticate arbitrary numbers in injected mechanical inputs.

The report is explicitly a scalar point estimate: recorded instrument resolutions
are not propagated into a conservative uncertainty guarantee. It does not verify
phone retention, sliding, joint strength, cardboard deformation or physical success.
A measurement save refreshes physical history/Proof and invalidates the displayed
stability result; analysis is an explicit subsequent action. A save with unknown
network outcome retains its exact request/key in bounded owner/project-scoped
browser storage across remount and reload. Recovery requires an explicit retry;
it never sends automatically. Storage failure blocks the initial write, and an
unresolved save blocks competing construction edits until its outcome is resolved.

Immutable numerical report storage/retrieval and Muse tools belong to #147; this
packet persists the measurement history, not an additional report cache. No live
provider call is necessary for these software checks.

## Saved reports and MetaMuse tools (#147)

`POST /stability/reports` runs the engine on the owner's authorized snapshot
(the same expected plan, inventory and history checks as `/analyses`) and
stores an immutable `SavedStabilityReport` in the `stability_reports` table.
The record holds the normalized `StabilityInput`, policy, report, engine and
numpy/shapely/GEOS versions, and the evidence IDs the input cites. Its ID is
`stability-report-` plus the engine cache hash. That hash already covers the
complete input, cases, policy and dependency versions, so an identical
calculation returns the first record (`cached: true`). Request keys replay
exactly, with freshness recomputed at replay. A response with no report saves
nothing. `/analyses` stays read-only.

`GET /stability/reports` (newest first, at most 50) and
`GET /stability/reports/{id}` return records across plan versions. Each carries
freshness: `plan_changed`, `inventory_changed`, `history_changed` (any new event,
including a measurement edit) or `evidence_invalidated`. Stale reports stay
readable. Records contain no evidence descriptions, media or provider text.

`GET /stability/report-comparison?first=&second=` compares two of the owner's
reports check by check. Different policies, load cases or engine/dependency
versions make every row `not_comparable`. A row with a non-decisive status is
`unknown`. Tip rows compare signed margins within the policy length tolerance.
There is no overall ranking.

`POST /stability/muse-explanations` needs `provider_context_consented`. In
`analyze_current` mode the server evaluates first and refuses dispatch when no
report exists. MetaMuse then calls `analyze_stability`: it may only choose the
authorized plan version and case IDs, and the tool reruns the engine on the
pre-authorized snapshot. In `explain_report` mode MetaMuse calls
`explain_stability_inputs` for the one saved report the owner selected. Tool
arguments are strict and forbid extra fields, so a model cannot supply
measurements or confirmations. The explanation must cite the tool's report and
cases. The route uses the existing pending/unknown-outcome receipts. A history
change during dispatch stores a terminal stale receipt and saves nothing. The
analyzed report is stored with `source: "muse_tool"` only after the identity is
rechecked. A completed request replays (with current freshness) before any
consent or stale check, and the browser retains the exact request body and key
until a definite answer. Provider-reported usage is returned.

Reproduce the browser check with
`uv run --locked python apps/web/tests/stability-history-fixture.py <output.json>`
and `node apps/web/tests/stability-history.browser.mjs <playwright-index.mjs>
http://127.0.0.1:3024 <output.json>`. It uses a scripted offline transport, not a
provider.

## Direct engine feedback

The user-requested [pure engine lab](stability-engine-lab.md) runs at loopback with
`python -m forma_stability --lab --port 3031`. It calls the same evaluator, exposes
editable hypothetical g/mm inputs and raw JSON, plots returned geometry and
exports reproducible feedback. It has no app account, project database or provider.
Its synthetic examples cannot become saved user measurements. The compiled-stand
diagnostic consumes the existing canonical producer and actual compiled operation
IDs. Fixed projections show physical coordinates, with the final target clearly
separated from unsupported intermediate states. The rectangle remains a small
analytical unit case, not the stand model. Hypothetical stage selection records
no actual construction, measurement or test event.

Full intermediate 3D physical snapshots and component-specific mechanics remain
[#153](https://github.com/olartgabo/forma/issues/153), owned here immediately after
#146. Gabo retains fabrication/execution (#150), repair search (#151), and the
interactive product viewer (#152). They consume the single physical producer;
camera and exploded display offsets never change mechanical inputs.

## Remaining delivery gates

1. Extend supported chronological stages and repair continuations through this
   shared producer; reject unsupported states until their geometry is validated.
2. Validate the measured flow on actual observations; extend justified uncertainty
   handling and supported contacts without treating point estimates as bounds.
3. Immutable report storage, history and bounded Muse tools are implemented
   (#147, below). Shared viewer overlays and actual physical observations remain
   S3/S4 work. Existing live-call windows and STOP controls remain unchanged.
4. A live MetaMuse acceptance run of the stability tools is outstanding. It
   needs the existing finite provider controls; offline transport tests are not
   a live pass.

These are work retained in this lane, not an implementation assignment to Gabo.

Run domain tests, generated-contract freshness and the repository check command.
Independent Sol/Terra review is required before publication; feature review and
checks on the exact published head remain required before merge. None of these
software checks establishes a physical pass.

## Reproducing the connected software check

Run `uv run --locked python apps/web/tests/stability-fixture.py <output.json>`.
The exporter uses the existing synthetic compiler inputs, a temporary actual
API/database, real activation and the new routes. It exports canonical nominal
geometry with measurement blockers, computed analytical and unknown-input
responses; providers are prohibited.
Start the local web app with `npm run dev -w @forma/web -- --port 3024`, then run
`node apps/web/tests/stability-report.browser.mjs <playwright-index.mjs> http://127.0.0.1:3024 <output.json>`.
Use `CHROME_PATH` when the local Playwright browser is not installed.
The test intercepts the exported API responses and rejects unexpected requests.
It covers 390px/1280px nominal geometry rendering, explicit analysis, history invalidation without
automatic requests, stale network-failure display, unknown inputs and cancelled
late responses. It is a connected software check, not provider/physical acceptance.
