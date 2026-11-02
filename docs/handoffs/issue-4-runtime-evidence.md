# Issue #4 runtime evidence handoff

Status: documentation reconciled with historical runtime receipts. G0 stays open; issue #4 is not closed. Owner: @ResniDev.

- Issue and acceptance criteria: #4 Meta gateway compatibility. Receipts cover only the two app routes below; the full live acceptance is outstanding.
- Branch: `agent/p0-runtime-evidence`, from `origin/main` at `0fedd2f8841b9f0b8f51ca42f16928438b7fbf55`. Commit: none yet.
- Changed files: `docs/model-compatibility.md` and this handoff. No code, tests, queue, configuration or other docs changed.
- Defect fixed: the compatibility page still said the key was missing, no live calls, latency or usage existed, and the gateway had no retries and old DNS bounds. It now reports the November 2, 2026 receipts and the current retry, deadline and DNS behavior from `model_gateway.py` and its tests.

## Sanitized receipts (November 2, 2026, UTC)

| Receipt | Route                | Model            | Elapsed   | Input tokens | Output tokens | Result                                              |
| ------- | -------------------- | ---------------- | --------- | ------------ | ------------- | --------------------------------------------------- |
| 1       | Photo intake         | `muse-spark-1.3` | 12,140 ms | 2,418        | 1,611         | `ok`, 5 labels, 4 questions, measurements `unknown` |
| 2       | Photo-only diagnosis | `muse-spark-1.3` | 14,109 ms | 2,975        | 2,025         | `ok`, `failure_type` `unknown`                      |
| Total   |                      |                  |           | 5,393        | 3,636         | 2 settled attempts                                  |

Calls were reserved and settled at 08:03 to 08:04 UTC in a server-only ledger. Input was one synthetic software image, labelled SYNTHETIC SOFTWARE IMAGE. Afterwards: no active plan, inventory not confirmed, measurements unknown, physical verification `not_checked`.

## What the receipts cover

- Observed: the provider accepted the server credential at that time, and Spark returned usable typed intake and diagnosis output for a synthetic image.
- Not billing: token counts are provider-reported usage. No actual charge was recorded and none is claimed. The calls are not free.
- Not current: authentication was observed then. Current key availability and funding are unchecked.

## Gates not proven

Full G0 remains open. These receipts do not prove: a forced structured tool roundtrip (one model call per route), SAM, a consented real team photo, account region, allowed use and privacy settings, hosted deployment, a live design, repair or replanning round, or any physical acceptance. Measurements, stock and failure cause stay unknown.

## Evidence handling

Reports and the ledger were read from the main checkout's ignored runtime acceptance directory; keys, settings and raw outputs were not read. Project and media identifiers, photos, notes, keys and local paths are deliberately omitted. Official documentation facts remain dated October 30, 2026; no new external documentation verification was done.

## Checks

Prose-only change. No app tests were run or claimed. Checks run: `git diff --check`, changed-path scope, link targets, UTF-8 and line-ending inspection, and a secret/path scan (see the return report). Gateway statements were compared by hand against `apps/api/src/forma_api/model_gateway.py` and `apps/api/tests/test_model_gateway.py`.

## Controls preserved

No live or provider call, install, commit, push or merge. Both Meta coding STOPs, the expired verification window, journals, unknown-outcome halting, server-only keys and payments are untouched. The bounded harness used both allowed attempts.

## Next action

Root obtains independent Sol/Terra exact-head review before publication and passing remote checks before merge. A further live attempt (tool roundtrip, SAM, real consented photo, region and privacy confirmation) needs a new explicit authorization and a renewed window by the owner.
