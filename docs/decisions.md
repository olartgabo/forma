# Decisions

Status: planning baseline, October 30, 2026. Accepted entries below come from
the supplied spec or the user's ownership instruction. They are architecture
constraints, not claims that software or physical tests exist.

## Accepted baseline

| ID   | Decision                                                                                   | Basis                                              |
| ---- | ------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| D001 | One low-risk tabletop stand family; P0 build/recovery first                                | formspec.md sections 2, 4, 19                      |
| D002 | Next.js/React/TypeScript web and FastAPI/Pydantic backend                                  | Spec sections 3, 13; exact versions pending        |
| D003 | Pure offline compiler/replanner/renderer; authoritative SVG geometry                       | Spec sections 3-5, 8                               |
| D004 | Model proposals require deterministic validation and user approval                         | Spec sections 5-7                                  |
| D005 | Separate immutable plan versions, physical events and evidence                             | Spec sections 5, 10-12                             |
| D006 | @ResniDev owns compiler + Meta; @olartgabo owns product + validation                       | User instruction; supersedes spec's A/B allocation |
| D007 | PostgreSQL/private object storage production target; SQLite/local assets permitted for dev | Spec section 11; provider choice pending           |

## Pending decisions

| ID   | Question and required evidence                                                            | Owner                                  | Resolve before                   |
| ---- | ----------------------------------------------------------------------------------------- | -------------------------------------- | -------------------------------- |
| P001 | Resolved for workspace scaffold; schema integration review remains pending (D008 below)   | @olartgabo with @ResniDev              | #1 review                        |
| P002 | Resolved by D009: domain layout, generated schemas and error taxonomy                     | @ResniDev with @olartgabo              | #3 consumers                     |
| P003 | Session/auth mechanism and authenticated project/media access                             | @olartgabo                             | #6 persistence routes            |
| P004 | Hosting region, DB/object-storage providers, migrations, backup and deletion approach     | @olartgabo                             | #6/#16 deployment                |
| P005 | Actual inventories A/B, stand dimensions, material thickness and tools in hand            | @olartgabo                             | #2/#5 geometry                   |
| P006 | Three tested joint/repair strategies, measured tolerances and supported limits            | @olartgabo; @ResniDev encodes profiles | #2/#5 profile promotion          |
| P007 | Named device/mass, angle, surface, duration and repeated-use functional test              | @olartgabo                             | First physical build             |
| P008 | Live Meta access, actual endpoints/model IDs, SDK, region, quota, privacy mode and budget | @ResniDev                              | #4 live smoke gate               |
| P009 | SAM practical value versus manual box/label fallback                                      | @ResniDev with @olartgabo              | #4/#7 intake                     |
| P010 | Portal team eligibility, terms/media consent, deliverables and exact deadline/timezone    | @olartgabo                             | Day 0; recheck before submission |
| P011 | Independent builder availability and consented study scope                                | @olartgabo                             | #15 evaluation                   |
| P012 | Narrowing to tested templates/fewer operations if G2/G3 miss October 31                   | Both                                   | October 31 gate                  |

Use spec section 18 as the starting reference list for provider/competition
verification. No live external claims were revalidated by this scaffold.
Optional Image/Voice/3D decisions wait until physical P0 is green.

## D008: Workspace tooling, October 30, 2026

Owner: @olartgabo; reviewer: @ResniDev. Issue #1 uses npm workspaces for
`apps/web`, Node 22.21.0/npm 11.16.0, Next.js 16.4.3/React 19.3.1 and
TypeScript 5.9.3. The root Python project installs `forma_api` from
`apps/api/src`, using Python 3.12.6 and uv 0.11.16 with exact direct dependencies
and a generated lock. Prettier 3.9.10 formats web/config source; Ruff 0.17.3
formats/lints Python. CI runs the documented `npm run check` with no Meta key.

