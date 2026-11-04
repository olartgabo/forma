# FORMA synthetic end-to-end test report

**Date:** 2026-11-04

**Revision tested:** `678edbf17c815cd412014205b88060246b8094dc` (latest `origin/main` after a fast-forward from `8f540c9`)

**Scope:** issues #27, #2, #13, #15, #16 and #17

**Environment:** Windows; isolated local API on port 8100, production web build on port 3100, separate temporary SQLite/media storage, test-only owners. No real owner data was changed.

## Executive assessment

The local browser-to-API path worked for creating a project, uploading and retaining an image, manually recording material, reading a compiled manual, activating a synthetic preview, exploring its assembly, checking stability, attempting a repair and viewing/downloading Proof. The tests below describe exactly what was exercised; they do **not** establish an end-to-end generated build or physical success. Live MetaMuse recognition, model-generated construction, diagnosis and recovery were not exercised: the local API reported the provider unconfigured and the existing encrypted runtime key was absent. The updated repository authorizes bounded app-runtime tests; the older blanket expired-window statement in the prior version of this report is superseded for such tests. No provider request was made in this run.

The most useful improvement opportunities observed are a more actionable invalid-photo error, clearer calibration guidance at the point of failure, and stronger context around the mobile diagram and missing server-side fabrication evidence. Details and reproduction steps follow.

## Test data and evidence

- An AI-generated, fictional overhead photo depicts cardboard, scraps, tape, scissors and a ruler. The image is **synthetic**, has no FORMA reference card and is not evidence of real stock or dimensions.
- [Screenshot: saved photo and manually added material board](test-report-assets/photo-board.jpg).
- [Screenshot: invalid upload feedback](test-report-assets/invalid-upload.jpg).
- [Screenshot: enlarged manual at 390 px](test-report-assets/mobile-manual.jpg).
- A second test project was seeded with the repository's explicitly synthetic stand fixture and compiled by the real local `PlanService` with synthetic opt-in. It contained eight generated SVG panels. This bypassed photo-to-design generation and used fixture process/profile data solely for software testing. It is not proof that the pictured materials are suitable.

## Browser test log

| Scenario and action | Observed result | Assessment |
| --- | --- | --- |
| Created a project with a synthetic phone-stand goal. | Project opened and the goal and project ID appeared. | Pass. |
| Selected the generated PNG with the browser file picker and clicked **Upload photo**. | The app displayed the image as Photo 1 at 1448 × 1086 pixels and said it was saved privately. It did not automatically generate inventory or invoke a model. | Pass for upload and display; no recognition inference was tested. |
| Added a cardboard sheet by hand, drew a box around it, checked the flat/same-surface declaration and tried photo measurement. | With no reference-line value, the app required a positive Line A. With a synthetic 100 mm line value, it rejected the input as more than 15% different from the card's expected check line. Width and height remained unknown. The photo contains no reference card, so this does not test valid calibration or detection. | Pass for this validation path; see finding 2. |
| Saved the material with unknown dimensions. | The board displayed the saved item, the checklist named width, height and thickness as missing, and linked-photo deletion was disabled with an unlink explanation. | Pass for observed state; no actual measurement was claimed. |
| Refreshed, re-entered the test-only credential and reopened the project. | The photo and material were retained; the credential had to be entered again. | Pass. |
| Uploaded a text file renamed `.png`. | The upload failed and the existing photo remained. The message was “Some details could not be accepted. Check your measurements and photo, then try again.” | Rejection passed; feedback needs improvement (finding 1). |
| With a second test owner, requested the first owner's project and image directly from the local API. | Both requests returned 404. | Pass for these two cross-owner reads, not a full security audit. |
| Opened the separately seeded compiled plan. Jumped from step 1 to step 8. | The preview showed eight steps, instructions, SVG and “Physical verification not attempted.” Step 8 named the synthetic device, test duration and criteria. | Pass. This is a fixture, not a plan generated from the photo. |
| Approved the fixture preview in the isolated test database. | The plan became active; the UI said approval does not complete work. It reported zero physical work. Jumping to step 8 showed its prerequisite operation rather than a completion form. | Pass for the approval and prerequisite gate. |
| Returned to step 1 without reporting work. | Checkboxes and an explicit actual-work confirmation were required; **Save physical report** was disabled. | Pass for initial gate. No fictitious physical report was submitted. |
| Opened the assembly viewer, orbited and selected the support part. | Part-specific links to associated manual operations appeared; the view called the geometry nominal and said physical verification is separate. | Pass for the controls exercised. |
| Ran stability analysis on the active synthetic fixture. | Status was **needs measurement**, listing missing assembled mass/center of mass, device pose, support contacts and policy/load cases. The diagram was labelled nominal. | Pass for missing-evidence handling. |
| Opened repair review, selected synthetic support and stock, entered a synthetic tear scenario, confirmed the test stock and simulated. | The candidate was blocked: “Resolve measured profile evidence before simulating a repair.” No repair was activated. | Pass for the missing-profile gate; a successful repair and its revision were not tested. |
| Opened Proof and downloaded JSON from the active fixture. | Proof showed zero of eight operations completed and functional test **Not attempted**. The downloaded JSON parsed successfully. | Pass for empty-history state and download; photo exclusion from a populated proof export was not verified. |
| Viewed the manual at a 390 × 844 viewport and expanded the diagram. | Step controls and instructions were visible; the diagram grew and its container stated that it can be scrolled. | Partial responsive check only; other viewport sizes and keyboard/screen-reader flows were not comprehensively assessed. |

