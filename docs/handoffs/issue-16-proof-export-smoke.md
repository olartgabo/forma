# Issue #16: Proof export read-only acceptance CLI

Status: implemented offline on `agent/proof-export-smoke` (base `4f87c7ae`), not
committed. Authored by native Claude Sonnet under the November 2, 2026 parent
authorization; independent review and exact-head checks remain with the root.

- Owner and reviewer: assigned lane per issue #16; independent Sol/Terra review pending.
- Branch and commit: `agent/proof-export-smoke`, uncommitted working tree.
- Changed files: `apps/api/src/forma_api/proof_smoke.py`,
  `apps/api/tests/test_proof_smoke.py` and this handoff. The Proof route,
  `proof-report.ts` and `demo_smoke` are references only and unchanged.
- Contract/schema changes: none; no generation command applies.

## Behavior

`python -m forma_api.proof_smoke --project-id ID [--api-origin O] [--timeout S]
[--credential-file F] [--json-export P] [--text-export P]`. `--help` needs no
network, token or files.

- Makes exactly two GETs: `/api/health` (no credential) and
  `/api/projects/{id}/proof` (owner bearer token). No POST, provider status,
  provider call, media byte read or mutation. The token comes only from
  `FORMA_SMOKE_OWNER_TOKEN` or `--credential-file` (demo_smoke convention).
- Reuses demo_smoke's bounded transport (total deadline, no redirects, 1 MB
  response cap), origin normalisation, credential loader and safe error codes.
  Additionally rejects plain `http` origins that are not loopback, so the bearer
  token is not sent in cleartext. Timeout is bounded to 0.1-30 s.
- The live snapshot must validate as `ProofSnapshot` and pass named coherence
  checks: `photos_excluded` (no non-empty `image_ids` or non-null `asset_id` at
  any depth, including nested repair simulation plans), `version_ids_unique`,
  `scope_consistent`, `states_match_ancestry` (active/historical/preview
  recomputed from the parent chain), `active_pointer_consistent`,
  `ancestry_complete`, `event/evidence/material_ids_unique`,
  `references_resolve` (event/evidence/material references to operations,
  parts, checkpoints, stocks, events), `progress_recomputes` (completed,
  carried, failed, last-event cursor and status recomputed with the server's
  rules), `expected_stock_recomputes` (via `progress.expected_stock`),
  `revisions_consistent`, `invalidations_consistent`, plus
  `project_matches_request` and `cache_prevented` (`no-store`).
- `--json-export`: bounded regular-file read, strict UTF-8, duplicate keys and
  non-finite numbers rejected, schema and the same coherence checks, then a
  semantic comparison of the model dump with the live snapshot excluding only
  `generated_at`. An export generated after the live snapshot fails.
- `--text-export`: structural comparison with the `proof-report.ts` layout:
  headings and state labels, version/inventory/candidate IDs, status text,
  completed/carried/new counts, revision lists, uncompleted operations,
  functional-test sections, timeline/evidence/receipt/expected-stock entries and
  invalidation lines. Multi-line user text is masked first so it cannot forge
  headings. It is not exact-text equality and not browser acceptance.
- A changed snapshot (for example a later physical report) fails as
  `snapshot_changed` or `text_structure_mismatch`; the tool cannot distinguish
  stale from inconsistent. With no export arguments the report says
  `artifact_verification: not_requested`.
- The JSON report holds booleans, counts, enums, check names and stable error
  codes. It never contains goal/notes, tokens, media IDs, file paths, export
  content, exception text or server bodies, including for malformed arguments.
  Exit codes: 0 verified, 1 verification/transport/export failure, 2 invalid
  arguments or credential. Bad export files fail before any request.

## Coverage limits (also in `coverage_limits` in every report)

Software consistency only. No physical test pass, provider result or measured
dimension is established or implied. No media bytes are read. User-authored
text is not inspected. Text exports get a structural check only. Export
verification covers only the files supplied. The two-GET design means the
snapshot is the server's single transactional read; there is no second fetch.

## Checks actually run (this checkout, shared venv Python 3.12.6)

