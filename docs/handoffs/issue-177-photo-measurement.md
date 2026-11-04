# Issue #177: guided photo intake and planar photo estimates

- Issue: [#177](https://github.com/olartgabo/forma/issues/177). Related: #7, #4, #149.
- Owner: @ResniDev (guided intake, photo measurement, their adapters). Reviewer:
  @olartgabo for the shared mounts listed below.
- Base: `main` at 41a1bf0, which includes #169 (assembly viewer, SAM
  localization and #149 measurement decisions). Branch `issue/photo-guided-intake`.
- Agent: Claude Code desktop on Opus 5.5. AGENTS.md asks for explicit Sonnet;
  the session could not switch its own model and the user chose to continue on
  Opus. No Meta/Muse/OpenCode coding worker or Meta-backed compaction was used.

## Scope and ownership

| Owned (new) | Shared mount changed (needs @olartgabo review) |
| --- | --- |
| `packages/photo_measure/**` | `packages/domain/src/forma_domain/models.py`: `Measurement.source` gains `photo_estimate`, never confirmed |
| `packages/domain/src/forma_domain/photo_measurement_contracts.py` | `packages/domain/src/forma_domain/generate.py`, `apps/api/src/forma_api/generate.py`: register contracts |
| `apps/api/src/forma_api/photo_measurement_runtime.py`, `routes/photo_estimates.py` | `apps/api/src/forma_api/projects.py`: inventory provenance check, router mount, project-delete purge |
| `apps/web/src/components/guided-intake/**`, `apps/web/src/lib/photo-estimates.ts` | `apps/api/src/forma_api/main.py`: public reference-card route |
| Tests: `packages/photo_measure/tests/**`, `apps/api/tests/test_photo_estimates.py`, `packages/measurement/tests/test_photo_estimate_gate.py`, `apps/web/tests/guided-intake.test.mjs` | `apps/web/src/components/intake-workbench.tsx`: guided step is the default; the full form moves under Details and shares one save path |
| | `apps/web/src/lib/photo-localization.ts`, `photo-localization-panel.tsx`: the SAM receipt store moved to the library so both callers share one |
| | `pyproject.toml`, `uv.lock`, `deploy/api.Dockerfile`, `package.json` (`test:web`), `apps/web/src/app/globals.css` |

Unchanged and reused: fabrication rules, repair search, product/assembly viewer,
compiler, #149 decision rules, Muse intake and SAM routes and their receipts.

## Behaviour

Default flow: goal → photo (with the printed card) → named cards → "Measure from
photo" → "Use photo estimate for exploring" or "I measured it with a ruler" or
"I don't know" → Save materials → next #149 question with the material
highlighted and why it matters → existing design proposals.

- Cards come from a consented Muse intake call or "Add a material by hand".
  Labels map to kind/material; unclear materials say "Material type is a guess".
  IDs are generated and carry the readable name (`cardboard-sheet-a--1f2e3d4c`);
  they appear only under Details. Renaming makes a new identity and drops photo
  values.
- Location: consented SAM ("Find it in the photo") or a dragged box. Outlines can
  be adjusted with pointer or keyboard (arrow keys, Shift for 10 px) and
  re-measured as a drawn polygon. Rectangle references are marked the same way.
- The full manual form, tools and build requirements remain under Details and
  work without any model.
- No provider call happens on upload, reload or render. Photo measurement is
  local and free; Muse and SAM require a per-request consent checkbox.

## Estimate contract and invalidation

`PhotoEstimate` keeps the full `EstimateInput` (stock ID/kind/material, media ID
and SHA-256, image size, reference input, outline input, capture declaration,
optional calibration), the input digest, reference corners in pixels and
millimetres, the outline and holes used, calibration status, method version,
per-dimension value, definition, displayed value and step, 5th/95th sensitivity
percentiles, uncertainty inputs (corner and outline sigma, reference tolerance,
fit RMS, hold-out error and count, measured edge scatter), diagnostics,
assumptions and one request when unusable. `measurement_status` is always
`photo_estimate_unconfirmed`.

Records are stored per project (`photo_estimates`) and never deleted except
with the project. A record becomes **stale** when its photo is deleted or its
bytes differ, the saved stock of that ID has another kind or material, the stock
left the saved inventory, or a newer estimate exists for the stock. Changing the
reference, outline or calibration produces a new input digest and therefore a
new record that supersedes the old one. The inventory rejects a
`photo_estimate` value that is not equal to a current estimate's displayed value
for that stock, field and linked photo (422). Plans already bind to an inventory
revision, so any change invalidates dependent previews through the existing path.
Exact retries replay the stored record through the existing request receipts;
a different body with the same key returns 409.

#149 treats `photo_estimate` values as unconfirmed estimates and still asks for
them when they matter (`test_photo_estimate_gate.py`). The compiler and
fabrication gates require confirmed values and are unchanged, so estimates do
not reach a buildable design. Exploratory designs from estimates are not
implemented.

## Supported cases and limits

- Flat sheets and strips on the same plane as the reference; one reference
  serves every material in the photo.
- Rectangles get edge length/width (may prefill stock). Irregular outlines,
  holes, non-square corners, unequal opposite edges or ragged traced edges get
  enclosing size and area only, with a request to measure the rectangle to cut.
- Not supported: tape, cord, curved, folded, stacked, raised or rolled items,
  thickness and any hidden property. A single photo cannot prove flatness,
  coplanarity or that nothing is occluded; these are user declarations.
- Lens distortion is uncorrected in the app (no calibration storage yet); the
  card's hold-out check catches some distortion near the card only.

## Dependencies

| Package | Version | Licence | Notes |
| --- | --- | --- | --- |
| opencv-python-headless | 5.0.0.93 (released July 2, 2026) | OpenCV Apache-2.0; wheel packaging MIT; bundled FFmpeg LGPL-2.1 and libvpx BSD (unused here) | `cp37-abi3` wheels for win_amd64 and manylinux_2_28 aarch64/x86_64; no libGL needed |

Uses the already-pinned numpy 2.5.4 and shapely 2.2.0. The API image
(`python:3.12.6-slim-bookworm`, glibc 2.36, arm64 `t4g.small`) satisfies the
`manylinux_2_28_aarch64` wheel. **Not verified:** no Docker build was run on this
machine (Docker is not installed), and the hosted host was not deployed.

## Checks run

`npm run check` (Node 22.23.4, npm 11.16.0 via corepack) exited 0 on
2c55efc: format, lint, contracts current, typecheck, 199 web tests, 1838
Python tests, devloop 18 tests, Next production build.

## Review

- Pre-review: one read-only Claude (Sonnet) pass; its findings were repaired
  (failed retries no longer supersede usable estimates, 2 mm / 1 % display
  floor without lens correction or independent check, design readiness asks
  for a ruler value, D060 states calibration is library-only).
- Independent Sol review (Codex CLI 0.166.0, `gpt-6.1-sol`, read-only, fresh
  context) of a72b32f: REQUEST_CHANGES, 8 findings. Repaired in 2c259b8
  (shared draft with Details and project keying, notch and out-of-photo
  outline checks, permanent retirement on type change or photo unlinking,
  rename on blur, SAM recovery bound to its material, exact #149 answer
  retries, single-threaded OpenCV). Re-review: 7 resolved, 1 open plus 2
  regressions; repaired in 2c55efc (lock Details during guided writes, apply
  guided edits to the latest draft, read early `removed` records). Second
  re-review: APPROVE, no regressions. Two repair attempts used.

## Accuracy

**Real-photo accuracy is unvalidated.** All numbers below are synthetic
geometry checks: rendered planar scenes with known homographies, optional lens
distortion, JPEG compression at quality 92 and 70, rotation and resizing. They
show the method is implemented correctly; they do not establish millimetre
accuracy on cardboard photos.

Observed in the synthetic suite: a 280 × 190 mm sheet at 0–40° tilt returned
within 3 mm with every result inside its sensitivity range; under JPEG with a
generous box the connected demo returned 280.0 × 190.3 mm with 0.14 px measured
edge scatter. A small hand-marked reference far from the material was refused
(±227 mm sensitivity), and ragged outlines are never accepted as rectangles.

### Defect found in the connected demo

The first browser run on a JPEG returned 290 × 202 mm for a true 280 × 190 sheet,
outside its own stated range: GrabCut absorbed compression noise beside the edge,
and the outline was simplified before edge fitting, which silently disabled the
straightness check. Fixed by seeding from the surrounding surface colour, a
compression-noise floor, sub-pixel colour-edge snapping, fitting edges on the
dense trace, and raising the outline uncertainty to the measured edge scatter.
Regression tests: `test_jpeg_photo_with_generous_box_near_a_marker`,
`test_ragged_edges_are_never_reported_as_a_rectangle`.

### Evaluation procedure (real photographs)

1. Choose the tolerance from the fabrication need before any evaluation photo is
   scored, and record it with its basis and date in the manifest. Suggested
   starting point: the joint/slot clearance the compiler requires for the
   reviewed profiles, not the estimator's own spread.
2. Print the card at 100 %, measure lines A and B with a steel rule.
3. For each sample, measure width and height independently with a steel rule
   (record the method), then photograph it beside the card. Vary distance,
   angle, lighting, surface and material; include deliberate failures (blur,
   clipped edge, steep angle, raised piece).
4. Put tuning photos in `split: "calibration"` and never adjust `RULES` using
   `evaluation` photos. Keep photos and the manifest outside git.
5. Run `uv run python -m forma_photo_measure.evaluate manifest.json`. It reports
   sample counts per split, accepted count, rejection rate, captures beyond
   tolerance, wrongly accepted captures (error above both the tolerance and the
   precision the estimate claimed), median and worst absolute and relative
   error, sensitivity-range coverage and median/worst latency.
6. Record the report (without photos) here, separately from the synthetic
   checks.

## Effort, same task (one cardboard sheet, photo to saved inventory)

Counted from the UI; no participant testing was done, so no usability claim is
made for children, older adults or anyone else.

| | Before (manual form) | After (guided) |
| --- | --- | --- |
| Physical measuring | Width and height with a ruler per sheet | Card lines A (and B) once per printed card; ruler only for values #149 asks for |
| Inputs per sheet | Add material, type width, tick confirmed, type height, tick confirmed, link photo, tick "I checked", Save (8) | Add or Muse suggest, draw box (or SAM), Measure, Use estimate, Save (5) |
| One-time setup | none | Print card, measure and enter its lines |

Thickness is not asked up front in either flow beyond the optional field; in the
guided flow it is asked by #149 only when it changes the result.

## Live tests

Not attempted. The external live verification window is expired; no Muse or SAM
request was sent. The connected demo used a synthetic rendered photo on a local
development server with a throwaway credential.

## Remaining work

- Run the real-photo evaluation above and record the report.
- Store and select per-device lens calibrations through the API.
- Usable-rectangle (inscribed) estimates for irregular sheets.
- Exploratory designs from unconfirmed estimates (compiler-lane decision).
- Docker build and hosted verification of the new wheel on arm64.
