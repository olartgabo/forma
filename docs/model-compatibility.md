# Model compatibility

Owner: @ResniDev. Issue #4. **G0 is open.** Two separate narrow server-only runtime receipt sets exist (both November 2, 2026): a historical software-image pair and a later realistic synthetic-photo pair. Full live compatibility is not verified.

## Documentation checked October 30, 2026

The official [structured output recipe](https://dev.meta.ai/docs/cookbook/structured-output) documents `https://api.meta.ai/v1`, `MODEL_API_KEY`, model `muse-spark-1.3` and Chat Completions `response_format.json_schema`. The gateway posts to `https://api.meta.ai/v1/chat/completions` and validates JSON again with the caller's Pydantic model. Documentation establishes a candidate protocol, not account access or successful inference.

[Image understanding](https://dev.meta.ai/docs/image-understanding) documents inline base64 images. The [tool recipe](https://dev.meta.ai/docs/cookbook/tool-function-calling) requires replaying the assistant tool call before its matching tool result. The spike forces one deterministic measurement check, validates its arguments/result, then requests typed final observations.

[SAM overview](https://dev.meta.ai/docs/sam/overview) documents `sam-3.1` at `POST https://api.meta.ai/v1/responses`, including nonstreaming responses. [Segmentation prompts](https://dev.meta.ai/docs/sam/segmenting) describes single-concept prompts and inclusive pixel box tokens. The spike extracts validated boxes only; mask decoding and overlays are not implemented.

These facts were read on October 30, 2026 and have not been re-verified since.

## Actual evidence

Two historical, server-only runtime calls to `muse-spark-1.3` succeeded on November 2, 2026 (UTC). They show that the provider accepted the server credential and returned usable output for the two app routes below, on one synthetic image. They are narrow receipts, not the full G0 acceptance.

### Runtime receipts, November 2, 2026

Source: sanitized server-only runtime acceptance reports and a reservation/settlement ledger from a bounded two-call harness. Raw prompts, responses, images, identifiers, notes and local paths are not reproduced here.

| Receipt | Route | Model | Reserved to settled (UTC) | Elapsed | Input tokens | Output tokens | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Photo intake | `muse-spark-1.3` | 08:03:19 to 08:03:31 | 12,140 ms | 2,418 | 1,611 | `ok`: 5 labels, 4 questions, measurement source `unknown` |
| 2 | Photo-only diagnosis | `muse-spark-1.3` | 08:03:46 to 08:04:00 | 14,109 ms | 2,975 | 2,025 | `ok`: 8 visible observations, 3 hypotheses, 4 questions or measurements, `failure_type` `unknown` |
| Total | | | | | 5,393 | 3,636 | 2 settled attempts, 2 model calls |

- Sums: 2,418 + 2,975 = 5,393 input tokens; 1,611 + 2,025 = 3,636 output tokens. Each route made one model call.
- Tokens are provider-reported usage and elapsed time is app-measured wall time. Token counts are not a charge. No actual billed amount, credit balance or dollar figure was recorded, and none is claimed. Live calls can consume credits; they are not free.
- Input was one PNG image (about 2.6 MB, accepted as eligible), labelled **SYNTHETIC SOFTWARE IMAGE**. It is not a team photo and not a physical build.
- State after both calls: no active plan, inventory not confirmed, no stock rows, measurements `unknown`, design readiness `needs_input` (blocker `missing_measurement`), physical verification `not_checked`. Design and repair were not requested.
- Authentication succeeded at that time. This does not show that a key is available or funded now; key presence was not checked for this document.
- The runtime verification window for these two calls has since expired and that harness has used both allowed attempts. The later photo harness below also used both of its attempts with a fixed expiry of 21:14:57 UTC. No provider call was made for this document. Further live calls need a new explicit authorization and the existing server-only key, reservation, journal and unknown-outcome controls.

### Realistic synthetic-photo receipts, November 2, 2026

A second, separate set. It is not merged into the table above; its counts are not added to the 5,393 / 3,636 totals. Source: sanitized private acceptance receipts and ledger from a new bounded harness, read at main `8d713154`. Project, revision and media identifiers, local paths, raw responses and the image are not reproduced. Full detail: [handoff](handoffs/issue-4-realistic-synthetic-photo.md).

| Receipt | Route | Model | Reserved to settled (UTC) | Elapsed | Input tokens | Output tokens | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3 | Photo intake | `muse-spark-1.3` | 20:45:43 to 20:45:52 | 9,484 ms | 2,442 | 1,716 | HTTP 200, `ok`: 4 candidate labels, 5 questions, measurement source `unknown` |
| 4 | Photo diagnosis | `muse-spark-1.3` | 20:45:52 to 20:46:03 | 11,219 ms | 3,033 | 1,584 | HTTP 200, `ok`: 8 observations, 3 hypotheses, 4 questions or measurements, `affected_ids` empty, `failure_type` `unknown` |
| Total | | | | | 5,475 | 3,300 | 2 settled attempts, 2 model calls, no pending or unknown entries |

- Sums: 2,442 + 3,033 = 5,475 input; 1,716 + 1,584 = 3,300 output. Tokens are provider-reported usage, not a charge; no billed amount is recorded or claimed.
- These were actual app API calls to the configured provider, not an intercept or mock. Input was one ChatGPT-generated realistic synthetic photograph (SHA-256 `e2ca67b40670767b35ba3a254472eed43dd757e20262739b1ffb6ff3f53a354d`) of overlapping cardboard, tape, craft sticks, scissors and a folded cardboard stand, with no ruler or scale. It is not an inventory or a build and is not physical evidence.
- Scope: manual user authorization, independent Terra review of the harness, 18 offline control checks, two lifetime attempts (one per stage), no retries, reservations with unknown-outcome halt, and one 30-minute window (20:44:57 to 21:14:57 UTC). The server was stopped after the sequence. No automatic renewal.
- Observed behavior matched the contract: no measurement was inferred, intake asked for actual availability and material identity, and diagnosis separated an irregular front edge from a possible fold, cut or synthetic-image artifact without confirming damage, strength, load or a physical test. No active plan or operation existed. Output remains untrusted proposal data.

### Gate coverage

| Check | State | Evidence |
| --- | --- | --- |
| Official protocol documentation | Checked | Links above, October 30, 2026; not re-verified since |
| Server-side key accepted by provider | Observed four times | Receipts 1 to 4; current availability and funding unknown |
| Spark image input with typed observations | Observed on synthetic images | Receipts 1 and 2 (software image), 3 and 4 (realistic synthetic photo) |
| Photo-to-app API flow, configured provider | Observed once, synthetic photo | Receipts 3 and 4; no physical or team-photo claim |
| Forced structured tool roundtrip | Not proven | Each receipt shows one model call; a tool roundtrip needs at least two |
| SAM on any image | Not attempted | No SAM call in the receipts |
| Consented real team photo | Missing | fixtures/ and data/ contain documentation/templates only |
| Account, deployment region, allowed use, privacy mode | Not checked | No account/dashboard verification |
| Hosted deployment | Not checked | Receipts came from a local server |
| Latency, usage and billed cost | Four samples (two per route) | Not a distribution; no billed cost recorded |
| Design, repair and replanning with a live model | Not requested | Receipts cover intake and diagnosis only |
| Manual box/label fallback primitive | Offline tested | Box validates label and inclusive image bounds without key/network |
| SAM masks/overlay UI | Not implemented | Caller must implement image review/correction |
| Physical success | Not tested | Gateway has no physical-state authority |

Intake and diagnosis output is untrusted proposal data. The receipts do not establish measured dimensions, stock, part identity, failure cause or any physical pass. Mocked responses in tests remain synthetic protocol cases. No guessed privacy-mode field is sent. Confirm Standard account privacy/retention settings and permitted region before private media use.

## Reproduce

From the root after `uv sync --locked`:

```sh
uv run --locked pytest apps/api/tests/test_model_gateway.py
uv run --locked python scripts/smoke_meta.py
```

Preflight exits 2 with explicit missing prerequisites. For an authorized live attempt, set server-only MODEL_API_KEY and confirm account permissions, region, privacy settings and media consent, then:

```sh
uv run --locked python scripts/smoke_meta.py --live --consented --image /private/team-photo.jpg --sam-concept "cardboard sheet"
```

Keep the photo outside git. PNG/JPEG input is limited to 5 MB with signature checks; this trusted local smoke input is not an authenticated upload API. Use one short noun phrase for SAM. Output contains safe status codes, box count and transport metadata only. Exit 0 means Spark schema/tool validation completed; inspect the separate SAM status, which may still require fallback. No labels, questions, raw response, key, image bytes or photo path are printed. The observation schema is local to the smoke script; product callers inject #3 domain Pydantic output types into `propose`.

## Bounds and handoff

The server-only adapter adds no route or state commits. Defaults, copied from `apps/api/src/forma_api/model_gateway.py`: four model rounds (configurable downward), 20-second per-call timeout (maximum 30), 60-second job budget (maximum 120), 2 MB response, `max_completion_tokens` 2,048, one tool execution and 32 SAM boxes.

**Retries.** `MetaGateway` retries each call at most `max_retries` times: default 1, allowed 0 to 2. Only HTTP 429, 500, 502, 503 and 504 are retryable. The wait is the valid `Retry-After` delta-seconds, otherwise 1.0 second, never more than 3.0 seconds. A retry happens only if at least 2.0 seconds of the job budget would remain after the wait; otherwise the original error is raised without sleeping. Retries do not consume model rounds and each attempt records its own trace. Never retried: timeout, network error, invalid or oversized response, authentication (401), access denied (403), budget exhausted and round limit. Refusals, malformed or truncated JSON and invalid tools also stop the proposal. When a failed attempt reports no usage, the aggregate usage is unknown, not zero. Tests: `test_retryable_rate_limit_once_then_success`, `test_retry_delay_uses_retry_after_capped`, `test_non_retryable_errors_never_retried`, `test_at_most_max_retries_per_call` and `test_no_sleep_when_remaining_after_wait_under_two_seconds`.

**Deadlines and DNS.** `MetaHTTP.post` runs each request on a bounded daemon worker. The caller waits for the per-call timeout plus 0.2 seconds of cleanup grace, then raises `timeout`, including when DNS resolution or TCP/TLS connect stalls before a socket exists. An active socket is also shut down, so slow headers and bodies are interrupted, and body reads re-check the deadline between chunks. A worker stuck in an uninterruptible OS call cannot be killed and may stay blocked as a daemon thread. It re-checks the expiry flag after `connect()` and before dispatch, so a late connection sends no authorization header, payload or request and is closed. Test: `test_http_stalled_connect_no_sock_times_out_and_never_dispatches`. Hosting should still enforce its own outer job deadline for process-level limits. Trusted deterministic callbacks must stay fast; the adapter cannot preempt arbitrary Python callbacks.

Only allowlisted read-only tools can be supplied. Callers own authenticated project scope, consent records, bounded domain schemas (two designs/three repairs), compiler integration and preserving the current validated manual on failure. Models cannot commit plans, complete operations or record test passes. META_SPARK_MODEL and META_SAM_MODEL override IDs server-side; changing them requires live verification. HTTP origin is fixed and redirects are rejected. Trace status describes transport; proposal validation failures surface separately through safe GatewayError.code values. API keys stay server-only.
