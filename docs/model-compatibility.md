# Model compatibility

Owner: @ResniDev. Issue #4. **Live compatibility remains unverified; G0 is open.**

## Documentation checked October 30, 2026

The official [structured output recipe](https://dev.meta.ai/docs/cookbook/structured-output) documents `https://api.meta.ai/v1`, `MODEL_API_KEY`, model `muse-spark-1.3` and Chat Completions `response_format.json_schema`. The gateway posts to `https://api.meta.ai/v1/chat/completions` and validates JSON again with the caller's Pydantic model. Documentation establishes a candidate protocol, not account access or successful inference.

[Image understanding](https://dev.meta.ai/docs/image-understanding) documents inline base64 images. The [tool recipe](https://dev.meta.ai/docs/cookbook/tool-function-calling) requires replaying the assistant tool call before its matching tool result. The spike forces one deterministic measurement check, validates its arguments/result, then requests typed final observations.

[SAM overview](https://dev.meta.ai/docs/sam/overview) documents `sam-3.1` at `POST https://api.meta.ai/v1/responses`, including nonstreaming responses. [Segmentation prompts](https://dev.meta.ai/docs/sam/segmenting) describes single-concept prompts and inclusive pixel box tokens. The spike extracts validated boxes only; mask decoding and overlays are not implemented.

## Actual evidence

| Check | State | Evidence |
| --- | --- | --- |
| Official protocol documentation | Checked | Links above, October 30, 2026 |
| Account, deployment region, allowed use | Not checked | No account/dashboard access provided |
| Key presence | Missing | No MODEL_API_KEY or Meta key environment names present; values never printed |
| Consented real team photo | Missing | fixtures/ and data/ contain documentation/templates only |
| Spark image/schema/tool live call | Not attempted | Smoke preflight blocks before network |
| SAM on real team photo | Not attempted | Same blockers |
| Manual box/label fallback primitive | Offline tested | Box validates label and inclusive image bounds without key/network |
| SAM masks/overlay UI | Not implemented | Caller must implement image review/correction |
| Privacy mode, quota, credits, usage/cost | Unknown | Requires account verification and real calls |
| Physical success | Not tested | Gateway has no physical-state authority |

No sanitized live response sample, latency or cost is available. Mocked responses are synthetic protocol cases, not live evidence. No guessed privacy-mode field is sent. Confirm Standard account privacy/retention settings and permitted region before private media use.

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

The server-only adapter adds no route or state commits. No retries. Defaults: four model calls (configurable downward), 20-second socket timeout/call budget, 60-second job budget, 2 MB response, 2,048 output tokens, one tool execution and 32 SAM boxes. HTTP errors, refusals, malformed/truncated JSON and invalid tools stop the proposal. DNS and OS scheduling may exceed socket deadlines; hosting should enforce an outer job deadline. Trusted deterministic callbacks must stay fast; the adapter cannot preempt arbitrary Python callbacks.

Only allowlisted read-only tools can be supplied. Callers own authenticated project scope, consent records, bounded domain schemas (two designs/three repairs), compiler integration and preserving the current validated manual on failure. Models cannot commit plans, complete operations or record test passes. META_SPARK_MODEL and META_SAM_MODEL override IDs server-side; changing them requires live verification. HTTP origin is fixed and redirects are rejected. Trace status describes transport; proposal validation failures surface separately through safe GatewayError.code values.
