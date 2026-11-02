# Provider configuration status agreement

Status: implementation prepared on `issue/91-provider-status-agreement`, based on
PR #91 head `ccac960`. Resolves the configuration mismatch identified in
ResniDev's architecture review; publication remains with the supervisor.

## Contract and behavior

`GET /api/provider/status` keeps the existing `{configured, model}` response.
The status route and `MetaGateway` now share Spark/SAM defaults and the compiled
model ID validator. A nonblank key and valid IDs for both models are required
for `configured: true`. Invalid Spark text is replaced with the safe default in
the response; invalid SAM text is never returned. A valid Spark ID remains
visible when another configuration field is invalid.

The route constructs no gateway or transport and makes no provider request.
Configuration acceptance establishes no account access, quota or live provider
readiness. No generated contract or domain schema changes are required.

## Verification

- `uv run --locked --offline pytest -q apps/api/tests/test_health.py apps/api/tests/test_model_gateway.py`
  exited 0: `95 passed in 5.78s`.
- `uv run --locked --offline ruff check apps/api/src/forma_api/model_gateway.py apps/api/src/forma_api/routes/health.py apps/api/tests/test_health.py`
  exited 0: `All checks passed!`.
- Ruff formatting completed: `1 file reformatted, 2 files left unchanged`.

Tests cover invalid Spark and SAM values without transport construction or key
disclosure, and 24 environment combinations compare status against real gateway
construction while forbidding HTTP requests. No live model or physical test ran.
Full integration checks remain the publishing supervisor's responsibility.