`PYTHONPATH` pointed at this checkout's `apps/api/src` and each `packages/*/src`;
`forma_api` was confirmed to import from this tree.

- `pytest apps/api/tests/test_proof_smoke.py apps/api/tests/test_proof.py
  apps/api/tests/test_demo_smoke.py -q`: `172 passed in 43.62s`
  (`test_proof_smoke.py` alone: `67 passed`).
- `ruff check` and `ruff format --check` on the two source/test files:
  `All checks passed!` and `2 files already formatted`.
- The text-export tests run the real `apps/web/src/lib/proof-report.ts` through
  Node v24 (`--experimental-strip-types`) on real snapshots (active-only and
  repaired historical+active with invalidations). They skip only if Node is absent.
  The full `npm run check`, web tests and build were not run (outside scope).

Coordinator verification on the returned candidate used this checkout's explicit
`PYTHONPATH`: `67 passed in 34.58s`, Ruff clean and `2 files already formatted`.
The actual formatter/export subset was then repeated with pinned Node v22.21.0:
`6 passed, 61 deselected in 12.50s` (current/historical downloads, each export,
stale exports, structural mutations and multiline user text). One initial unused
import/lint cleanup was completed; there were no failed functional repair cycles.

Tests use the existing synthetic test_progress/test_proof/test_adapt fixtures
with an injected transport and dummy owner tokens. They verify the allowed
GET-only paths and header handling (no credential on health), current and
historical JSON/text exports verifying, stale/tampered/future exports failing,
malformed/oversize/duplicate-key/non-regular/missing files, scope, ancestry,
cursor, status, reference, revision, invalidation and nested photo-field
failures, transport/HTTP error redaction and offline `--help`.

## Not attempted

No live server, provider, Meta/Muse call, physical build or measurement. No real
browser download was inspected; the text check is against Node-run formatter
output, not a user-downloaded browser file.

## Pending and next action

Root independent review and exact-head checks. Possible follow-ups outside this
scope: a second-fetch stability option, an explicit stale-versus-inconsistent
distinction, and an index row in `docs/handoffs/README.md`.

## Independent review repair round 1

Terra found that invalidations were incorrectly restricted to the destination's
immediate parent. The read contract permits evidence from any ancestor: Adapt
collects ancestor evidence and records invalidation against the new version;
Proof attaches that invalidation to the original evidence version. The smoke now
walks the complete destination parent chain with a visited set, accepts a strict
ancestor and rejects missing parents or cycles. Existing destination-revision,
evidence-reference and unique-invalidation requirements remain.

The first bounded terminal Sonnet repair session could not construct a second
feasible repair with the existing fixture: replacement stock was exhausted or
the deterministic tape-undo continuation was unsupported; commit returned 409.
That session was stopped. Its scratch and diagnostic evidence remain private
under `.local/checkpoints`, outside the published change. No failed attempt is
relabelled as a successful repair.

After one targeted contract diagnosis, native Sol implemented the read-side fix
and regression. The regression starts with the existing approved two-version
fixture, then explicitly constructs a third persisted plan/revision and an
original-version evidence invalidation targeting it. It reads the actual Proof
route and verifies JSON plus text from the actual web formatter. This is
constructed persisted software history, not a second repair approval, physical
attempt or physical pass. A constructed unrelated saved preview, self target,
missing parent and cyclic ancestry fail. Before the fix the positive regression
failed solely on `invalidations_consistent` (`1 failed, 67 deselected in 5.26s`).
An initial negative-test setup tried creating a preview after activation and
correctly received a blocked response; the test now constructs that unused
persisted preview within the explicitly software-only history.

Final affected suite with explicit checkout `PYTHONPATH` and pinned Node
v22.21.0: `72 passed in 51.68s`. This includes all previous export cases and the
five new ancestry regressions, so the formatter subset was not repeated again.
Ruff reported `All checks passed!` and `2 files already formatted`.

The review-round count remains 1, with the prior unsuccessful fixture attempts
preserved. Root's same independent Terra reviewer must rereview this fix before
publication.
