# Connected Muse demo: priority and route contract

The user paused standalone offline-engine work. This branch extends the existing
intake UI from PR #42 without changing that PR's branch. The next deliverable is
a real browser-to-Muse request, followed by design/manual/diagnosis integration.
Existing deterministic validators remain behind the live flow; no new recovery
algorithms or offline-only PRs are planned.

## First runtime contract

`POST /api/projects/{project_id}/intake` uses existing bearer/project ownership.
The body supplies `media_id`, `expected_revision_id` and explicit
`provider_transfer_consented: true`. The server loads the private photo itself;
the browser cannot submit a trusted snapshot, remote image URL or provider key.
No provider call occurs for missing consent, stale revision, wrong ownership,
missing media, unsupported image or missing credentials. JPEG/PNG up to the
gateway's 5,000,000-byte limit are supported initially; other stored uploads
produce a useful error before transfer.

The response identifies the project, inventory revision and media, and contains
the existing typed `IntakeObservation`: candidate labels, questions and
`measurement_source="unknown"`. It may include bounded safe diagnostics such as
model/status/duration; never keys, raw provider bodies or private prompt traces.
This does not mutate inventory or activate a plan. Reload/check revision around
the external request; never keep the database transaction open over network I/O.
Provider errors have stable actionable codes and no automatic paid retry.

## Shared integration boundary

The user explicitly prioritizes this connected demo. API authentication/router
composition and browser intake belong to Gabo's lane; this handoff records the
contract before implementation. Reuse PR #42's intake/upload/session controls and
generated API contracts instead of duplicating them. Keep model keys server-only.
No teammate messages, merges or changes to Gabo's remote branch are authorized.

Automated fake-transport checks verify request boundaries. Acceptance additionally
requires an actual consented photo and a real Muse response shown in the browser;
until then the live path is unverified. Generated labels never become confirmed
measurements, available stock or physical results automatically.

## Implemented API boundary

The route is wired through the existing project router and authentication. It
uses the real `MetaGateway.from_env()` at request time, keeping `MODEL_API_KEY`
server-only. `META_SPARK_MODEL` selects the configured Muse text/vision model;
the existing default is Muse Spark. Missing configuration returns a safe 503.
No model call happens at application import or for denied requests.

Consent accepts literal booleans only. Intake-specific validation errors omit
rejected values, and typed API-local errors cover provider access, rate limits,
timeouts and unusable output without widening the domain error schema. Project
ownership errors retain the existing handler. Transactions close before the
provider request; project revision and media existence are checked again after it.

Independent API and UI reviews approved the completed intake boundary. Full
`npm run check` passed 297 Python tests, 13 browser-client tests, formatting,
lint, generated contracts, TypeScript and the production build.

A real Muse Spark 1.3 call with the labelled OpenAI-generated material photo
returned five candidate labels and four questions in 7,797 ms. A separate actual
browser request through the web proxy displayed five labels, four questions,
`measurement_source="unknown"` and real model/status/duration diagnostics
(8,453 ms). These are two software observations, not a latency benchmark or
physical inventory evidence. The isolated browser reused saved project/photo
state, explicit consent and the existing owner session. No provider credential,
runtime database, generated image or unredacted private artifact is committed.

## Composition with saved requirements and manuals

The owned integration branch combines PR #70 with PRs #68ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“69. Both authenticated
routers and both workbench panels are retained: Muse photo observations alongside
saved requirements, immutable previews/manuals and explicit initial approval.
Muse resolved the two source conflicts; independent integration review approved.
The combined full project check passed 344 Python tests, browser-client tests,
formatting, lint, contracts, TypeScript and production build. Existing real intake
and plan suites exercise the shared app, so no duplicate route-list test was added.
Private historical `.devloop` state is excluded from formatting.

## Next connected producer contract

Connect `MetaGateway.propose(DesignProposals)` and its scoped read-only
`get_project_snapshot` tool to the existing `PlanService.compile_preview`.
The request contains expected inventory revision, bounded notes, explicit context
transfer consent and request identity. Inventory revision is never a plan version;
the plan service creates real version IDs and timestamps after successful checks.

Resolve process, stand parameters, catalogue and selected kerf/margin from an
explicit server-owned manifest or injected resolver, scoped to the exact project
and inventory revision. HTTP cannot submit those trusted objects, file paths,
synthetic opt-ins or a BuildPlan. Missing inputs remain missing: Muse may return
questions and no candidates, with precise blockers explaining why no manual exists.

Each candidate must reference the saved stock and available profile IDs, then pass
the existing compiler/renderer producer before becoming a saved preview. Request
identity must prevent blind repeated generation and bind the resolved context.
Generation never activates a plan. Existing manual review and explicit approval
remain authoritative. Production synthetic acceptance stays disabled; isolated
test injection must be visibly labelled. No new offline recovery algorithms or
parallel concept store are part of this work.

## Connected generation implemented and checked

`POST /api/projects/{id}/designs/generate` now implements the producer contract
above. The existing plan service compiles and saves accepted previews, preserving
its two-preview capacity and separate approval path. Missing measurements are
kind-specific: tape/cord need width and remaining length, while sheet/strip need
width, height and thickness. Uncertain provider outcomes retain request identity;
capacity exhaustion preserves any preview already saved in the same request.

