# MetaMuse construction proposals

The project workbench now includes a separate **Muse construction** flow. Save
the goal and inventory, upload a material photo if useful, select that photo,
enter design notes, and explicitly consent to sharing the saved context and the
selected photo. MetaMuse proposes named polygonal panels and connections; the
existing engine generates intermediate construction stages and checks the
fabrication proposal using Gabo's compiler/report. The stand manual, physical
progress, fabrication assessment and repair flows remain separate and unchanged.

## Model and engine contract

POST `/api/projects/{project_id}/construction/propose` takes an expected inventory
revision, optional notes/photo ID, separate context/photo consent and an
idempotency key. The server reads the owner's saved stock, goal, tools and
trusted process/profile context. Caller-authored replacement stock, measurements,
profiles and evidence are not accepted.

The model returns at most two candidates, each with at most eight planar pieces
and twelve proposed connections. Coordinates are proposed design dimensions in
millimetres, not measured photo coordinates. Piece names and roles are tagged
as model suggestions and resolved into the existing stable piece catalog.
There is no shape-preset dispatch or model-authored construction-stage list.

The deterministic adapter validates geometry and IDs, generates the proposed
stages, allocates only selected saved stock and calls the existing production
fabrication engine. Model output cannot supply mass, contact, confirmed access,
tool confirmation, process evidence or completed operations. Unknown mechanics
and missing fabrication inputs remain visible. A candidate is never physical
proof or automatically activated as a build.

One optional correction can use compact engine rejection feedback when the first
single candidate has a repairable geometry/reference/allocation failure. The
original rejected candidate is retained. The total remains two candidates and
one shared four-round/time budget; missing physical evidence does not trigger
repeated model calls. Geometry responses use an explicit 8,192-token output cap;
other gateway consumers retain their 2,048-token default.

## Privacy, retry and history

Photos use the existing private normalized upload store, JPEG/PNG and 5 MB
provider-transfer limits. Consent is scoped to the selected request. Photo/goal
content is treated as untrusted data. Provider keys remain server-only.

The route reserves a durable request receipt before provider dispatch. Identical
successful retries replay the result; changed inputs conflict. In-progress or
uncertain requests block new keys for the same project. Inventory, photo, active
plan and context are checked again before returning/storing a result. A stale or
unknown outcome does not become a usable proposal. Project deletion removes its
construction receipts. No plan, material consumption, physical event or evidence
is written by this flow.

## Interface and verification

The isolated proposal preview displays actual engine facets, named references,
step navigation, camera-only rotation, engine blockers, questions and reported
provider usage. It is not a replacement for Gabo's executable product manual.
Canceling a browser request does not claim the provider stopped; uncertain
requests can only check the same request identity, not silently dispatch a new
one. Changes in project, revision, goal, notes or photo invalidate earlier
consent and results.

Offline tests use injected gateways and provider-compatible response fixtures,
including malformed geometry, reference failures, photos, bounded correction,
ownership, stale races and receipt semantics. Browser tests intercept provider
results explicitly and use engine-derived geometry; they are not live model
acceptance. Live acceptance requires the existing finite verification window and
bounded usage reservation, with actual usage/outcomes recorded. No physical
acceptance follows from either type of software test.
