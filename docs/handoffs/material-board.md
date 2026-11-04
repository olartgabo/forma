# Illustrated material board

The guided intake displays a blueprint material board using actual recognized
items, the shared stock draft, and the shared tool list. The supplied front-facing
library is bundled as transparent WebP, with a crisp CSS silhouette shadow offset
left/down at 35% opacity. The mascot paths reuse the existing FORMA brand artwork.

The board groups repeated recognized categories without inventing counts. Six
objects appear on desktop and three on phones; the complete editable records stay
in the review section. Clicking a cutout opens that section and focuses its existing
control. Tool cutouts open the existing tool editor. Corrections and saves continue
through Claude's recognized-item persistence; this board adds no persistence API
or fabrication authority. Unknown categories and failed images keep their names
and a question-mark silhouette. Generic tape is not guessed to be duct tape.

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

The existing external live-verification window is expired. This implementation
does not renew it, make provider calls, or validate recognition accuracy. Existing
catalog and guided-intake dependency/review gates remain applicable before merge.

Final browser run passed at 1280, 390 and 320 pixels, including saved corrections, keyboard focus, missing-image fallback, and construction pending/success/rejection. No provider calls were made.