The first real browser generation exposed a pre-existing gateway incompatibility:
named `tool_choice` is rejected by Meta Chat Completions. The gateway now uses
supported `auto`, instructs the named read-only tool, and enforces exactly one
valid tool call locally before accepting typed output. Direct answers and invalid
or multiple calls cannot bypass the snapshot. See Meta's current
[tool calling documentation](https://dev.meta.ai/docs/cookbook/tool-function-calling).

After the fix, a real browser -> same-origin proxy -> authenticated API -> Muse
Spark 1.3 request completed two model rounds and one validated snapshot-tool call
in 6,406 ms. It returned eight questions and the missing server-context blocker;
zero previews were saved and no plan was activated. This intentionally unknown
synthetic test project is not evidence of a physical build or a model-produced
accepted manual. Safe server instrumentation recorded model-reported token counts
without provider bodies; local reservation estimates are not billing.

A second real request verified cancellation: ordinary Generate stayed disabled,
checking saved previews retained the unknown-outcome notice, and explicit fresh
start reset consent. The server completed its original receipt. Replaying that
exact request returned the same result with `replayed=true` and zero additional
audited provider runs. The UI did not start a fresh provider request for those
checks. Private DOM/evidence files and runtime state remain outside Git.

The green generation feature passed 371 Python tests, including actual compiler/
renderer integration with explicitly synthetic test inputs; 20 client tests;
contracts, TypeScript, lint, formatting and production build checks. Independent
reviews approved backend outcome handling, stock requirements, UI retry controls
and the supported Meta protocol. These are software checks; measured inventory,
reviewed physical profiles, real history and a physical attempt remain required.

## Next connected diagnosis boundary (issue #9)

Add a read-only saved-photo diagnosis route and browser panel using canonical
`DiagnosisProposal`, explicit transfer consent, actual Muse diagnostics and scoped
saved context. Photo-only diagnosis may ask questions before any active manual;
its affected IDs must be empty and progress remains unknown. When an active plan
and operation are supplied, resolve both from server-owned state and validate all
references. No inventory, completion history, damage fact, repair patch or plan
activation is created by diagnosis. Existing plan-required repair service guards
remain unchanged. Record the exact shared contract here before implementation.

## Connected diagnosis implemented and checked

`POST /api/projects/{id}/diagnose` now loads an authorized private saved photo
and bounded reported problem after literal transfer consent, image eligibility
and revision gates. Photo-only diagnosis uses no plan IDs or assumed completion
history. Optional active-plan/operation context resolves server-owned state;
selected operation arguments, preconditions, effects and referenced geometry
are intended plan facts, never completion evidence. Affected IDs are validated.
Project revision, photo existence and active context are rechecked after Muse.
The route writes no inventory, plans, physical events or repair patches.

The browser's Something went wrong panel separates visible observations,
hypotheses and measurement questions. Dispatch consumes consent; a subsequent
success, failure or cancellation requires fresh consent for another transfer.
Repair execution remains unavailable pending authenticated physical history and
existing deterministic repair validation. Independent final review approved both
context completeness and per-request consent repairs.

A real browser -> proxy -> authenticated API -> Muse Spark1.3 request with the
labelled synthetic materials photo completed in 9,750ms. It returned six visible
observations, three hypotheses and four questions, failure_type=unknown and zero
affected IDs. The response correctly noted that no assembled stand was visible.
The checkbox cleared and the repeat-request button remained disabled. Safe local
instrumentation captured model-reported usage without raw provider responses.
No physical failure, completed operation, successful build or repair was claimed.

Validation passed 395 Python tests, 24 client tests, generated contracts,
TypeScript, Ruff, formatting and production build checks. A typed Fold regression
checks expected operation arguments and actual geometry in diagnosis context;
route tests cover scope, consent, image gates, stale state and immutable data.
Private evidence, owner credentials, generated images and runtime DB stay out of Git.

## Planned request-local usage diagnostics contract

The user requests visible evidence of actual Muse usage. Add optional `usage`
to the existing intake, design and diagnosis diagnostic records, using one
canonical API-owned ProviderUsage record. Its input_tokens/output_tokens are
provider-reported nonnegative integers or null when unavailable; model_calls
counts only this request's trace entries. Missing usage stays unknown, including
an aggregate with missing counts. Reused gateway history must not be included.
No prices, billed-cost claims, prompt bodies, keys or extra model requests are
part of the response. Generate nested API TypeScript from Pydantic and preserve
existing client compatibility. This lane owns API/runtime/contract tests; the
parallel UI lane owns intake/design per-request consent only, with no API edits.

### Usage diagnostics implemented and verified

Optional diagnostics.usage now uses the canonical ProviderUsage record in all
three connected runtimes. A request-local ProposalBudget trace sink excludes
old gateway history. Reported input/output counts aggregate only when every
participating count is valid; missing/malformed values remain null, never a
partial total or invented zero. Model-call counts reflect that request's traces.
There are no currency, billed-cost, prompt or credential fields.

The parallel Muse lane passed 414 Python tests and 24 client tests, generated
contracts, lint and formatting. Independent review approved the nine-file feature.
The combined usage/consent tree also passed the full project check including
TypeScript and production build. A real authenticated diagnosis request returned
usage={model_calls:1,input_tokens:2904,output_tokens:1969}, exactly matching the
safe trace from the actual Muse Spark1.3 response (11,859ms). Failure remained
unknown with no affected IDs. These counts are provider-reported tokens, not a
bill, estimated spending, physical evidence or additional inferred inventory.
