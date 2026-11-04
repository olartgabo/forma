# Photo-first manual flow

The November 4 user direction makes image upload the default route to a manual
preview. Detailed entry remains available. A photo and per-request transfer
consent let Muse propose visible materials, approximate dimensions and named
geometry. Users review those assumptions before opening illustrated steps.

Estimates remain proposal data. They do not populate confirmed physical stock,
create a fabrication-ready plan, or report physical work. Geometry and step
illustrations use the existing construction engine. See D070.

Verification results are recorded in the implementation chat. Offline provider
fixtures verify the route and client behavior; they do not establish recognition
accuracy or a live provider result.

## Verification

- Python suite: `1964 passed, 4 skipped` (the skipped tests need POSIX).
- Web unit tests: `219` passed, `0` failed.
- Affected construction route/runtime tests: `54 passed`.
- Typecheck, production build, Ruff, formatting and generated-contract checks passed.
- Photo-first browser replay: two intercepted hypothetical requests, review before
  diagrams, next-step navigation, correction notes in regeneration, and fresh
  acknowledgement before showing the revised manual. No provider calls.
- Independent review identified the hidden sidebar/layout issue; it was fixed.

The implementation is local on `codex/photo-first-manual`; the hosted deployment
has not been updated. Actual model recognition and geometry quality still need a
bounded live run on the new implementation. Browser fixtures are not that result.
