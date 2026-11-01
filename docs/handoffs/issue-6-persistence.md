# Issue #6: private project and inventory storage

This records the original persistence slice. The subsequent
[private-media handoff](issue-6-private-media.md) adds scoped image storage and
allows inventory references to uploaded photos; evidence history remains pending.

Scope: first persistence slice, branch `issue/6-project-storage`. Consumes the
#3 domain handoff; changes no compiler, provider or shared domain contracts.

API-local Pydantic envelopes reuse domain `Stock` and `ErrorEnvelope`. Projects
have an inventory `revision_id` separate from nullable `active_version_id` (a
BuildPlan version). Inventory edits use `expected_revision_id`; the domain
`ConfirmInventory.expected_version_id` remains reserved for plan-version writes.
This avoids representing an inventory revision as a compiled plan. No plan is
activated by these routes.

Routes: POST `/api/projects`, GET `/api/projects/{id}`, PUT
`/api/projects/{id}/inventory`, DELETE `/api/projects/{id}`. All require a
server-configured bearer credential. Creation, inventory and deletion require
idempotency keys. Credentials map to owners; owner checks precede data/replay
access. SQLite transactions serialize revision checks and durable replay records.
No photos/evidence references are accepted until scoped media exists.

The local development auth configuration is `FORMA_API_TOKENS`, a JSON object
mapping owner IDs to distinct bearer tokens of at least 32 characters. There is
no default credential; unconfigured project access is disabled. This is a local
development credential mechanism, not a hosted sign-in implementation. Store
the database under `FORMA_DATA_DIR` (default `.local/forma`); no credential is
stored in SQLite. Browser login, hosted identity, media, plan/event/material
history and atomic adaptation remain follow-up work for #6/#12. Deleting a
project removes its local inventory; deleted-project retry metadata retains only
owner, project ID and request digest. External providers receive no data here.

Verification (local, no model credentials):

- `uv sync --locked`: pinned Python 3.12.6 and 26 resolved packages installed.
- `npm ci` using Node 22.21.0/npm 11.16.0: 30 packages added, zero vulnerabilities.
- `ruff check .`: all checks passed.
- `pytest -q`: 175 passed, including 13 new persistence checks.
- Independent read-only review found no blocking auth, concurrency or retry bugs.
  Deletion is logical; forensic SQLite erasure and backup removal are not claimed.

`npm run check`: exit 0; Prettier/Ruff formatting, lint, generated-contract
drift check, Next route generation/TypeScript, all 175 tests and production web
build passed (3/3 static pages). No live model or physical tests were run. Issue #6 remains open for its remaining acceptance
criteria; this PR must not close it.
