# Issue #6: private project photos

Owner: @olartgabo; cross-lane review requested from @ResniDev through the PR.
Branch `issue/6-private-media-integration`, based on the merged progress in main.
This slice adds private photo storage
and inventory references; immutable plans/events, hosted identity and approved
revision transactions remain open. No shared domain/compiler schema changes.

## Contract handoff

The parent integration owns `projects.py`, `pyproject.toml`, generated `uv.lock`,
API documentation and the decision record. This branch owns `media.py`,
`test_media.py` and this handoff. Reuse the existing project authentication
dependency and `ProjectStore` transaction; include `media_router(store,
authenticate)` under the project router. Pillow 13.0.0 is the pinned decoder.

SQLite `media` columns are `id`, `project_id` (foreign key to projects with
`ON DELETE CASCADE`), `content_type`, `width_px`, `height_px`, `body` (BLOB).
Creating the table in the shared transaction initializer keeps inventory scope
checks and project deletion available even before the first upload. Inventory
accepts image IDs only when their media row belongs to that exact project;
measurement evidence references remain rejected until evidence persistence exists.
Project deletion purges media request receipts as well as cascading live blobs.

- POST `/api/projects/{project_id}/media` accepts a raw JPEG, PNG or WebP body,
  its MIME in `Content-Type`, and `Idempotency-Key`. It returns
  `{media: {id, project_id, content_type, byte_count, width_px, height_px}, replayed}`.
- GET `/api/projects/{project_id}/media/{media_id}` returns authenticated private
  bytes with `private, no-store`, `nosniff` and attachment headers.
- DELETE at the same path requires `Idempotency-Key` and returns
  `{media_id, deleted: true, replayed}`. Remove current inventory references first;
  otherwise deletion returns 409 without changing inventory or media.

Uploads require 1 byte to 8 MiB of source bytes and at most 20 million decoded pixels.
The normalized result must also fit 8 MiB. Streaming overflow is rejected even
without a declared length. MIME must agree with the decoded format; malformed,
truncated and animated images are rejected. EXIF orientation is applied, then
only pixels are re-encoded in a fresh image, removing EXIF, ICC and PNG text.
These pixel dimensions confer no physical measurements or verification status.

Owner checks precede reading upload bytes and run again at commit. No connection
is held across an await. Decode and SQLite work run in worker threads. Media and
replay receipts commit together; failed receipt writes roll back the mutation.
Exact upload retries return the original metadata, changed bytes return 409,
and concurrent identical retries create one blob. Retrying an upload after its
photo was deleted returns 404 and cannot recreate it. Historical inventory retry
responses may describe original photo references; they do not restore references
or media into active state. Project deletion removes those saved responses.

SQLite deletion is logical. Free pages, backups and forensic erasure remain
outside this slice. No photo is sent to a provider or shared publicly; upload
does not imply transfer consent. External retention controls remain required
before provider integration. Unknown physical dimensions stay unknown.

## Verification

On the integrated source plus this slice, with the parent's shared storage and
Pillow dependency changes copied into the worktree for verification:

- `uv run --locked pytest apps/api/tests/test_media.py apps/api/tests/test_projects.py -q`:
  `35 passed in 1.99s`, exit 0.
- `uv run --locked pytest -q`: `246 passed in 3.83s`, exit 0.
- `uv run --locked ruff check .`: `All checks passed!`, exit 0.
- `uv run --locked python -m forma_domain.generate --check`:
  `Generated contracts are current`, exit 0.
- Independent source/test review found no blocking findings and independently
  reran the first 32 photo/project cases successfully. The final three tests
  add inventory/delete races, normalized byte limits and project-delete rollback.

After integration, `npm run check` exited 0: Prettier/Ruff formatting, lint,
generated contracts, TypeScript, `246 passed in 3.86s` and the production web
build all passed. No live provider or
physical tests were attempted. Issue #6 remains open for its other acceptance
criteria. The next step is intake UI using these private endpoints, followed by
separately consented model transfer and durable plan/event/evidence storage.
