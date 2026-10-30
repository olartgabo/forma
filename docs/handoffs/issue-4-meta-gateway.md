# Issue #4 Meta gateway handoff

Status: offline spike implemented; live acceptance blocked. Owner: @ResniDev.

Changed paths: apps/api/src/forma_api/model_gateway.py, apps/api/tests/test_model_gateway.py, scripts/smoke_meta.py, docs/model-compatibility.md and this handoff. No routes, shared domain schemas, configuration or dependencies changed.

The gateway accepts a bounded prompt, optional consented image and caller-owned Pydantic output type. It returns only a validated proposal or safe error. An optional allowlisted deterministic tool has typed arguments/result; arguments validate before execution, result before replay, and final output after replay. Tools have no state activation authority. Domain #3 supplies product schemas; the smoke observation is explicitly local to the spike and does not define Stock/Measurement/BuildPlan.

SAM returns candidate media-pixel Box records; the same model with source=manual supports key-free user box/label entry. Boxes do not establish physical dimensions, identity, strength or user approval. Mask overlay, upload/auth routes and UI correction are future consumer work.

Official endpoints/protocols were read directly; sources and missing evidence are in [model compatibility](../model-compatibility.md). Next action: supply a server key and consented actual photo, verify account region/privacy/access/quota, run the live command and record actual sanitized results. Do not close #4 or claim G0 until this evidence exists.

Verification: pinned uv sync --locked installed the existing lock unchanged; Ruff check passed; Ruff format --check reported 42 files formatted; offline pytest reported 31 passed (29 gateway, 2 health) on Python 3.12.6 / pytest 9.2.0 / Pydantic 2.14.2. Smoke preflight reports missing key/photo/consent/live flag with no network request. Smoke exited 2; git diff --check passed. No physical attempts or provider successes are claimed.

Review follow-up: absolute call timers shut down active sockets to interrupt slow headers/bodies and are cancelled/joined in cleanup. DNS/pre-socket connection and OS delays remain documented limits. SAM refusals/missing/non-text output fail explicitly; only an explicit empty output_text counts as zero matches. Synthetic cancellation/cleanup and refusal tests pass.
