# SAM photo localization (#4)

Owner scope: dedicated API runtime/route, browser panel/client, serialized mount,
contract generation and tests. No fabrication, repair, viewer or measurement code
changed. Base: origin/main 9ae6ea2. Branch: issue/4-sam-photo-localization.

POST `/api/projects/{project_id}/photo-localizations` accepts existing `media_id`,
`expected_revision_id`, one `concept`, explicit `provider_transfer_consented: true`
and `idempotency_key`. It returns source-pixel boxes, actual provider trace counts,
unknown token counts when omitted, and `unverified_photo_annotation`. JPEG/PNG,
5,000,000 bytes maximum; stored normalized upload dimensions must match every box.
Private upload normalization already removes metadata and corrects EXIF orientation.

Owner/project/media and revision are checked before dispatch; final revision and
media existence are checked under the receipt write lock. Only request receipts
are written: inventory, plans, physical events and evidence remain unchanged.
Successful or terminal exact-body retries replay without dispatch, even after a
revision changes. Pending/unknown requests block new keys throughout that project.
Transport retries are disabled. A crashed process leaves pending until an operator
reconciles the provider outcome; there is no expiry or automatic reset.

Browser receipts contain only the exact consented request, scoped to a SHA-256
owner-credential digest and project, not the raw credential. They are retained
before dispatch and survive reload. Recovery uses the original media/revision;
malformed/unknown responses preserve the receipt. Historical replay boxes have no
selection controls. Storage failures block dispatch. A known terminal response can
be explicitly cleared before a fresh consented request. Operator reconciliation is
required for unknown outcomes, including after a crash; do not clear unknown
server receipts merely to make another request.

The panel lets users choose a box, correct source-pixel coordinates manually and
review its name. The resulting reference is local only and clears on context or
concept changes. It does not silently save stock, crop an image, feed a physical
measurement, infer identity across photos, produce masks or reconstruct 3D.

Decision D058 explains why SAM 3D is not a physics input or a local dependency.
Official API documentation supports hosted SAM 3.1 boxes; live account access,
real-photo accuracy and provider billing remain unverified. No live calls made.

## Checks

Offline API tests exercise the real gateway with a scripted transport: consent,
ownership, stale context before/during dispatch, media deletion, format/size limits,
box-frame mismatch, empty results, no physical writes, concurrent pending keys,
unknown/restart protection, terminal replay and deletion cleanup.

Browser replay uses outputs generated through the actual API with an explicit
synthetic image and scripted transport. Run the fixture exporter and browser test
with a local web server, explicit Playwright module and optional `CHROME_PATH`:

```text
uv run --locked python apps/web/tests/photo-localization-fixture.py <fixture.json>
node apps/web/tests/photo-localization.browser.mjs <playwright/index.mjs> <local-url> <fixture.json> [screenshot.png]
```

The browser runner covers 390px/1280px selection, manual correction, consent,
no automatic provider calls, lost-response/reload recovery with the same body,
invalid/unknown response retention and historical result suppression. It blocks
unexpected external/API writes. This is software acceptance, not live SAM or
physical evidence. The browser check is separate from `npm run check`.

## Recorded offline results - November 4, 2026

- `uv run --locked pytest apps/api/tests/test_photo_localization.py -q`: 18 passed.
- Native Node localization client/receipt suite: 4 passed.
- Browser runner: passed at 390px and 1280px, including a second run after the
  final button/coordinate wording edits. Synthetic API fixture only.
- `npm run check`: passed. 173 web tests; 1,738 Python tests passed and four
  existing POSIX-shell devloop tests skipped on Windows; 18 guarded-devloop Node
  tests; formatting, Ruff, generated contracts, TypeScript and production build
  passed. The full Python run took 293.17 seconds.
- Final `npm run format:check`, `npm run contracts:check` and `git diff --check`
  passed after the wording/documentation edits. No source changed during review.

The temporary browser server on port 3051 was stopped and its listener confirmed
absent. The user's app on port 3043 was not changed. The screenshot and full check
log are outside tracked source under the workspace `output` directory. No provider
inference ran, no credits were consumed by these offline checks, and no physical
result was recorded. An independent root review reported no remaining actionable
issues; publication/merge and exact published-head CI remain the supervisor's work.
