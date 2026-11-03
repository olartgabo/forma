# Stability engine: S1 mechanics and initial connected report

Issue [#142](https://github.com/olartgabo/forma/issues/142), November 3, 2026.
Owner: ResniDev. Feature reviewer and geometry interface partner: olartgabo.

The initial slice introduced validated quantities, identity, policy and reports.
The next packet adds the pure S1 scalar mechanics consumer, generated inputs and
overlays, scoped read-only API and an explicitly requested report in the active
manual. The shared geometry/stage agreement and actual plan producer remain
pending. S1 mathematical software checks are not the S1 same-plan acceptance
gate, and this initial API/UI path does not complete S2–S7.
Schema validation does not authenticate evidence, establish freshness or prove a
physical result. API consumers must resolve all references in an authorized
project snapshot before using these records.

## Consumer agreement

Import the Python records from `forma_domain.stability_contracts`. Browser types
come from the existing domain generator; do not maintain a second schema.
Measurements can be a finite scalar, ordered inclusive interval or unknown.
Units are explicit SI. Provenance, confirmation, evidence and correlated
dependencies travel with the estimate. An interval is not automatically a
defensible physical bound; the future engine must validate its applicability.

An analysis identifies the exact plan, inventory, construction history, geometry,
evidence and profile revisions. The future server must reject stale contexts and
derive hashes from normalized authoritative inputs, never from display rounding.
Identity fields alone do not implement a cache or revision check.

Reports cover a declared case/check matrix. Missing required checks and failed
computation cannot support an overall modeled pass. Physical observations are
separate references to existing evidence; a modeled pass creates no physical
event. A tipping result does not establish phone retention, sliding resistance,
joint capacity or cardboard strength.

## Geometry handoff still required

The [concrete producer proposal](https://github.com/olartgabo/forma/issues/144#issuecomment-6597156231)
was published November 3. No owner agreement is inferred from posting it.
For x across width, y rearward and z upward, proposed nominal centerlines are
F=(0,0,0), R=(0,D,0), A=(0,S cos(theta),S sin(theta)), and
L=(0,-lip sin(theta),lip cos(theta)), extruded across x in [-W/2,W/2].
They match the existing template/side-view interpretation, not actual contact
measurements. The stability package deliberately does not implement these poses.

[#144](https://github.com/olartgabo/forma/issues/144#issuecomment-6596884972)
owns the canonical pose producer; #141 owns chronological fabrication semantics.
No competing pose producer or AssembledGeometry schema is introduced here.
Before S1 integration, agree and publish:

- Right-handed physical frame: x across, y along the base, z upward; explicit
  support plane and SI conversion from the existing mm/g/degree inputs.
- Physical transforms and part/facet IDs, preserving folded-part mass totals.
- Active stage-specific contacts and attachments, excluding future braces.
- Nominal versus observed geometry and explicit contact assumptions.
- Canonical geometry hash and binding to the exact operation/history state.

Camera motion and exploded display offsets never alter these inputs. Until the
shared producer exists, analytic reference cases may test mathematics but cannot
satisfy connected acceptance. The next slice must consume that producer, not
infer assembled poses from flat rectangles or SVG pixels.

## Applicability and numeric policy for S1

| Check | Supported target | Required unresolved result |
| --- | --- | --- |
| Whole-assembly tipping | Horizontal, coplanar support; gravity only; explicitly assumed rigid assembly; measured or justified bounded mass/COM | Missing mass/contact inputs need measurement; unsupported load or stage stays unsupported |
| Phone retention and sliding | Separate contact model with evidence | No inference from a whole-assembly tipping pass |
| Joint strength and deformation | Separately calibrated later models | Not verified by dimensional joint profiles |
| Dynamic response | Separate future capability | No physical claim from animation |

Caller-selected physical clearance and numerical tolerance must be separate.
For the future signed-clearance test, a lower bound strictly above the required
clearance plus tolerance may pass; an upper bound below the required clearance
minus tolerance fails; the boundary/overlap is indeterminate. These are proposed
engine semantics, not a solver implemented by this contract slice. No default
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
producer plus measured context and policy. The production default has no
producer and returns `needs_geometry`, with no fabricated report or geometry
hash. Synthetic integration tests inject a clearly labeled analytical resolver;
they are not a connected test of the user's actual stand or a #144 producer.
The browser renders the actual typed report and SVG overlay when supplied, and
shows the missing prerequisites otherwise. No request occurs on mount. Network
failure marks any retained result historical/stale; project/version/inventory,
physical-write or diagnosis changes invalidate it. Generated browser types do
not replace the server's Pydantic cross-field validation.

The current generic Evidence record cannot bind a numeric mass/COM/gravity value
to a property, unit and body. The S1 API therefore rejects `measured` or confirmed
quantities until an explicit typed measurement binding exists; a photo,
interpretation or free-text measurement event cannot establish that authority.
Hypothetical unconfirmed values remain labeled in the report. Referenced
evidence must also be current, scoped and applicable. This restriction is an
additional measured-demo gate, not permission to describe assumptions as facts.

S2 still requires immutable report persistence/retrieval and the actual canonical
producer adapter; S3 still requires Muse tool registration. Do not configure a
fixture resolver in production to substitute for missing physical inputs.

## Remaining delivery gates

1. Obtain the #144/#141 owner agreement and producer. The mechanical input models
   are implemented; shared scene/stage acceptance is still outstanding.
2. Consume that producer for the same approved plan and verify dimensions, active
   IDs, stage parity and folded-part mass conservation before claiming S1 acceptance.
3. Complete S2 immutable storage/retrieval and bind actual measurements/evidence
   to the connected report; preserve unknown mass, phone contact and properties.
4. Add bounded Muse tools, shared viewer overlays and actual physical observations
   in S3/S4. Existing live-call windows and STOP controls remain unchanged.

Run domain tests, generated-contract freshness and the repository check command.
Independent Sol/Terra review is required before publication; feature review and
checks on the exact published head remain required before merge. None of these
software checks establishes a physical pass.

## Reproducing the connected software check

Run `uv run --locked python apps/web/tests/stability-fixture.py <output.json>`.
The exporter uses the existing synthetic compiler inputs, a temporary actual
API/database, real activation and the new routes. It exports missing-geometry,
computed analytical and unknown-input responses; providers are prohibited.
Start the local web app with `npm run dev -w @forma/web -- --port 3024`, then run
`node apps/web/tests/stability-report.browser.mjs <playwright-index.mjs> http://127.0.0.1:3024 <output.json>`.
Use `CHROME_PATH` when the local Playwright browser is not installed.
The test intercepts the exported API responses and rejects unexpected requests.
It covers 390px/1280px rendering, explicit analysis, history invalidation without
automatic requests, stale network-failure display, unknown inputs and cancelled
late responses. It is a connected software check, not provider/physical acceptance.
