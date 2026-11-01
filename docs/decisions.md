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

| ID   | Question and required evidence                                                                   | Owner                                  | Resolve before                   |
| ---- | ------------------------------------------------------------------------------------------------ | -------------------------------------- | -------------------------------- |
| P001 | Resolved for workspace scaffold; schema integration review remains pending (D008 below)         | @olartgabo with @ResniDev              | #1 review                         |
| P002 | Resolved by D009: domain layout, generated schemas and error taxonomy                    | @ResniDev with @olartgabo              | #3 consumers                     |
| P003 | Session/auth mechanism and authenticated project/media access                                    | @olartgabo                             | #6 persistence routes            |
| P004 | Hosting region, DB/object-storage providers, migrations, backup and deletion approach            | @olartgabo                             | #6/#16 deployment                |
| P005 | Actual inventories A/B, stand dimensions, material thickness and tools in hand                   | @olartgabo                             | #2/#5 geometry                   |
| P006 | Three tested joint/repair strategies, measured tolerances and supported limits                   | @olartgabo; @ResniDev encodes profiles | #2/#5 profile promotion          |
| P007 | Named device/mass, angle, surface, duration and repeated-use functional test                     | @olartgabo                             | First physical build             |
| P008 | Live Meta access, actual endpoints/model IDs, SDK, region, quota, privacy mode and budget        | @ResniDev                              | #4 live smoke gate               |
| P009 | SAM practical value versus manual box/label fallback                                             | @ResniDev with @olartgabo              | #4/#7 intake                     |
| P010 | Portal team eligibility, terms/media consent, deliverables and exact deadline/timezone           | @olartgabo                             | Day 0; recheck before submission |
| P011 | Independent builder availability and consented study scope                                       | @olartgabo                             | #15 evaluation                   |
| P012 | Narrowing to tested templates/fewer operations if G2/G3 miss October 31                          | Both                                   | October 31 gate                  |

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
