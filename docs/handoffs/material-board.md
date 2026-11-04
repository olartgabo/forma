# Illustrated material board

The guided intake displays a blueprint material board using actual recognized
items, the shared stock draft, and the shared tool list. The supplied front-facing
library is bundled as transparent WebP, with a crisp CSS silhouette shadow offset
left/down at 35% opacity. The mascot paths reuse the existing FORMA brand artwork.

The board groups repeated recognized categories without inventing counts. Six
objects appear on desktop and three on phones; the complete editable records stay
in the review section. The objects sit together in one outward-facing fan, with
the left and right edges leaning away from the center. Hover and keyboard focus
lift and slightly enlarge the image with a white silhouette outline. Clicking
keeps a visible selection marker, opens the review section and focuses its existing
control. Tool cutouts open the existing tool editor. Corrections and saves continue
through Claude's recognized-item persistence; this board adds no persistence API
or fabrication authority. Unknown categories and failed images keep their names
and a question-mark silhouette. Generic tape is not guessed to be duct tape.

The integrated photo-intake dependency now requires an unchecked, piece/photo-
specific declaration that the piece is flat and on the reference surface before
measuring; it no longer silently supplies that affirmative capture provenance.

Intake and construction progress come from real request state. The existing cube
loader remains available for long requests. The board stays mounted while design
generation runs; View your design appears only for a returned construction plan,
and opens the existing design results. There are no timed discoveries or forced
loading delays. Model suggestions remain unconfirmed.

## Assets

`apps/web/public/materials` contains 60 optimized assets (48 materials, 12 tools),
totalling 3,574,018 bytes versus 56,103,953 bytes of originals. They are at most
720px, 12,956–184,132 bytes each, and retain transparency. Only visible cutouts are
requested, at most six at once. The manifest records per-file sizes and dimensions.
PNG masters remain in the external asset archive. To reproduce conversion:

```sh
node tools/prepare-material-art.mjs
```

## Verification

Run `npm run test:web`, `npm run typecheck`, and `npm run build`. The browser
regression runs against the real local app with synthetic intercepted API
responses; no provider or physical result is implied:

```sh
node apps/web/tests/material-board.browser.mjs /absolute/path/to/playwright/index.mjs http://127.0.0.1:3011
```

To include construction loading/success/failure and design navigation, first
export the existing offline construction fixture, then pass it as the fourth
argument (after the screenshot directory):

```sh
uv run --locked python apps/web/tests/muse-construction-fixture.py ../output/material-board/construction-fixture.json
node apps/web/tests/material-board.browser.mjs /absolute/path/to/playwright/index.mjs http://127.0.0.1:3011 ../output/material-board ../output/material-board/construction-fixture.json
```

Local validation: 213 web tests, TypeScript, production build and formatting pass.
Independent Sol review approved the implementation. The screenshots use labeled
synthetic API state and supplied representative artwork, not live recognition.

Existing catalog and guided-intake dependency/review gates remain applicable
before merge. The November 4 runtime authorization separately permits bounded
app-runtime tests without renewing the disabled coding guard's expiry or removing
its STOP files.

Final browser run passed at 1280, 390 and 320 pixels, including saved corrections, keyboard focus, missing-image fallback, and construction pending/success/rejection. No provider calls were made.

## Runtime verification — November 4, 2026

After independent review of the harness and eight offline control checks, one
live intake request used the supplied synthetic corrugated-cardboard reference
image (1261 × 1247 pixels; 2,012,015 bytes). The actual app intake runtime and
fixed-origin server transport were used; credentials remained server-only.
The run allowed one call, no retries, a 4,096 completion-token limit, a 30-second
request timeout and a fixed one-hour authorization. Input controls limit image
bytes to 5,000,000, serialized request bytes to 7,000,000 and textual context to
48,000 bytes. The 64,000 input-token reservation is an accounting reservation,
not a provider-enforced input-token ceiling.

The request outcome is unknown after 30,094 ms. The original receipt has no
failure-code detail, so the cause cannot be established from it. The durable
reservation remains recorded, the run halted and no retry was attempted.
Provider-reported usage and validated
recognized categories are unavailable; no recognition pass or dollar billing
amount is claimed. Reconcile this request before any retry. Private metadata
receipts remain outside the repository in the runtime-board-live output folder.
Historical unknowns remain recorded independently. This synthetic reference test
does not establish real-photo recognition coverage or physical validation.

The harness now records only allowlisted gateway failure codes for future runs,
with no exception text or response bodies. Ten offline control checks pass;
the existing unknown receipt remains unchanged and unresolved.
