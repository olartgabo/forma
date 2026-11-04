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

- Python suite after integrating main: `2248 passed, 4 skipped` (the skipped tests need POSIX).
- Web unit tests passed in the full `npm run check` run.
- Affected construction route/runtime tests: `54 passed`.
- Typecheck, production build, Ruff, formatting and generated-contract checks passed.
- Photo-first browser replay: two intercepted hypothetical requests, review before
  diagrams, next-step navigation, correction notes in regeneration, and fresh
  acknowledgement before showing the revised manual. No provider calls.
- Independent review identified the hidden sidebar/layout issue; it was fixed.

The implementation is local on `codex/photo-first-manual`; the hosted deployment
has not been updated. A bounded live browser run is recorded below. Browser fixtures remain separate from that result.


## Live browser verification — November 4, 2026

Computer use exercised the local production web build and actual server-side
Meta gateway using the user-supplied workshop reference PNG. Image provenance is
unverified; no physical build or recognition-accuracy claim follows from it.
The goal was a stationary tabletop camera cradle beside the helmet, with no
helmet modification or riding use.

The finite run allowed four approximate-construction calls to muse-spark-1.3,
8,192 output tokens per call, a 64,000 input-token reservation per call (not a
provider-enforced input ceiling), 7 MB request and 48 KB text bounds, and expiry
at 2026-11-04 18:32:52 UTC. Two calls were used; the server was then stopped.
Durable private reservations and actual usage receipts remain outside git.
Historical unknowns and coding STOP files were left intact.

| Browser action | Observed result |
| --- | --- |
| Upload supplied PNG with consent and generate | Two concepts; first concept had three named pieces and six illustrated assembly steps |
| Accept estimates and navigate steps | Preparation outlines and step diagrams appeared |
| Reload and check original request | Stored response replayed; no additional provider dispatch |
| Correct sheet to 200 x 200 mm and base to 100 x 80 mm | Returned estimates matched; base preparation outline showed 100 x 80 mm |

Provider-reported usage: first call 3,077 input / 2,665 output tokens in 23.5 s;
second call 3,145 input / 3,724 output tokens in 29.7 s. Total 6,222 input and
6,389 output tokens, two settled outcomes, zero unknown outcomes. No monetary
amount was reported. The test exposed missing preparation guidance; the UI now
shows approximate per-piece outlines/dimensions and plain assembly actions.

This verifies live photo-to-concept generation and correction on a local build.
It does not establish physical fabrication, stability, a real recovery, SAM,
held-out evaluation, or deployment of this branch.
