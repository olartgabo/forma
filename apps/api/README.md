# API and orchestration

Product/persistence owner: @olartgabo. Gateway/orchestrator owner: @ResniDev.
Each reviews the other's API contract changes. Status: health plus local private
project/inventory persistence; provider services are available offline.
Issues: #1, #4, #6, #9 and #12.

Implement FastAPI with project-scoped routes and Pydantic validation. Reserve
`src/forma_api/routes`, `services`, `models`, `providers` and `tests` as code
lands. Keep shared domain entities in [packages/domain](../../packages/domain/README.md).

| Boundary                                                           | Owner                     | Deliverable                                                               |
| ------------------------------------------------------------------ | ------------------------- | ------------------------------------------------------------------------- |
| Routes, sessions, project service, private uploads and persistence | @olartgabo                | Authenticated/idempotent API and durable plan/event/evidence records      |
| Providers/model_gateway and bounded orchestration                  | @ResniDev                 | Validated proposals and safe traces; no autonomous physical state commits |
| Revision transaction                                               | @olartgabo with @ResniDev | Atomic user approval against validated expected-version proposal          |

Provider tasks cannot rewrite completed events or record test passes. Apply
project auth before data access, validate uploads, keep secrets private and
bound external calls. Use storage adapters; offline compiler modules never
import API services. Coordinate changes to shared routes/models in a handoff.

## Run and check

From the root, `uv sync --locked` installs the editable `forma_api` package from
`apps/api/src/forma_api` using the root `pyproject.toml`. `npm run dev:api` starts Uvicorn
at `127.0.0.1:8000`; `GET /api/health` reports process liveness and `/docs`
exposes FastAPI's OpenAPI UI. No database or provider readiness is implied.

`npm test` runs the offline pytest suite. `npm run lint` and
`uv run --locked ruff format --check .` check Python source. No model key is
needed. See the [root README](../../README.md) for pinned tools and setup.

