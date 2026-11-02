# Issue #7: local goal, photo and inventory intake

Owner: @olartgabo; cross-lane review requested from @ResniDev through the PR.
Branch `issue/7-intake-inventory`, based on the private-media slice merged in
#36. This is the first browser intake slice. Issue #7 remains open for tools,
device/design constraints, segmentation boxes and model-assisted proposals.

## Contract and behavior

The workbench consumes the existing project create/read, inventory save and
private-media routes. GET `/api/projects/{id}/media` now restores all uploaded
photo metadata, including unlinked photos. It checks project ownership before
querying and returns `{media: [...]}` with cache prevention. Individual bytes
remain private behind the authenticated media route. The list adds no model
transfer, public sharing or photo-derived physical measurement.

`python -m forma_api.generate` exports API-local Pydantic envelopes to
`apps/web/src/lib/generated/api-contracts.ts`. It imports the shared Stock type
from the domain-generated file. Root `contracts:generate` and `contracts:check`
run both exporters. Domain generation keeps its offline dependency boundary.

The web server rewrites `/api` to a fixed `FORMA_API_ORIGIN` configured before
dev/build, defaulting to `http://127.0.0.1:8000`. Only HTTP(S) origins without
credentials, paths, queries or fragments are accepted. The browser supplies the
configured development owner credential; no shared server owner token is
injected. Requests omit cookies, reject redirects and have an abort deadline.
Errors use local messages without echoing backend response content.

The access key stays in React memory and is cleared on disconnect or refresh.
The project ID remains in the URL so the owner can reconnect and reopen it.
Hosted identity and deployment access control remain pending; this is a local
development flow, not public registration.

Each row represents one physical stock item with a stable ID. New rows begin
with unknown measurements and no usable-region geometry. Editing a number
requires checking that measurement again; blank values remain null/unknown.
Unchanged saved measurements preserve their provenance and evidence fields.
Existing usable regions are retained and their dimension controls are locked.
Projects with active plans cannot use pre-plan inventory edits. No web action
compiles a design, enables cutting or records a physical test pass.

Uploads persist privately before being linked to stock. The gallery restores
unlinked photos after reload. Linked photos cannot be deleted until their
inventory links are removed and saved. Object URLs and in-flight reads are
cleaned up when the project/session changes. List responses are invalidated
before and after photo mutations so late reads cannot overwrite newer state.

Ambiguous mutation failures retain an immutable payload snapshot and its
idempotency key. Editing stays locked until that same request is retried or the
owner disconnects. A stale inventory save keeps the draft visible and requires
explicitly reloading/reviewing current inventory before saving again.

## Validation

Independent review found and corrected a gallery list/mutation race, then found
no remaining blocking source findings. Generated API and media checks, client
header/redaction/cancellation probes and UI TypeScript checks were also run
independently. Root `npm run check` exited 0: formatting, lint, domain/API
contract freshness, TypeScript, `# pass 8` / `# fail 0` client checks,
`250 passed in 5.18s` Python checks and the production build (4/4 pages).

Browser checks used an isolated local database, a synthetic owner credential,
generated PNG pixels and explicitly synthetic dimensions. Observed behavior:

- Created a project with a Spanish goal; saved width/height while thickness
  remained blank and unknown.
- Uploaded a private image, linked it to stock and saved; deletion was disabled
  while the saved link existed.
- Refreshed, observed an empty credential field and empty local/session storage,
  then reconnected and restored dimensions, unknown thickness and the photo link.
- Changed the inventory in another API session, observed the stale-save panel,
  and reloaded the current value without filling unknown thickness.
- Delayed an old gallery response until after upload; the new photo remained
  visible when that response was released.
- Dropped a save response after the server committed it; the retry used identical
  request bytes, returned `replayed: true` and preserved locked editing until
  the outcome was known.
- Inspected desktop and 390-pixel mobile screenshots; the mobile document fit
  the viewport without horizontal page overflow.
- Reopened the saved project through the production server and restored the
  confirmed width, unknown thickness and both uploaded photos.

These are software checks. No provider request, real material measurement,
physical attempt or physical pass was performed. Browser artifacts and the
temporary database are ignored local files.

## Next work

Add agreed tools/device/segmentation contracts and the consented provider path,
then connect validated design selection and authoritative manual steps. Persist
plan/event/evidence history before recording physical progress or activating a
revision. Actual inventories and test conditions remain #2/#27/#13 inputs.
