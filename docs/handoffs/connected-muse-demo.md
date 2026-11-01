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