Project/inventory routes and local development authentication are implemented.
Initial plan/manual and user-reported event/evidence/material persistence are
implemented; hosted authentication remains #6 work. The
[#1 handoff](../../docs/handoffs/issue-1-workspace.md) reserves the service/domain
boundary for review before those changes.

## Local private projects (#6, first slice)

`create_app()` now exposes project creation/read/deletion and pre-plan inventory
confirmation. Configure `FORMA_API_TOKENS` as a JSON object mapping owner IDs to
distinct secret tokens of at least 32 characters. Send a configured token in
`Authorization: Bearer <token>`. With no credentials configured, project routes
return 401; health stays public. This is development auth; hosted sign-in remains
pending. Keep tokens server-side and out of source control and public logs.

`FORMA_DATA_DIR` defaults to `.local/forma`; SQLite stores private project and
inventory records there. POST `/api/projects` accepts `goal` and
`idempotency_key`. GET `/api/projects/{id}` restores the project. PUT
`/api/projects/{id}/inventory` accepts domain `stocks`, `user_confirmed: true`,
`expected_revision_id` and `idempotency_key`. Every accepted edit advances the
inventory revision. Stale edits and changed-payload key reuse return 409; exact
retries return the original outcome with `replayed: true`. An inventory revision
is separate from `active_version_id`, which stays null until explicit initial plan approval.
Unknown measurements remain unknown. Photo IDs must resolve to private media in
the same project; evidence IDs remain rejected until evidence storage exists.
OpenAPI documents the actual envelopes.

Inventory confirmation can include `requirements` with available `tools`, nullable
`device_description` and the domain `Constraints` record. Requirements and stock
advance the same revision atomically. Omitting requirements preserves them;
explicit null clears them. Known mass/footprint measurements must be positive and
confirmed; a known angle must be greater than 0 and less than 90 degrees. Evidence
references and profile selection remain unavailable until trusted evidence/catalogue
integration. Tool names record reported availability and grant no execution permission.
See the [requirements handoff](../../docs/handoffs/issue-7-requirements.md).

DELETE `/api/projects/{id}` takes `Idempotency-Key` in a header, removes the
inventory and stored replay snapshots, and retains only a scoped deletion receipt.
This is logical deletion; SQLite free pages and local backup copies are outside
this deletion mechanism. These routes do not send
data to providers. Consent/transfer, actual remaining-stock reconciliation
and repair revision activation remain open in #6/#12. See the
[contract handoff](../../docs/handoffs/issue-6-persistence.md).

## Private photos (#6)

POST `/api/projects/{id}/media` accepts a raw JPEG, PNG or WebP body with
`Content-Type` and `Idempotency-Key` headers and the same bearer authentication.
The API checks the byte count, decoded format, pixel count and complete image
before storing a normalized image without embedded metadata. Animated images
are rejected. Limits are 8 MiB for input and normalized output and 20 million
decoded pixels. The response contains an opaque media ID and image metadata;
it does not establish dimensions in millimeters or physical success.

GET `/api/projects/{id}/media/{media_id}` returns private image bytes only to the
project owner, with cache prevention and download headers. DELETE at the same
path requires `Idempotency-Key`; first remove any current inventory references.
Project deletion removes all photo rows and their upload receipts in the same
transaction. Images remain in the local SQLite database until deleted. Logical
deletion does not erase SQLite free pages or backups. No route sends images to
a model or shares them publicly; those capabilities require a future consent
flow. See the [media handoff](../../docs/handoffs/issue-6-private-media.md).

GET `/api/projects/{id}/media` lists private image metadata for that project,
including uploads not yet linked to stock. It returns `{media: [...]}` with
cache prevention, and checks project ownership before reading rows. Image bytes
still require the authenticated individual media endpoint.

## Initial plan previews and approval (#6/#11)

`PlanService.compile_preview` is an internal producer boundary. A trusted runtime
supplies a candidate, selected kerf/margin, measured process, stand parameters and
reviewed profiles. The service loads scoped saved stock/requirements, generates
version/time IDs, compiles and renders, then stores accepted immutable outputs
against the exact inventory revision. It stores the process/stand context and
binds the complete invocation to its retry key. At most two previews can be saved
per revision. Production calls reject synthetic evidence by default. This is not
an HTTP model-generation or arbitrary-plan upload endpoint.

Authenticated routes:

- GET `/api/projects/{id}/plans` lists saved version summaries.
- GET `/api/projects/{id}/versions/{version}` reads the immutable plan/manual.
- GET `/api/projects/{id}/manual/{version}` reads the immutable manual alone.
- POST `/api/projects/{id}/plans/{version}/activate` requires
  `expected_revision_id`, `idempotency_key` and `user_approved: true`.

Approval atomically checks the saved preview, current revision and absence of an
active plan before setting the active pointer. It never accepts plan JSON. Exact
retries replay; changed keys/payloads or stale activation conflict. Read/approval
responses prevent caching. Project deletion cascades plan/manual rows and purges
their receipts. Approval creates no events, material consumption or test results.

Provider-driven preview production, measured process/profile intake and repair
activation remain pending. The browser can inspect and approve
existing previews, navigate instructions and enlarge dimensions. See the
[contract and evidence handoff](../../docs/handoffs/issue-6-plan-activation.md).

## Physical progress (#6/#11)

GET `/api/projects/{id}/versions/{version}/progress` returns chronological domain
events, user evidence, material receipts, completed/failed IDs, an expected-stock
projection and the last event cursor. POST `/api/projects/{id}/events` accepts an
operation reference, expected active version/last event, retry key, result, notes,
explicit confirmations and up to eight existing project photo IDs. It accepts no
caller-authored events, ledger quantities or physical-test authority fields.

Reports are appended atomically after scope, active version, cursor, prerequisites
and duplicate checks. Exact retries return their original receipt; consumers must
reload current history after replay because other reports may now exist. Checks
use explicit pass/fail; failed checks stop further confirmation until diagnosis
or a revision resolves them. Functional-test outcomes retain the stored named
device/procedure/conditions and user provenance. Nothing infers physical function.

Confirmed cuts consume the entire parent region and preserve declared offcuts;
joins spend exact planned connector length once. Expected connector balances use
decimal accounting and remain calculated/unconfirmed. They need actual material
reconciliation before a repair. Original plan stock stays immutable. Photo evidence
prevents individual asset deletion; deleting the whole project purges history and
its retry snapshots. This slice exposes no event-writing model tool.
See the [contract and validation](../../docs/handoffs/issue-11-physical-progress.md).