This provides two local processes without optional hosting or task orchestration.
The health route is liveness only. Domain packaging, schema export, generated
TypeScript paths and error envelopes remain P002/#3. The
[#1 handoff](handoffs/issue-1-workspace.md) proposes integration boundaries for
review; no domain consumer is implemented before agreement. No product scope or
physical verification claim changes.

## Recording a resolution

For each resolved pending item, add date, owner, chosen option, why it fits the
current scope, consequences, supporting issue/experiment and affected contracts.
Update the table status explicitly. If it changes the product, record the
spec impact instead of silently treating the old text as current.

## D009: Immutable domain and generated contracts, October 30, 2026

Owner: @ResniDev; consumer/reviewer: @olartgabo. Issue #3 resolves P002 by
installing `forma_domain` beside `forma_api` in the root wheel. Records forbid
extra fields and freeze nested records/tuple collections. Pydantic is the only
schema source. `npm run contracts:generate` exports JSON Schema/OpenAPI
components to `packages/domain/generated`, and readonly TypeScript to
`apps/web/src/lib/generated/contracts.ts`; `contracts:check` detects drift.
OpenAPI has no paths and creates no persistence routes.

The 12 operations form a closed discriminated union with typed arguments,
preconditions and effects. Flat bounded proposals confer no execution/commit
authority. Mutation wrappers carry expected version, idempotency and explicit
approval. See [the handoff](handoffs/issue-3-domain.md) for consumer obligations.
Material conservation, geometry, auth and transactions remain #5/#6/#10 work.
Synthetic fixtures are not measured stock. No product scope changes.

## D010: Local private persistence, October 30, 2026

Owner: @olartgabo; review requested from @ResniDev through the issue #6 PR.
The first #6 slice uses SQLite in an ignored local directory and explicitly
configured owner bearer credentials (`FORMA_API_TOKENS`). Missing configuration
disables project access. This resolves only the development part of P003/P004;
hosted identity, production storage and media retention remain pending.

Inventory has its own optimistic revision ID, separate from nullable active plan
version. API-local envelopes reuse domain Stock records and leave domain plan
mutation contracts unchanged. Confirmation stores what the user reports, including
unknown measurements; it does not authorize cutting. Serialized transactions
persist revision checks and idempotency outcomes together. Scope is project
creation/read, pre-plan inventory and deletion; media, immutable plans/events and
approved adaptation transactions remain open. See the
[#6 handoff](handoffs/issue-6-persistence.md).

## D011: Private local photo storage, October 31, 2026

Issue #6 extends the development SQLite store with project-scoped normalized
image blobs. Storing bytes and retry receipts in one transaction avoids partial
filesystem writes and makes project deletion atomic. This fits the local
fallback in D007; production object storage and hosted identity remain pending.

Uploads accept bounded JPEG/PNG/WebP images after complete decoding and remove
embedded metadata before persistence. Images remain private and are retained
until explicit deletion. Inventory photo references must belong to the same
project. Referenced photos must be unlinked before individual deletion; deleting
the project removes its photos. Deletion is logical and does not promise
forensic erasure or backup deletion. Provider transfer and public sharing are
unavailable in this slice; their consent and external-retention policy remain
pending. No measurements or physical outcomes are inferred from uploads.

## D012: Development intake access and API contracts, October 31, 2026

Issue #7 uses the existing configured owner credentials for the local intake
workbench. The person enters their development access key; it stays in React
memory and is cleared on disconnect or refresh. Reopening a project requires
its ID and reentering the key. This extends D010 without choosing hosted identity.

The web server proxies same-origin API requests to a fixed, server-configured
origin. It forwards the caller's authentication and never injects a shared
server credential. API-local Pydantic models generate their TypeScript envelopes
separately from the offline domain exporter, preserving the domain dependency
boundary and avoiding handwritten request/response schemas.

One stock row describes one physical item. Blank dimensions remain unknown;
entered measurements require explicit confirmation. Existing measurement
provenance and usable regions remain intact. Saving inventory does not compile
a design, authorize cutting or establish a physical test result. Manual stock
editing and photo linking work without a model. Segmentation boxes, tools and
design constraints require later contracts; they are not represented by guessed
fields in this slice.

## D013: Persisted build requirements, November 1, 2026

Issue #7 now records available tools, a device description and existing domain
constraints with inventory confirmation. They share the inventory revision so
planning can consume a consistent set of user-confirmed inputs. Older projects
have null requirements; older clients preserve requirements when omitting them.
Known values require confirmation and the same provenance categories as stock;
unknown values remain unknown. The API rejects unresolved evidence/profile IDs.
This extends D012 without changing compiler or proposal contracts. See the
[requirements handoff](handoffs/issue-7-requirements.md).

The product has one connected planning/build journey. Running deterministic
validation without provider access is an implementation/testing property, not a
separate product mode. Live interpretation/design remains integration work.

## D014: Immutable initial plans and manual review, November 1, 2026

Issue #6/#11 stores only accepted compiler/renderer output through an internal
trusted producer boundary. The browser can read scoped previews and explicitly
approve one against the current inventory revision; it cannot upload a plan or
mark a supplied plan valid. Plan/manual bytes stay immutable while a transaction
sets the active pointer. Physical work remains separate and is never inferred
from approval or navigation.

Manuals include written instructions, checkpoints, BOM and authoritative SVG with
an enlarged view for inspecting dimensions on phones. Live model production,
real measured process/profile intake, physical history and repair activation remain
separate work. See the [handoff](handoffs/issue-6-plan-activation.md).

## D015: Consented connected Muse design production, November 1, 2026

Issue #9 connects saved project facts to Muse proposals and D014's existing
trusted compiler/renderer producer. Generation requires owner authentication,
expected inventory revision, literal transfer consent and request identity.
The browser supplies notes, not trusted geometry, profiles or a BuildPlan.
A scoped read-only snapshot tool loads saved facts; proposals must reference
those facts and pass existing validation before becoming immutable previews.
Generation never approves a plan or records physical work.

An explicit server-owned `FORMA_DESIGN_CONTEXT_PATH` manifest resolves process,
stand parameters, profiles and allowances for an exact project/revision. Missing
context returns blockers/questions; no implicit catalogue or measured values
are invented. Production rejects synthetic evidence. Tests may explicitly inject
synthetic context and remain software checks, not physical evidence.

Uncertain provider outcomes retain a durable receipt and cannot be silently
restarted with the same key. The client requires an explicit fresh start and
new consent after uncertainty. A completed request replays without model calls;
capacity limits preserve already saved previews and their result receipt.

Meta Chat Completions supports automatic tool selection only. Request a tool
with the supported protocol, then enforce its name, arguments, count and result
locally before accepting final typed output. A skipped or invalid tool blocks
the request; it never becomes a successful proposal through a fallback.

## D016: Read-only connected failure-photo diagnosis, November 1, 2026

Issue #9 permits consented photo-only diagnosis before a calibrated plan exists.
The canonical DiagnosisProposal separates observations, hypotheses and questions;
without a plan, affected IDs must be empty. When an active plan/operation is
selected, server-owned expected arguments and geometry inform reasoning without
asserting physical completion. Each photo transfer consumes its consent. No
state mutation or repair execution follows from a diagnosis; real history and
separate validated repair approval remain required.

## D017: Provider-reported request usage, November 1, 2026

Connected intake/design/diagnosis diagnostics optionally expose request-local
model-call and provider-reported input/output token counts. Missing or malformed
counts remain unknown, including incomplete aggregates. Never infer actual
billing from local reservations or present token estimates as provider charges.
Generate the nested API type from Pydantic; emit no prompt, credential or raw
provider response. Fresh request trace sinks preserve prior gateway history
without counting it again.

## D018: Explicit physical reports and failed-check gating, November 1, 2026

Issue #11 records authenticated user reports against the active plan and last
physical-event cursor. The server derives immutable domain evidence/events and
material receipts from the referenced operation. User-reported work is separate
from approved plans; neither navigation nor models complete a step.

Failed inspections/tests pause further confirmations. The current replanner has no
same-plan failure-resolution contract, so a later pass cannot silently clear the
failure. Diagnosis/revision integration must resolve it explicitly. Expected stock
is a calculated, unconfirmed projection requiring actual reconciliation before
repair. See the [handoff](handoffs/issue-11-physical-progress.md).

## D019: Photo-excluded initial Proof snapshots, November 1, 2026

Issue #14 uses one owner-scoped read transaction for project, versions, user
history, evidence and material receipts. Exported copies omit structured image
references; private originals remain unchanged. Explicit local text/JSON downloads
include user notes and a generated snapshot time. No sharing route or photo consent
is inferred.

Coverage is limited to initial plans and user reports. Repair diffs, evidence
invalidation/freshness and measured waste/salvage totals remain unavailable.
Pending downloads are invalidated by known report changes, including while the
panel is closed. See the [handoff](handoffs/issue-14-proof-summary.md).

## D020: Stand replacement roles and stable core manual steps, October 31, 2026

Stand continuation validates active panel roles through joint topology while
retaining retired parts and their original cuts as history. The renderer and
replanner callback share the same family checks. Supplemental replacement cuts
use separate headings; the original eight core slots keep stable numbering so
unchanged visible panels retain their hashes. Hashes still cover the entire SVG.
Grouped cuts are preserved while their other outputs remain useful; retired-part
material loss is explicit. This changes no schema, physical claim or approval flow.

## D021: Brace-only explicit tape undo, November 1, 2026

Issue44 adds an offline continuation for the canonical attached brace after the
original six-operation construction prefix. Rear/apex peels are new incomplete
operations; old definitions/consumption remain immutable, front hinge is kept,
and remaining measured stock funds replacement. The manual validates historical
and active stages separately. Exact fold invariants apply to both paths.

Completed final fit/function checks block before construction of this candidate;
the current slice does not rewrite or drop their completion history. Base/support
replacement and generic physical inverses remain unsupported. Synthetic
compile/simulate/rank/render regression evidence does not establish a bench pass.

## D022: Completed-build brace history, November 1, 2026

The attached-brace continuation also supports all eight original operations
completed. It retains all original operation/checkpoint definitions and IDs and
appends explicit recovery work and new fit/function checks with unique state and
checkpoint IDs. Old dependent evidence/checks invalidate; they are not treated as
useful current verification. No event/evidence/transaction/salvage is created.

This supersedes the initial slice's completed-final-check gate. Six, seven and
eight completed original operations use 14-, 15- and 16-step layouts; base/support
changes remain blocked. Validation and rendering share a narrow stage resolver
instead of duplicating the validator. Original checkpoint
references must match their operations before construction; malformed history
returns blockers. Synthetic replay/manual evidence is not a physical pass.

Unfinished final operations can receive replacement identities only when no
persisted event, evidence or transaction references the retired operation or its
checkpoint. Otherwise the proposal blocks before mutation. The same rule applies
to the original six-operation path; saved history is never silently dropped.

## D023: Approved repair revisions and failed checks, November 2, 2026

Issue #12 activates a repair only through an explicit approval that names a
server-stored preview, the expected active version and the history cursor. The
server re-derives the simulation from saved history inside the commit
transaction; the browser never supplies a plan. The new version carries the
completions the replanner preserved and records evidence invalidations; parent
history stays unchanged.

A user-reported failed inspection or functional test is a known outcome, not
uncertainty. It no longer blocks repair simulation because its check never
completes and every repair must repeat it. Other failed, unknown or invalidated
records still block. See the [handoff](handoffs/issue-12-adapt-revision.md).

## D024: Versioned Proof and evidence freshness, November 2, 2026

Proof now includes approved repair records and evidence invalidations in its
owner-scoped consistent snapshot. Ancestors of the active plan are historical;
unselected designs remain previews. Original evidence retains its provenance
and recorded outcome while dated notices identify the revision that invalidated
it and the reason. Carried completions are distinct from new user reports.

Approved repair requirements and proposed material deltas remain separate from
physical actions and receipts. Private photo references are excluded from all
exported copies, including the nested revision simulation plan. Source records
stay unchanged. No physical success, measured waste, salvage or build duration
is inferred from repair approval. See the [Proof handoff](handoffs/issue-14-proof-summary.md).

## D025: Muse-written code with a Claude review loop, October 31, 2026

Owner: @ResniDev. `tools/devloop` is development tooling for the @ResniDev
lane. Meta Muse Spark writes the code changes. Claude models are used only as
planners and reviewers (task specs, approve/revise verdicts, proposed issues);
their output is never applied as code. Commits and PRs carry no assistant
attribution, enforced by `.githooks/commit-msg` and the `attribution` CI job.
Meta spend is capped at $90 by a local ledger. The loop opens draft PRs only;
humans review and merge. No product scope changes; CI gains one job (handoff to
@olartgabo for `.github/workflows/checks.yml`).

## D026: Codex coding fallback and Muse preference, October 31, 2026

The user authorizes Codex agents to implement code as well as plan and review.
Muse remains preferred for raw implementation to use promotional Meta credits;
Codex handles architecture, task selection, integration context and independent
review. This supersedes D025's exclusive code-author rule without changing the
product's bounded runtime flow or ownership lanes.

The user reports roughly $130 remaining Meta credit and wants to use almost $100
while retaining $30. These are an intended reserve and approximate account
balance, not a new per-run allowance. Existing usage across both local ledgers,
uncertain requests and other clients must be reconciled before provider dispatch;
do not reset history or silently raise the existing lifetime cap. PR #33 remains
draft until its reproduced runner defects are repaired and verified. No physical
or live-provider acceptance is established by development-agent work.

## D027: Muse implementation, tests and repairs; bounded premium review, November 1, 2026

The user directs Muse to own implementation, regression tests, offline check
execution and ordinary repairs. Codex or Claude plans a coherent feature, reviews
its final green change, or diagnoses after two unsuccessful Muse repair attempts.
This supersedes D026's routine premium implementation/test-authoring fallback.
Use fresh feature sessions and small checkpoints with native automatic compaction;
never replay entire supervisor transcripts or reset repair/spending counters.

The guarded Node launcher uses the existing external budget authority; the legacy
Python command exits before dispatch. Existing lifetime cap, reserve, STOP,
uncertain-outcome accounting and finite verification window remain in force.
No product runtime, contract, ownership, or physical acceptance changes.

## D028: Monitored own-work loop without the fixed90 cap, November1,2026

The user removes the fixed90USD limit while monitoring and asks for continued
Muse development, delegation, review of their submissions and code cleanup.
The external guard retains append-only accounting, durable reservations, STOP,
finite verified funding and no paid fallback. Its allowance is based on current
verified free credits with the existing30USD reserve and a billing-lag buffer;
the original ledger is never reset or rewritten. Development roles in D027 stay.
Continue ResniDev-owned issues/PRs and open only concrete useful followups. Reuse
original issues instead of multiplying equivalent loop-proposed tickets. Product
runtime bounds, ownership and physical-evidence requirements are unchanged.

## D029: Allow bounded runtime responses through the web, November 2, 2026

Intake, design, diagnosis and repair proposal requests wait up to 130 seconds
in the browser, covering the gateway's permitted 120-second maximum plus response
validation and persistence. Ordinary project, media and history requests retain
their 30-second browser deadline. The Next.js API rewrite uses a finite
140-second proxy timeout so it does not cut off runtime responses first.
Cancellation stays available and the browser never retries provider requests.
Server model budgets, retry counts, consent and physical evidence gates stay
unchanged. Hosted infrastructure must also permit these response times.

## D030: DigitalOcean hosting preference, November 2, 2026

The user selects DigitalOcean for the hackathon deployment, with AWS available
as an alternative. The user expects student credits; eligibility, activation and
available balance remain unverified. This records the preferred provider without
provisioning resources, committing spending or selecting a deployment region.
Continue connected-flow work before spending more time on hosting. Hosted
identity, storage, retention and actual deployment verification remain pending.

## D031: Reconfirm remaining repair materials after changes, November 2, 2026

Editing a remaining connector measurement or withdrawing its confirmation clears
earlier repair previews and simulation retries. Reloading recorded work clears
all entered connector lengths and their confirmation before fetching, including
on read failure. A fresh simulation requires fresh physical confirmation; no
previously calculated or user-entered length is silently promoted for new history.
Pending activation locks the material inputs and retains its exact retry payload
because approval may have already committed. This changes browser freshness gates, not server stock
accounting, model authority or the evidence required for a physical pass.

## D032: Keep uncertain diagnosis outcomes visible in Proof, November 2, 2026

Dispatching an active-step diagnosis invalidates earlier Proof snapshots and
pending exports. Downloads stay blocked while the browser knows the request is
pending. Cancellation, a lost response or a context change can leave server-side
evidence persistence unknown; they do not establish that the server stopped.
That uncertainty remains visible even after another diagnosis succeeds.

The user may explicitly refresh saved history and acknowledge an as-of report
before downloading fresh history dated by its generation time. This is a snapshot
of saved records, not proof that an unknown request finished; evidence may arrive
later. A new request, refresh or snapshot context invalidates the acknowledgement.
There is no automatic provider retry, and each new diagnosis needs fresh consent.

This protection is limited to the current connected browser session.
Uncertainty is retained separately for each project visited in that owner session;
diagnosing another project cannot settle an earlier project's unknown outcome.
Disconnecting clears the owner session and its in-memory history.
It adds no durable server job status or outcome reconciliation contract;
reconnecting or refreshing the application cannot recover an earlier unknown
request's status.
The browser regression intercepts synthetic API responses and establishes no live
provider or physical result.

## D033: AWS EC2 hosting for the demo, November 2, 2026

The user moved the hackathon deployment from DigitalOcean (D030) to AWS
`us-east-1` and approved one `t4g.small` instance at roughly $0.58 per day.
SQLite and private media stay on the instance's encrypted volume; stateless
container services were rejected because they lose local disk on restart.
Caddy serves HTTPS on an sslip.io hostname for the Elastic IP. Owner bearer
tokens and the optional provider key live in SSM Parameter Store, not git.
The host has no SSH; administration goes through SSM. This resolves P004 for the
demo only. Backups, token rotation and provider-side retention stay unverified.
See [hosted deployment](deploy.md).

## D034: Damage reports pause the build, November 2, 2026

The user approved a damage report on each manual step. `POST /projects/{id}/damage`
records a user-reported `damage` event with `user_report` evidence and optional
photos, scoped to the step and the damaged part IDs. The builder confirms what
they saw, so the event and evidence are `user_confirmed`; the replanner accepts
only that state, and then only a replacement of a damaged part. Like a failed
check, a damage event sets the build to needs review and pauses further
confirmations until an approved revision. It consumes no stock, marks no
operation complete and needs no provider. The progress snapshot lists
`damaged_part_ids`, and Adapt starts a repair draft on the first damaged part.
Asking Muse to diagnose the damage stays optional. Standalone measurement events
are not added because no compiled plan requires a recorded measurement.

## D035: Recorded waste and salvage follow the replanner ledger, November 2, 2026

`POST /projects/{id}/materials` records material the builder discarded, lost or
recovered at a step, as a user-confirmed `measurement` event and evidence plus a
`waste` or `salvage` material transaction. Only losses the replanner can
reconcile are accepted: a whole current sheet region discarded, a measured
connector length lost at a tape joint that uses it (up to the calculated
remainder, with a confirmed original length), or a region wasted earlier in the
same version recovered. Expected stock applies these records, so the remaining
stock a repair simulation checks matches the ledger. Partial sheet waste needs a
measured split and stays unsupported. Proof labels measurement evidence
"manually measured", labels Muse evidence as unverified observations and
hypotheses, and totals only the waste and salvage the builder recorded.

## D036: Begin evidence-aware stability contracts, November 3, 2026

The user authorized the implementation specification in #142. Begin with the
engine-owned quantity, identity, policy and report contracts, generated from
Pydantic for browser consumers. Modeled outcomes and physical observations stay
separate; missing required checks cannot become an overall modeled pass.
This is the initial S0 slice, not a completed mechanics engine or connected
feature. The shared assembled-geometry producer belongs to #144, and operation
state semantics belong to #141. Their handoff remains a dependency before the
mechanical adapter consumes actual plans. Do not reconstruct a second geometry
authority from cutting rectangles. See [the stability handoff](handoffs/engine-stability.md).

## D037: Connect conditional tipping reports without inventing poses, November 3, 2026

#142 now computes scalar, gravity-only tipping from externally resolved physical
geometry, with explicit provenance, uncertainty blockers and separate strength
and sliding limitations. NumPy and Shapely are pinned dependencies; installed
distribution notices are retained. The active manual can request a scoped
read-only analysis and display its report and SVG overlay. Only server-resolved
physical inputs are accepted; current inventory, active plan and full history
cursor gate the computation. Requests create no physical observations or approval.

The #144 canonical geometry producer is not implemented in this lane. Its owner
must agree the published frame/stage handoff and supply the shared producer.
Until then, production shows missing geometry, while explicitly labeled analytic
software tests exercise the calculation and connected rendering. This does not
complete S1 same-plan acceptance, S2 persistent reports or a physical demo.

## D038: Complete stability dependencies in this lane, November 3, 2026

The user explicitly superseded the ownership wait in D036/D037: do not leave
work for Gabo if that prevents completing the engine. This lane now implements
the shared canonical geometry and connected stability dependencies, with a
documented interface reusable by the viewer and fabrication engines. The prior
handoff proposal remains historical; another engineer's agreement is no longer
a prerequisite for implementation. One canonical producer must serve consumers.

Supported nominal geometry describes the planned assembly, not observed contact
or completed construction. Unknown mass, device placement, material properties
and physical observations remain unknown. Native independent review and passing
checks still precede publication; provider STOPs and finite live-test controls
remain unchanged. No physical success follows from this authorization.

## D039: Measured stability and a separate engine lab, November 3, 2026

Issue #17 now sequences ResniDev's #146–#149 separately from Gabo's #150–#152.
The user requested continuing #146 and a direct way to assess the calculation
engine. This work builds on PR #145 without merging that draft implicitly.

The bounded measured model weighs the assembled stand including its connectors
as one body covering all canonical source parts. It captures measured world COM,
two explicit device orientation cases, actual rectangular support contacts and
a chosen physical reserve. Typed immutable batches retain methods, instrument
resolutions, observations, applicability assumptions and evidence references.
They require reported assembly, owner scope, exact inventory/history and explicit
confirmation. Corrections append records and invalidate previous calculations;
measurement events do not complete construction or pass physical tests.

The current numerical model evaluates point estimates. Instrument resolution is
recorded and shown, but is not a conservative uncertainty bound or propagated
error guarantee. Standard gravity and rigidity/stationary-load assumptions are
explicit; sliding, retention, joint strength and deformation stay unverified.

The loopback engine lab calls the same pure evaluator with hypothetical inputs.
It has no project database, account, provider or evidence writes. Its examples
test mathematics, and cannot be promoted to user measurements. Downloadable
input/report JSON makes feedback reproducible independently of the app UI.

User feedback correctly identified that a support rectangle does not demonstrate
stage-aware 3D mechanics. The lab therefore inspects the actual compiled stand
through the existing canonical producer, retaining the rectangle as an analytical
unit case. Unsupported intermediate poses remain explicit rather than borrowing
the final assembly's support. Issue #153 owns the next physical-stage extension;
Gabo's fabrication, repair search and product viewer scopes remain separate.

## D040: Explicit physical stages and bounded material checks, November 3, 2026

The user requested 360-degree diagnostic rotation and implementation of
intermediate physics, sliding, joint strength and deformation. The engine now
accepts explicit stage transforms, source masses/COM and body contacts, partitions
active load-bearing components and evaluates each separately. The direct lab's
camera does not change physical coordinates or calculation identity.

Additional checks use explicit Coulomb contact demands, named scalar joint
allowables and named Euler-Bernoulli beam conditions. They do not infer friction,
cardboard stiffness, joint capacity or internal load paths from appearance. Unknown
properties remain unresolved. The stage API authenticates current reported work
but accepts hypothetical physical inputs only; observed stage capture remains
future work. See [stage mechanics](handoffs/stability-stage-mechanics.md).

## D041: Fabrication reports model the next step from declared rules, November 3, 2026

Issue #150 adds a read-only fabrication report for the active manual and each
saved repair preview. It replays the plan lineage's recorded reports, derives
joint attach/detach from confirmed operation effects, reruns the existing
compiler and reads the existing expected-stock ledger. Declared rules
(`fabrication-rules-v1`) add what the compiler does not check: the family's
recordable operation types, conservative access (a part held by an attached
joint cannot be marked, slotted or folded until an explicit detach) and tool
classes per operation. Unknown joint access and unknown connector lengths block.
Tool gaps are listed as required confirmations instead of blockers, because
saved tools are locked while a plan is active and a blocker would leave the
builder no way forward. The report is modeled, not observed: it never completes
a step, authorizes cutting or changes stock. See the
[fabrication handoff](handoffs/issue-150-fabrication-report.md).

## D042: Repair search enumerates existing operators and reuses approval, November 3, 2026

Issue #151 adds `POST /projects/{id}/repairs/search`. It generates repairs only
from operators the simulator already supports: replacement from remaining usable
sheet stock, resize to a size the user measured, and swapping a joint to another
allowed tested profile. Angle changes are not generated because they would need
an invented angle. At most 12 candidates are simulated; each feasible one must
also pass the #150 fabrication report. Ranking uses known cost, undo, preserved
work and measured material; time, price and strength stay unknown, and stability
is reported as unverified because no stability report covers repairs yet. The
top three are stored as ordinary previews, so approval is the existing atomic
`adapt/commit`. Search records no physical work. `exhausted` (the limit stopped
the search) is reported separately from `infeasible` (everything was checked).
See the [repair search handoff](handoffs/issue-151-repair-search.md).

## D043: Attached-base tape undo, November 3, 2026

Issue #151 carries forward the attached-base replacement left out of D021. Once
the fold and all three joins are complete, replacing `stand-base` stages front
and rear `peel_tape` detaches, a replacement cut and inspection, and new
front/rear joints in the original part order; the apex hinge stays attached and
preserved. Peeled tape is lost and never refunded; only the two reattachments
consume tape. The first peel waits on the apex attachment so the new functional
test's required apex joint is an ancestor. The tape-undo helper, the family
validator and the renderer now resolve the replaced role (brace or base) from
the staged joints; brace plans and manuals are unchanged. Support replacement
would undo a completed fold and stays blocked, as do a second repair of a
replacement and other repeated-repair depth. Synthetic regression evidence does
not establish a bench pass. See the [handoff](handoffs/issue-151-attached-base.md).

## D044: Combined latest work and user-authored assembly diagnostics, November 3, 2026

The user requested Gabo's latest published work and a friendlier engine that can
evaluate many shapes step by step. The integration branch combines fabrication,
repair search and attached-base recovery with the stability work without merging
unfinished remote PRs. Necessary shared-file resolutions preserve both lanes.

The primary diagnostic now authors polygonal panels and explicit per-stage poses,
contacts and edge joints. A generic producer validates geometry and source seams;
it shares the component solver with the original stand adapter. Examples are data,
not geometry-dispatch branches. Future parts cannot contribute support or mass.
The editor does not extend the production fabrication compiler's supported family,
infer physical properties or create observed work. See the
[generic assembly handoff](handoffs/generic-assembly-diagnostic.md).

## D045: Reconcile fabrication readiness with explicit report-only confirmations, November 3, 2026

The user chose PR #154 as the baseline and asked to retain useful parts of both
implementations. Keep its lineage/boundary replay, GET routes, next-step manual
navigation, transition IDs and deployment packaging. D041's tool-gap behavior is
superseded: unavailable tools and unconfirmed connector balances block readiness.

An authenticated read-only assessment can add actual available tool names and
fresh measured connector lengths after explicit confirmation, bound to expected
active version, inventory revision and history cursor. They apply only to that
report. Different measured balances require material-loss records or separate
reconciliation; they never silently modify inventory, ledger, evidence or work.
Clear/refresh and project/version/history changes discard these confirmations.
Repair previews keep their saved simulation measurements and are re-simulated
against authoritative inputs before reporting.

The combined engine hashes all typed inputs, including profile evidence and
validation mode, and validates remaining-stock provenance and confirmed physical
history. Independent preparation precedes attachments; explicit supported
join/detach/preparation/reattach sequences remain available. Declared access and
tool availability establish neither observed usability nor physical suitability.
No provider call or physical pass follows from these software checks.

## D046: Generate construction proposals and retain fabrication authority, November 3, 2026

The user requests automatic steps from a finished target rather than manually
authored intermediate states. The generator expands the target part/joint graph
and evaluates each proposed placement and connection with the shared physical
engine. It neither invents temporary support nor reuses final load demands for
different intermediate assemblies.

A dedicated opt-in synthetic bridge proposes rectangular cut, inspection and tape
operations, then calls Gabo's existing compiler/fabrication report. Fixed resources
and profile/process fixtures are explicit. Nonrectangular cutting, inadequate
stock and unsupported process conditions remain blocked. This integrates the
latest fabrication safeguards without creating a competing scheduler or recording
completion. Production observed stock/process capture and physical approval remain
separate. See [generated construction](handoffs/generated-construction.md).

## D047: Material-bound construction and shared piece references, November 3, 2026

The user requests real-material construction proposals, more shapes and a common
piece vocabulary for MetaMuse, plans and diagrams. A supplied-material adapter
allocates only declared stock regions and calls the existing fabrication engine.
The authenticated read-only consumer resolves saved inventory and trusted process
context, rejects stale revisions and directs active builds to the history-aware
repair flow. Local lab imports remain explicitly unverified. Synthetic resources
cannot be combined with actual-material input.

Named pieces keep immutable mechanical IDs and derived stable references.
Geometry classification is calculated; user/model role and naming suggestions
are retained separately without becoming physical evidence. Parametric polygon,
enclosure and screen targets share the generic constructor, while unsupported
polygon cutting remains blocked. These interfaces support model proposals; they
do not replace AI reasoning, infer photo measurements or record completion.
See [material construction](handoffs/material-construction.md).

## D048: Connect MetaMuse to checked construction proposals, November 3, 2026

The user requests photo/materials and goal intake that lets MetaMuse propose
shapes, piece names and construction ideas using engine checks. A separate
consented project route accepts notes and an optional saved photo, resolves
inventory and reviewed context on the server, and sends a bounded typed proposal
request through the existing gateway. Model geometry becomes a hypothetical
finished target; the engine generates intermediate steps and calls Gabo's
fabrication checks. Model output cannot confirm physical facts or activate work.

At most two candidates are evaluated. One optional correction may use engine
feedback while retaining the original rejection. Unsupported manufacturing and
missing evidence stay blocked. Durable request receipts prevent changed-key
retries from bypassing in-progress/unknown outcomes. The isolated proposal panel
renders engine facets, names and reports without replacing the existing manual
or repair viewer. Live acceptance remains a separate bounded, authorized test.
See [MetaMuse construction](handoffs/muse-construction.md).

## D049: Expose material gaps and named construction stages, November 3, 2026

The real-material proposal flow shows missing or unconfirmed saved measurements
before generation, named stage selection, piece presence and unresolved stage
checks. These are projections of existing typed records, not a second readiness
validator. MetaMuse proposes geometry and names; deterministic engine rejection
and Gabo's fabrication report retain authority. No photo-derived value becomes a
measurement, and inspecting a stage neither approves a plan nor records work.

## D050: Blueprint workbench, November 3, 2026

The project workbench uses a blueprint grid and a section rail. Saved manuals
index drawings by operation and show planned parts with their source stock and
dimensions. Blueprint colors are a browser presentation of the compiled SVG.
Builders can switch to the original colors and download the original SVG.
The entry screen uses a full-width drafting surface with a labeled stand
illustration and a separate credential strip. The illustration has no
project dimensions or build instructions.
The opening animation plays once per document load. Reduced-motion visitors
see a static wordmark until the workbench hydrates.
The manual uses the current compiled views. A rotatable assembly view remains
subject to the physical P0 gate.

## D051: Give MetaMuse localized canonical geometry feedback, November 3, 2026

Rejected construction proposals expose bounded piece or connection references
and allowlisted canonical geometry diagnostics to the existing single correction
request. Diagnostic probes reuse the geometry producer; they cannot accept a
candidate or invent measurements. Raw exception payloads, notes and labels are
excluded. The two-candidate limit and fabrication authority remain unchanged.

## D052: Use the supplied FORMA vector artwork, November 3, 2026

The shared wordmark uses the supplied vector artwork and retains the existing
header and loader colors. The browser icon uses the supplied logo in site blue.

## D053: Saved stability reports and read-only MetaMuse stability tools, November 3, 2026

Stability calculations can be saved as immutable reports keyed by the engine
cache hash. History shows each report as current or stale with named reasons;
stale reports remain readable. Two reports compare only check by check, and only
under the same policy, cases and engine versions. MetaMuse gets two allowlisted
read-only tools, `analyze_stability` and `explain_stability_inputs`. Their
arguments select server-authorized identities and cases only. A report is
modeled evidence of nothing physical, and MetaMuse cannot add measurements,
confirm inputs or approve plans.

## D054. Use the cube for long construction requests, November 3, 2026

The construction proposal shows its text status and Cancel on dispatch. After
10 seconds waiting for the proposal response, a blueprint-blue Rubik's Cube
appears below the request controls. It reverses three quarter turns when a
rotatable construction preview is ready. Results display immediately. Errors,
cancellations and blocked results clear the cube. Reduced motion shows a static
cube during the wait and skips the solve. The animation reports no percentage
and does not indicate physical acceptance.

## D055: Bounded stock-feasible stand search, November 3, 2026

Design search (#148) enumerates a finite step-aligned grid of panel width,
support length and base depth for each saved single-region sheet, tape stock and
reviewed tape/fold profile pair. Grid bounds come from confirmed device sizes,
the sheet's usable region and the footprint limits; the support angle is the
user's requirement and the lip comes from the confirmed stand parameters. Every
grid point is compiled by `compile_stand` and the independent validator. A node
budget (deterministic) and a time guard bound the search; running out is
reported apart from infeasibility. At most two acceptable designs are proposed,
ordered by consumed sheet area, then panel area, then their values; the second
prefers another sheet or base depth. Stability, retention and joint strength
for an unbuilt geometry stay missing, incompatible or unsupported. Measurements
of another assembled stand never transfer. Search and probe write nothing.
Selecting a design saves an ordinary preview through the existing plan
transaction; activation remains the separate approval. An active build changes
only through the existing repair simulation.

Review repair, same day: compiler requests for measurements, confirmations or
reviewed profiles make a search `needs_input`, never `infeasible`. Candidates
are generated lazily and the time budget covers final evaluation. MetaMuse may
compare the proposed designs through one read-only tool, `compare_stand_designs`,
choosing only authorized candidate IDs and one grid probe value; the probe is the
engine's result, shown apart from the model's words.

## D056: Deploy main automatically, November 3, 2026

The user asked for every `main` commit to reach the hosted demo without a
manual step. A GitHub Actions workflow runs after `Offline checks` passes on a
push to `main`, assumes a narrow IAM role through GitHub OIDC and runs the
existing update steps on the instance through SSM Run Command. No long-lived
AWS keys are stored in GitHub, and the host still has no SSH. The role trusts
only this repository's `production` environment, which accepts deployments from
`main` only. Deploys run one at a time and never move the host to an older
commit. See [hosted deployment](deploy.md).

## D057: Measurement decisions from compiler thresholds, November 4, 2026

The app asks for a measurement (#149) only when a confirmed value can change a
supported decision: whether a saved sheet or tape can be used by the stand
search, or whether a built stand's modeled tipping result can be computed.
Sheet and tape thresholds are found by compiling the smallest searched design
on hypothetical stock, never by a second geometry rule; that stock never
becomes a candidate. Questions follow a fixed order with stock-ID ties and no
probabilities or effort scores. Answers use the existing inventory confirmation
or the #146 measurement form; a "measurement unavailable" marker is the only new
record. Unbuilt candidates' stability returns "physical test or model extension
required" rather than reusing another stand's measurements.

Thresholds are computed per sheet material, only over reviewed tape and fold
profile pairs for that material, and are reported in 0.1 mm steps; a confirmed
value below a rounded threshold is decided by compiling at that exact value. A
compiler refusal of unlimited stock for an input reason (for example missing
profile evidence) is reported as unsupported, not as infeasible.

Server design settings are reviewed for one inventory revision. When the
current revision has none, the newest earlier revision that has them is used
for stock that is still the same item: the same stable stock ID, kind and
material in every saved revision since, read from the inventory route's own
receipts. Only measured facts may differ, and the search, compiler and
fabrication report recheck them. Stock added, removed and re-added, or changed
in kind or material is left out of the search and named; removed stock is
named; a changed tool list drops only the tool confirmation. Evidence is used
exactly as recorded and never renewed or confirmed. The revision's own
settings always win, an invalid or unreadable earlier entry is never used,
and without a complete history the operator prerequisite stays.

## D058 - Hosted SAM photo localization; no generated 3D physics (November 4, 2026)

Connect the existing SAM 3.1 gateway to explicitly consented, private JPEG/PNG
photo localization. Source-pixel boxes and a manually adjustable fallback produce
an unverified, locally reviewed named photo reference. They never create stock,
measure millimeters, infer density/COM, alter canonical geometry or record evidence.
Exact-body browser recovery receipts and server pending/terminal receipts prevent
silent repeated paid requests; unknown outcomes require operator reconciliation.

The official [model catalog](https://dev.meta.ai/docs/models) lists hosted SAM 3.1;
[SAM documentation](https://dev.meta.ai/docs/sam/overview) defines source-pixel
boxes and valid empty matches. This slice consumes boxes only, not masks.
[SAM 3D Objects setup](https://github.com/facebookresearch/sam-3d-objects/blob/main/doc/setup.md)
requires Linux and at least 32 GB GPU memory; the inspected local GTX 1660 Ti has
6144 MiB. Reconstructed hidden surfaces would be proposals, not measured material
or center-of-mass evidence. No 3D hosting or dependency is added. Future calibrated
multi-view reconstruction needs a separate evidence contract before physical use.
No live SAM inference or physical acceptance is claimed by this implementation.

## D059: Inspect canonical assembly geometry in the manual, November 3, 2026

The user requested issue #152 after the canonical geometry baseline merged.
The active manual adds an owner-scoped assembly viewer using that producer's
exact facets, part IDs, stage and geometry hash. The display adapter projects
those coordinates; orbit, zoom and separated-part offsets change presentation
only. Selecting a part or operation navigates the existing manual and records
no physical work.

This explicitly authorizes the scoped viewer despite the earlier physical-P0
pause on optional 3D presentation. Unsupported partial, damaged, detached or
repaired states retain the authoritative SVG/history fallback. Planned and
user-reported assembly remain nominal; absent matching numerical overlays are
shown as unavailable. No camera action dispatches analysis or changes evidence.

## D060: Bind displayed stability claims to saved results, November 4, 2026

Following the merged #147 and #152 implementations, MetaMuse selects a bounded
focus from authorized saved cases and check types. The server derives displayed
statuses, explanations and cautions from the saved engine report. Model-written
prose cannot assert a physical pass. Completed older receipts retain their request
identity and usage but receive the same deterministic presentation; unresolved
provider outcomes continue to block new dispatches.

The assembly viewer reads matching saved reports without running analysis. Report
identity, canonical geometry, measurements, profiles, history and engine dependencies
must match the current authorized context. Missing or stale overlays remain
unavailable. Camera controls and case selection change display only; separated
parts hide world-coordinate overlays. Stored reports remain readable after an
engine or numerical dependency upgrade and are marked stale.

## D061: Reference-scaled planar photo estimates stay estimates, November 4, 2026

The user requested photo-first intake with calibrated dimension estimates (#177).
This deliberately changes #7's rule that image-derived sizes stay unknown: a
flat sheet or strip photographed beside a verified reference may now prefill an
unconfirmed `photo_estimate` value. The domain validator forbids a confirmed
`photo_estimate`, so every existing confirmed-measurement gate still requires a
ruler value; "save estimated dimensions" never becomes "measured".

Method: OpenCV 5.0.0.93 ArUco detection and a least-squares planar homography,
with optional lens correction bound to an exact uncropped image size (library
only for now; the API does not yet store calibrations, so app estimates are
uncalibrated and say so). The
printable FORMA card has four markers (16 points), so the fit has residuals and
each marker can be predicted from the others; a single marker or a user-marked
rectangle is accepted but reported as having no independent check. The printed
check lines must be measured with a ruler, because printer scaling is not
observable in the photo. Outlines are seeded from SAM or manual boxes, segmented
against the surrounding surface and snapped to the colour edge; the measured
edge scatter raises the outline uncertainty, and ragged or non-square outlines
give enclosing dimensions only, never stock size. Uncertainty is a stated
Monte Carlo sensitivity, not a calibrated confidence interval.

Rejected: a single pixel-per-millimetre scale (wrong under perspective); one
known line length (does not define plane geometry); bounding boxes or convex
hulls as stock (overstate usable material); learned metric depth (Depth
Anything 3, Depth Pro) or reconstruction (COLMAP) without a measured
improvement on our materials, compatible licences and deployable resources.
Accuracy on real photographs is unvalidated until the evaluation procedure in
the [photo measurement handoff](handoffs/issue-177-photo-measurement.md) runs.

## D062: Recognition categories are not fabrication materials, November 4, 2026

The user extended #177 to an initial catalog of 48 everyday categories. They are
recognition categories: what a visible object probably is. Identity, a
suggested material family, visible form and fabrication support are separate
fields. Seven categories map onto build rules that already exist (corrugated
cardboard to a cardboard sheet; thin packaging card and cardstock to a
paperboard sheet; duct, masking and clear tape to tape; string or twine to
cord). The other 41, and every `other` or `uncertain` answer, are shown as
"Identified; build rules not available yet" and can never link to a stock, so
recognised inventory stays visible without enabling operations. Nothing is
forced into cardboard or a generic supported material.

Muse returns structured item proposals constrained to the catalog through the
existing bounded, consented intake call. `uncertain` never selects a category,
alternatives carry look-alikes, and a pile is one proposal without a count.
Proposals and SAM boxes locate and suggest; they are not evidence of
composition, thickness, strength, mass or remaining quantity. A later
suggestion never changes an existing card; it is skipped when it overlaps one.

Measurement follows visible form: planar outlines for thin flat sheets (the
existing estimator), top-face-only outlines for thick sheets, as-laid outlines
for soft sheets, length and width for straight sticks lying flat, no photo size
for tubes, containers, blocks and small parts, and no quantity for rolls,
adhesive containers and loose cord. This change exposes these capabilities as
text; photo measurement still runs only for supported sheet and strip stock.

Recognition accuracy is not evaluated: no labelled real photographs exist in
this checkout. `forma_api.recognition_evaluate` scores recorded proposals
against such a set and refuses a coverage claim until every category and scene
type has real labelled instances.

## D064 — Illustrated material review board (November 4, 2026)

Use the supplied 60 front-facing cutouts as representative art over the shared guided-intake draft. Show at most six cutouts on desktop and three on phones, preserving full editable records below. Recognition does not grant fabrication support. CSS derives crisp offset shadows from image alpha; no runtime image generation or artificial discovery timing. Request state drives loading, and actual returned construction plans enable design navigation. See [handoff](handoffs/material-board.md).

## D063: Check web research against saved materials during intake, November 4, 2026

An opt-in investigation adds cited research to the existing stock-feasible
stand search. FORMA checks the saved materials and requirements first. A scout
finds public references and a separate analyst flags applicable concerns.
A bounded adjudicator can recommend one of the engine's checked candidates
or abstain. The ordinary candidate review and explicit approval still apply.

The builder approves the public brief. Findings stay separate from inventory,
plans and physical evidence. Unsupported essential requirements and hard
blockers stay visible. The feature starts disabled pending the
[provider handoff and acceptance checks](handoffs/issue-9-intake-research.md).

Recommendations identify the cited finding and a directional comparison the
engine confirms for the selected option. The scout runs alone when the engine
has one checked option or no measured difference to compare.

The design comparison shows the cited claim alongside the suggested option.
Optional research leaves current stock choices available if the provider fails.
A stale inventory or unsupported essential requirement clears those choices.
When the engine identifies a missing measurement, the research result opens
the existing measurement form and fetches a decision for the current inventory.
The builder still has to enter and confirm the measured value before saving.

## D065 — Photo recognition deadline and board annotations (November 4, 2026)

Give photo intake one provider attempt with a 120-second total budget and timeout; retain the ordinary gateway defaults for other operations and the longer browser/proxy deadlines. A timeout does not prove provider cancellation or zero usage. Preserve unknown receipts and reconcile them without inventing billing outcomes.

Selected and hovered representative cutouts use a faint alpha-derived white glow. Italic labels and angled leader lines evoke blueprint annotations; selection still opens the existing material correction controls.

## D066 — Retain safe photo-recognition failure diagnostics (November 4, 2026)

A deployed photo request exposed that generic invalid_response errors discarded why the proposal was rejected and any provider usage. Keep the public error family compatible while returning bounded owner-only failure diagnostics from the same request. Show those details in both photo-recognition interfaces without raw provider content or credentials. Failed recognition never becomes a material or physical observation; unknown usage stays unknown.

The diagnostic reproduction exhausted 2,048 output tokens before completing the structured answer. Raise only photo intake to an 8,192 completion-token ceiling, retaining one 120-second attempt without retries. Remove conflicting labels-only prompt wording so the requested catalog item proposals are explicit.

## D067 — Bounded recognition reasoning and required item records (November 4, 2026)

The deployed structured-item request exhausted 8,192 output tokens. Meta documents that hidden reasoning shares this output allowance and unspecified effort is model-determined. Select low reasoning for photo intake only; other proposals retain their existing behavior. Keep one 120-second attempt and the 8,192 ceiling.

A low-effort local call returned correct labels in 10.4 seconds with 665 output tokens, but omitted optional item records. Require the items field in the model-facing photo schema while retaining compatibility for stored/legacy observations. Items are primary output and labels are summaries; an image without visible objects can still return an empty list. These remain reviewable suggestions, never physical evidence.

## D072 — Photo-first illustrated manuals (November 4, 2026)

The user requests a hackathon flow that starts from a photo, proposes visible
materials and approximate dimensions, asks for one editable review, and produces
an illustrated manual without requiring millimeter measurements first. Keep a
detailed-entry mode for measured inputs.

Accepting a photo estimate approves a planning assumption. It does not record a
ruler measurement, establish material strength, confirm a joint test, or complete
physical work. Estimated dimensions and proposed geometry stay visibly approximate.
Use the existing typed construction engine and diagrams for the manual preview;
retain measured fabrication and physical-report checks for actual build records.
## D068 — Saved synthetic pipeline walkthrough (November 4, 2026)

Provide `/walkthrough` as a filled-in recipe-card stand for interaction review, with direct stage links, previous/next navigation, retained model/engine replies, the real generated manual, shared assembly projection and browser-local review notes. The committed bundle contains only labeled synthetic typed results. Its generator runs current deterministic services in an isolated store; hypothetical operation prefixes remain in memory, and the store retains no physical reports or passes. A returned response is not an engine or physical pass.

The companion live run uses separate finite runtime controls, durable reservations before dispatch, actual provider usage and halt-on-unknown handling. Its six calls returned typed intake, design, diagnosis, repair and SAM replies. Both design suggestions were rejected; the model repair was separately simulated against the canonical parameter-driven example. Preserve those results and their distinct provenance. Browsing never dispatches a provider call, activates a revision or submits physical work. Keep active/unready local work outside this release.

## D069: Location-first sourcing with verified Meta-discovered prices, November 4, 2026

The user requests automatic nearby discovery, explicit browser location permission
instead of mandatory city selection, real Meta runtime tests and deployment after
acceptance. Shopping list now resolves a consented rounded device point into city
metadata, suggests an editable currency and keeps manual city entry as fallback.
Only coarse locality and public shop hints reach the separately consented model.

Meta discovers actual product URLs through official search metadata. Its prices
remain proposals; a robots/TLS/refusal-aware reader verifies structured primary
product identity, currency and amount. A portable CA bundle repairs missing trust
roots without disabling TLS. Main-product microdata can use matching single-item
GA4 JSON currency evidence, never unrelated analytics or executed JavaScript.

Nearby mapped shops and online prices are distinct; neither establishes local stock
or changes physical engine state. Refusals persist across requests and deployment
for their finite retention. The initial real output-limit response retained its
actual usage and was reconciled before further bounded calls. No coding-worker
STOP, provider payment setting or historical unknown receipt was changed.

The local complete flow returned ten real mapped San Francisco shops and a verified
USD 21.99 online catalogue observation without a pasted URL. Browser GPS is simulated
software input, not physical evidence. Exact-head checks, independent review and
the existing deployment workflow gate release; see handoffs/local-sourcing.md.

## D070: Release the saved workshop home, November 4, 2026

The user expected the previously implemented workshop to appear after sign-in.
Its local Home, My Projects, My Materials, Shopping List and Explore presentation
had remained uncommitted while supplier sourcing was released separately. Bring
that presentation onto current main, preserving guided photo intake, shopping,
manual and request-recovery behavior. Existing project URLs still open their
project; a normal sign-in opens the workshop. Navigation retains a draft and
pending requests and confirms before discarding unsaved work.

Project cards read saved owner-scoped engine geometry through revision-guarded
GET routes, or use a frozen saved manual for an explicitly unsupported design.
Unknown/pending construction receipts never fall back to an older proposal.
Thumbnails are planned geometry, not evidence of physical construction. Opening
Home or Shopping List makes no model request or purchase. Favorites remain in
session memory; credentials are never stored in browser storage.


## D073 — Retain construction previews and separate planned step illustrations (November 4, 2026)

The user requests reproducible repairs to missing generated diagrams and stepwise
3D output. Keep geometrically valid model proposals visible when fabrication
measurements or reviewed joint evidence are missing. A known unusable correction
must not erase an earlier checked proposal; genuine transport uncertainty retains
the original request identity and blocks redispatch. Safe receipt metadata and an
owner-scoped read-only inspection route support diagnosis without settling an
unknown provider outcome.

Integrate the existing photo-first illustrated preview with the workshop home.
An active build retains its saved manual and diagnosis. Highlight the actual
pieces referenced by each generated step, and derive preparation outlines and
proposed dimensions from the returned geometry rather than a preset design.

The compiled-plan viewer adds a distinct planned-operation illustration derived
from immutable plan effects. It is a target-position reference, not an observed
intermediate pose or a stability result. Physical geometry and evidence checks
remain separate, and report overlays cannot be applied to planned illustrations.
No navigation, preview or regression test records work in a user's project.

## D071 — Live intake repairs: structured answers, recoverable localization, reconciled stock (November 4, 2026)

Live MetaMuse runs on synthetic images (head 7dc1744) returned useful text labels with no items for cardboard and a notched sheet, an incomplete bottle answer at the 2048-token cap, and zero SAM boxes for the notched sheet. The connected intake prompt also told the model to list "labels and questions only", which contradicted the item request.

- Fresh intake answers use a separate provider schema (`intake-items-v2`, `IntakeProposal`) whose `recognition`, `items` and `questions` are all required. `recognition` is `items`, `partial` or `no_objects`; `no_objects` exactly when no item is listed; an unidentifiable object is an `uncertain` item. A label-only or inconsistent answer is refused as `invalid_response`; labels in the API observation are derived from items. The API `IntakeObservation` keeps its earlier shape, with `recognition` left out when absent, so an older label-only response still parses and is shown as "no item cards", never as catalog intake.
- This is one implementation with D066 and D067: their 8,192 completion ceiling, low reasoning effort for photo intake only, one 120-second attempt without retries, and the `invalid_response` public code with an allowlisted `reason` and validation issues. It adds the provider finish reason and reported reasoning tokens to those diagnostics; a truncated answer has reason `incomplete_output`. The answer is bounded (12 items, 80-character evidence, three short questions) so even its largest valid form fits the old 2,048-token cap. The D067 photo schema that required `items` is replaced by `IntakeProposal`, which also requires `recognition`, and labels are no longer requested from the model.
- When SAM returns no usable region (none, only the whole photo, only the marked reference, or none where Muse placed the item), the card says so, keeps the photo, reference and material, and offers a drawn box or a local, deterministic outline suggestion for sheets and strips. The suggestion excludes the reference and regions cut off at the photo edge, is kept only if the outline search confirms it, and is labelled as a suggestion. The estimator now refuses any outline lying mostly on the reference.
- A saved item whose identity contradicts its linked material withdraws the inventory's confirmation (recorded as a hold) until the user removes the material, retypes it to fit, or changes the item back. Design readiness and generation, construction, synthesis and plan compilation require confirmation; plan activation now does too. Confirmation is restored automatically only when a hold placed for that reason is resolved. A new contradiction is refused while a build is active; contradictions saved earlier are held at startup, active builds included. Confirmation alone does not gate an active build's repair and fabrication actions, so those check the holds directly: repair search, Muse repair advice, repair simulation and approval, fabrication assessment and saved-preview scheduling are refused (`blocked`) while a material is held, and the active fabrication report stays readable but carries a `needs_confirmation` blocker naming the held material, so it offers no order. The fabrication rules are unchanged; the hold enters through their existing context-blocker input. Events, evidence, plan versions and saved previews are never rewritten, an exact replay of an earlier recorded outcome is still returned, and a saved preview can be scheduled and approved again once the hold is released.

Synthetic results do not establish real-photo accuracy or 48-category recognition coverage.

The D073 construction preview remains available as hypothetical geometry when material confirmation is missing. A held material cannot gain fabrication approval from that preview; active-build action gates and physical evidence requirements remain in force.

## D074 - Gate construction generation on server receipts (November 4, 2026)

Read the authenticated, owner-scoped construction receipt list before enabling
new generation, including in a fresh browser without a local pending request.
Pending or unknown server receipts block dispatch and show only the safe stored
cause and original request digest. Failed, malformed or unavailable status reads
keep generation blocked; stale reads are discarded when authorization or project
changes. Preserve any browser-local original request payload and identity.

The explicit Check request status action performs a read-only GET without provider
consent, a new request key or a proposal POST. It does not resume provider work,
recover a missing result or reconcile an unknown outcome by itself. Existing
successful proposal diagrams remain reviewable, and a confirmed completed receipt
can permit a separately consented action. Offline intercepted browser regressions
are software checks, not live provider recovery or physical build evidence.

## D075 - Prefill empty material sizes from reference-based photo estimates (November 4, 2026)

Photo first exposes the existing material and reference controls through Estimate
material sizes. A current, matching reference-based estimate fills only untouched
empty width and height drafts, with photo_estimate provenance and no measurement
confirmation. Existing values, partial manual measurements, thickness and mass
remain unchanged. Stale, foreign and enclosing-only estimates cannot fill sizes.
The existing explicit Save materials action persists the draft; opening the
controls or receiving an estimate does not save inventory or invoke a provider.

Known scale and the existing flat, same-plane and visibility requirements remain
necessary. A visible ruler without established markings is not a calibrated
reference, and a partly hidden sheet does not establish its full dimensions.
These prefills do not grant fabrication approval or reconcile an unknown request.
Intercepted browser checks exercise the connected draft and save flow with
synthetic responses; they do not establish accuracy on the user's actual photo.