## Findings to improve

### 1. Invalid photo feedback does not identify the actual problem — medium

**Reproduce:** select a file named `.png` containing non-image bytes and press **Upload photo**. The app rejects the upload but says to check “measurements and photo.” At this stage the user has not entered measurements, and the message does not explain that the file could not be decoded or how to recover. The existing saved image remained intact.

**Suggested improvement:** show a photo-specific error beside the upload control, such as “This file could not be opened as an image. Choose a valid JPEG, PNG or WebP.” Preserve the current generic fallback for unclassified failures. Verify with corrupt, wrong-format and oversized files.

### 2. Reference calibration failure is difficult to resolve in context — medium

**Reproduce:** upload a photo without the FORMA card, add a material, draw a box and select the flat/same-surface checkbox. Press **Measure from photo** without a line value. The error requires “Line A” while the reference controls can be collapsed. Entering 100 mm produced a generic instruction to measure the printed line; the precise “more than 15%” reason appeared only under **Details**. No invalid dimensions were saved, which is the correct outcome.

**Suggested improvement:** expand and focus the reference section when calibration is missing; put the specific failure and the next action next to the field. Distinguish an invalid printed-line measurement from a card that cannot be located, if the backend can reliably distinguish them. This run did not reach a valid-card detection attempt.

### 3. Mobile diagram requires deliberate discovery and panning — low

At 390 px the default SVG was very small; **Enlarge diagram** made it legible but required horizontal inspection. The instruction text remained readable. Consider an explicit visible pan cue or a touch-friendly zoom affordance next to the diagram, and verify all dimensions remain reachable at 320 px and with keyboard input. This is an improvement opportunity, not a confirmed clipping defect.

### 4. Local setup blocks a complete photo-to-build journey without operator context — delivery blocker

The photo project correctly displayed missing measured cutting process, reviewed joint profiles, parameters, kerf, edge margin and revision-specific server design context. The synthetic fixture's repair was likewise blocked by missing measured profile evidence. A new user cannot complete the real flow merely by uploading a photo. Provide the operator with a clear way to prepare and validate the revision-specific context from actual measurements and reviewed profiles, and keep the user-facing explanation linked to the next actionable step. Do not substitute synthetic fixture profiles for actual evidence.

### 5. Live inference and downstream recovery are still unverified — coverage gap

The isolated server reported `configured: false`, and no encrypted runtime key was available at the existing local key location. Muse intake, automatic recognition, proposed construction, photo diagnosis and model-supported repair therefore remained disabled. A separate bounded runtime test needs a configured server-only key, durable pre-dispatch reservation, fixed expiry, call and token caps, usage recording and unknown-outcome halting under the current `AGENTS.md`. This report does not claim those flows work.

## Automated checks on this revision

- `npm run build -w @forma/web`: exit 0; production build compiled and generated static pages.
- `npm run test:web`: exit 0; `# tests 219`, `# pass 219`, `# fail 0`.
- `uv run --locked pytest apps/api/tests/test_media.py apps/api/tests/test_projects.py apps/api/tests/test_plans.py apps/api/tests/test_photo_estimates.py apps/api/tests/test_progress.py apps/api/tests/test_proof.py apps/api/tests/test_repair_route.py`: exit 0; `170 passed in 36.50s`.
- The full `npm run check` from the earlier session passed on **the older commit** `8f540c9` (1,785 Python passed, four POSIX-only skipped; 191 web tests passed). It is historical and is not a full-suite result for `678edbf`.

## Issue-specific remaining acceptance

- **#27:** supply and record real materials, device measurements, photo/transfer permissions and participant decisions. Synthetic values are not those inputs.
- **#2:** measure two real inventories, perform and record the required joint/repair bench tests and stand attempt.
- **#13:** perform a real build and a non-scripted failure/recovery, recording actual work, versions, photographs, timing and rechecks.
- **#15:** complete the second physical build, held-out perturbations, impossible case and comparable baselines with observed outcomes.
- **#16:** verify the current hosted deployment end to end, fresh-session access, persistence, privacy, recording and participant-portal requirements. This local run is not hosted acceptance.
- **#17:** use the evidence above to track integration, distinguishing software checks from provider observations and actual physical gates.

The real physical and hosted gates remain open. The user-provided owner credential was not used or stored; the local work used separate test-only credentials and isolated data.
