# Runtime response deadlines

Issue: [#16](https://github.com/olartgabo/forma/issues/16), connected-flow
reliability; also affects #7 intake, #11 diagnosis and #12 repair.
Branch: `issue/16-connected-flow-hardening`. Owner: @olartgabo; independent
native review required before publication.

## Problem and behavior

The web client and Next.js external rewrite both stopped waiting after 30 seconds,
while the server gateway permits 60 seconds by default and at most 120 seconds.
A successful response after a provider retry could therefore be lost. Active
diagnosis can persist evidence server-side even after the browser stops waiting.

The four runtime requests now have a 130-second browser deadline; ordinary
storage reads and writes retain 30 seconds. The proxy deadline is 140 seconds.
User cancellation, bounded response-body reads, safe errors, consent and the
absence of automatic browser retries remain in place. No API/domain contract,
compiler, provider budget or provider configuration changes. See D029.

Owned files: `apps/web/src/lib/api.ts`, `apps/web/next.config.ts`,
`apps/web/tests/api.test.mjs`, this handoff and `docs/decisions.md`.

## Verification

Thirteen new regressions cover all four runtime request functions: valid delayed
responses, stalled response bodies, cancellation after thirty seconds, cleared
timers, no automatic retry and a finite proxy deadline beyond the client limit.
The existing ordinary-request stalled-body regression retains its 30-second
expectation.

`PATH=/tmp/forma-tools/bin:$PATH UV_CACHE_DIR=/tmp/forma-uv-cache npm run check`
outside the sandbox exited 0: formatting, Ruff lint, both generated-contract
checks, strict TypeScript and production build passed; web `102` passed, `0`
failed; Python `1099 passed in 55.91s`; guarded Node `18` passed, `0` failed.
The build reported `proxyTimeout: 140000`. The sandboxed full check hung in
FastAPI TestClient startup and was interrupted; these complete results come
from the rerun with pinned Node 22.21.0, npm 11.16.0 and uv 0.11.16 under `/tmp`.

A local HTTP fake returned through the installed Next.js `proxyRequest` utility
with this checkout's configured proxy timeout: `HTTP 200 after 35035 ms`.
This verifies the configured proxy utility, not a hosted deployment or a full
browser session. Direct Node execution also passed all `97` API tests and `5`
photo-preview tests. `git diff --check` passed. A fresh independent native Sol
review approved the complete five-file diff with no blocking findings; no repair
round was needed.

## Remaining gates

No Meta request or physical test was attempted. The local proxy check uses a
fake HTTP backend and establishes only response forwarding. Hosting/auth/storage
decisions, current live guard prerequisites, real measured inputs and actual
build/recovery evidence remain separate acceptance requirements. Hosted proxy
and platform timeouts must be checked when a deployment target is chosen.
