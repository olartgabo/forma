# Connected demo runbook

How to run the internet-connected Muse demo end to end. Everything here was
checked against the code (`apps/api`, `apps/web`); button and field text is
quoted from the web components. Live Muse steps spend provider credits. A
passing live step, or a passing smoke run, is **not** physical proof: only a
build you did and a check you observed count.

## 1. Prerequisites

- Node 22.21.0, npm 11.16.0, uv 0.11.16 (Python 3.12.6 via `uv python install`).
- `npm ci` and `uv sync --locked` already run at the repository root.
- A Meta model API key and an owner token you generate yourself.
- Photos to upload: Muse reads only JPEG or PNG photos of at most 5,000,000 bytes.

Environment variables (names only). Export them in the shell that starts the
process. `.env.example` lists some of them and is not loaded automatically.

| Name                        | Read by    | Purpose                                                                                                                          |
| --------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `MODEL_API_KEY`             | API        | Provider credential. Server-only; never use a `NEXT_PUBLIC_` prefix.                                                             |
| `META_SPARK_MODEL`          | API        | Optional model id override (default `muse-spark-1.3`).                                                                           |
| `META_SAM_MODEL`            | API        | Optional model id override (default `sam-3.1`).                                                                                  |
| `FORMA_API_TOKENS`          | API        | JSON object of owner id to secret token (32+ characters). Without it project routes return 401.                                  |
| `FORMA_DATA_DIR`            | API        | Optional location for SQLite and private media (default `.local/forma`).                                                         |
| `FORMA_DESIGN_CONTEXT_PATH` | API        | Server-owned manifest (cutting process, stand parameters, joint profiles, kerf, edge margin) per project and inventory revision. |
| `FORMA_API_ORIGIN`          | Web server | Optional API origin for the web proxy (default `http://127.0.0.1:8000`).                                                         |
| `FORMA_SMOKE_OWNER_TOKEN`   | Smoke CLI  | Owner token for `demo_smoke` whenever `--project-id` is used (or pass `--credential-file`).                                      |

> **Warning: design generation needs a design context.** Muse design generation
> is blocked unless `FORMA_DESIGN_CONTEXT_PATH` points to a readable JSON
> manifest (at most 262,144 bytes) with exactly one entry matching the
> project's `project_id` and current inventory `inventory_revision_id`. The
> API returns blockers ("No server-configured design context for this project
> and inventory revision." or "Configured design context is invalid.") and
> nothing is invented. An entry holds `project_id`, `inventory_revision_id`,
> `process` (measured cutting process), `parameters` (stand parameters),
> `joint_profiles`, `kerf_mm` and `edge_margin_mm`; the schema is
> `DesignContext` in `apps/api/src/forma_api/design_context.py`, and the
> manifest is `{"contexts": [...]}` (a bare list or single entry also loads).
> Use measured values only (see docs/decisions.md, D015). The manifest is
> scoped to one inventory revision, so any inventory save needs a new entry.
> Export the variable and restart the API. Use the "Saved input checklist" to
> see what is still missing.

Never commit or paste values for any of these variables.

## 2. Start the apps

Two terminals, both at the repository root:

```sh
npm run dev:api
npm run dev:web
```

- API: <http://127.0.0.1:8000> (OpenAPI at `/docs`).
- Web: <http://127.0.0.1:3000>.
- Stop each with Ctrl+C. Restart the API after changing any variable.

## 3. Preflight

```sh
curl http://127.0.0.1:8000/api/provider/status
```

Returns `{"configured": true|false, "model": "<spark model id>"}`. It inspects
local configuration only: no provider call, no cost. `/api/health` reports
process liveness only.

`configured: false` means `MODEL_API_KEY` is empty or blank, or
`META_SPARK_MODEL` / `META_SAM_MODEL` is not a valid model id. Fix the
environment and restart the API; otherwise every Muse action fails with
`provider_not_configured`. `configured: true` does not prove the key is accepted
or the model reachable.

## 4. Demo path in the web UI

Open <http://127.0.0.1:3000>. Muse panels stay unavailable while the inventory
is unsaved or stale ("Save or reload the inventory first").

1. **Sign in.** Under "Open your workbench", enter a `FORMA_API_TOKENS` token in
   "Owner credential" and connect.
2. **Create or open a project.** Describe the goal under "What would make your
   desk work better?" and press **Create project**. To resume, use "Continue a
   project": enter the "Project ID" and press **Open project**.
3. **Goal photo and inventory.** Under "Photograph your materials" press
   **Upload photo**. Under "Record what you have", add one record per physical
   item (millimeters), link matching photos and save. Unknown measurements stay
   unknown.
4. **Muse intake (consent).** In "Ask Muse about this photo", pick a photo, tick
   "Send the selected photo and this project's saved goal to Meta's Muse
   service for this one request...", press **Ask Muse about this photo**.
   Results ("Candidate labels", "Questions to check") are read-only and do not
   change saved materials; correct the inventory yourself.
5. **Check inputs.** "Saved input checklist" lists "Missing inputs" and
   "Blockers". Resolve them before generating.
6. **Design generation (consent).** Under "Review your plan and manual" >
   "Generate with Muse", optionally fill "Notes for Muse (optional)", tick
   "Share this project's saved goal, materials, requirements and my notes
   above...", press **Generate with Muse**. No photo is sent. Muse proposes up
   to two designs and FORMA compiles them ("Muse design result", "Questions to
   answer", "Blockers"). Unavailable once a plan is active.
7. **Compiled manual.** Step through the manual, tick "I reviewed this plan and
   its required physical checks." and press **Approve this plan**. Approval
   does not mark any work done.
8. **Physical progress and a failed check.** Under "Record what actually
   happened", for each operation tick the checks you performed, fill "What did
   you do or observe?", tick "I performed this operation or check and am
   reporting its actual result." and press **Save physical report**. On a check
   operation choose "Failed a displayed check" under "What was the result?" and
   attach the failure photo ("Photo N", up to eight). Status becomes needs
   review and further confirmations pause until an approved revision.
9. **Failure-photo diagnosis (Muse, consent).** In "Something went wrong", pick
   the "Saved failure photo", fill "What went wrong?" and "Current step", tick
   "Send the selected photo, my reported problem and this project's saved
   materials...", press **Ask Muse what went wrong**. Output: "Visible
   observations", "Possible causes (hypotheses)", "Questions or measurements to
   check". It is unverified.
10. **Repair handoff.** In the diagnosis result press **Review a repair for
    <part id>**. This sends nothing; it opens a draft under "Adapt the plan".
    The plain **Review a repair** button there opens the same panel.
11. **Muse repair options (consent).** In "Ask Muse for repair options", fill
    "Reported problem", tick "Send my reported problem, the Muse diagnosis if
    present and the active plan context...", press **Ask Muse for repair
    options**. Proposals join the candidate list as unverified. A Muse
    diagnosis from the handoff is required first.
12. **Simulate.** Measure remaining stock, tick "I checked the remaining
    materials and measured the connectors above." and press **Simulate
    repairs**. Review "Repair options" (up to three candidates). If none
    passes, nothing can be approved.
13. **Approve and activate.** Select a preview, tick "I approve this revision.
    Recorded work stays in history; the listed checks must be repeated." and
    press **Activate revision**. Repeat the listed checks physically.
14. **Proof export.** Open "Proof — saved plans, reports and evidence", press
    **Refresh proof snapshot**, then **Download text summary** or **Download
    JSON report**. The file includes goal and notes; private photos are
    excluded ("N private photos excluded").

## 5. Smoke CLI

Run from the repository root with the API running. Output is one JSON report;
exit code 0 means ok. Owner credential comes from `FORMA_SMOKE_OWNER_TOKEN` or
`--credential-file PATH`, never from a flag value.

```sh
uv run --locked python -m forma_api.demo_smoke --help
```

Read-only (no provider cost): with no flags it checks health and local provider
configuration. After health succeeds it requests `/api/provider/status` once;
`report.provider` records that endpoint result, configuration and model, not
actual Meta reachability. An unavailable endpoint or unconfigured provider is
informational in read-only mode; live mode stops before project reads or POSTs
if the endpoint fails or configuration is missing. `--project-id ID` adds the
saved project and design readiness, plus one build-progress snapshot when a
version is active. `report.progress` contains counts, status and a last-event
presence flag, without observation text. `--media-id ID` (needs `--project-id`)
adds photo eligibility. Common options: `--api-origin` (default
`http://127.0.0.1:8000`) and `--timeout` seconds (0.1 to 30, default 10).

Live steps. At most one live flag per run. Each makes real provider calls,
**costs credits**, and refuses to run without `--transfer-consent` (alias
`--provider-transfer-consent`). Consent alone never triggers a call.

| Flag               | Required with it                                                | Optional         | Proves only                                                                                 |
| ------------------ | --------------------------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------------- |
| `--live-intake`    | `--project-id`, `--media-id`, `--transfer-consent`              |                  | One validated provider response for that photo.                                             |
| `--live-design`    | `--project-id`, `--transfer-consent`                            | `--design-notes` | One provider response plus deterministic compile results.                                   |
| `--live-diagnosis` | `--project-id`, `--media-id`, `--transfer-consent`, `--problem` | `--operation-id` | One provider response for that photo.                                                       |
| `--live-repair`    | `--project-id`, `--media-id`, `--transfer-consent`, `--problem` | `--operation-id` | One diagnosis, one repair proposal and one read-only simulate. Never approves or activates. |

Example (live design):

```sh
uv run --locked python -m forma_api.demo_smoke --project-id project-abc --live-design --transfer-consent
```

`report.usage_total` sums model calls, input/output tokens and elapsed milliseconds
from all live steps, including diagnosis and repair in a live repair run. Any
unknown contributing value makes that total null; the whole field is null when
no live step ran. These are reported usage values, not a billing estimate.

A read-only pass checks saved state and local configuration; it does not show
that Muse answered. A live pass shows the requested provider flow and its
deterministic checks completed. Neither is **physical proof**. Do not present
smoke output as a built or tested part.

## 6. Failure modes

Codes come from `PROVIDER_ERROR_CODES` and the gateway mapping. Within one
request, FORMA may retry a rate-limit or temporary server response (HTTP 429,
500, 502, 503 or 504) once by default, only inside the same request deadline.
Timeouts, network errors and outcomes that are unknown are not automatically
retried. Cancel only stops FORMA waiting, and Muse may still process the
request. Explicitly sending a new request yourself is separate from this
internal retry and needs fresh consent.

| Code                      | HTTP | What you see                                                       | What to do                                                                                                            |
| ------------------------- | ---- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `provider_not_configured` | 503  | "Model provider is not configured on the server"                   | Set `MODEL_API_KEY`, confirm `/api/provider/status`, restart the API.                                                 |
| `timeout`                 | 504  | "Model provider request timed out; retry later"                    | Check saved previews first for generation: its outcome may be unknown. A new provider request requires fresh consent. |
| `rate_limit`              | 429  | "Model provider rate limit reached; retry later"                   | Wait, then retry.                                                                                                     |
| `invalid_response`        | 502  | "Model provider returned an unusable response; retry"              | Retry; if it repeats, simplify notes or use a clearer photo; switch to the recorded backup.                           |
| `consent_required`        | 422  | "Consent to transfer this photo to the model provider is required" | Tick that panel's consent box (the button stays disabled until then). Smoke needs `--transfer-consent`.               |
| `stale_version`           | 409  | "Inventory changed; reload it"                                     | Press **Reload latest materials and requirements**, re-save, ask again.                                               |

Other codes in the set: `provider_authentication` and `access_denied` (502, key
or model rejected), `network_error`, `provider_http_error` and `provider_error`
(502), `validation_error` (422, for example a photo that is not a JPEG or PNG
within limits) and `not_found`. A 401 from a project route means
`FORMA_API_TOKENS` is unset or the credential is wrong.

## 7. Privacy

- Photos are private to the owner. A photo goes to Muse only when you tick that
  request's consent box, and only the photo selected for it.
- Proof exports (text and JSON) exclude photos and photo ids. They do include
  your goal and notes.
- Remove current inventory links before deleting a photo. A photo linked to
  physical-report or Muse-diagnosis evidence in any project version cannot be
  deleted individually; the API returns 409. There is no evidence-unlink action.
  Deleting the whole project removes its photo and evidence records. The media
  list exposes only an `evidence_linked` boolean for this restriction, without
  evidence IDs, text or counts.
- Never put credentials in `NEXT_PUBLIC_*` variables, commit photos, or record
  a screen that shows the owner credential.
