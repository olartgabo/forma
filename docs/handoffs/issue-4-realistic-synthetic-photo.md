# Issue #4 realistic synthetic-photo receipt handoff

Status: documentation of one actual connected-runtime acceptance. G0 stays open; issue #4 is not closed. Owner: @ResniDev.

- Issue and acceptance: #4 Meta gateway compatibility; connected photo-to-app intake and diagnosis priority.
- Branch: `agent/p0-realistic-photo-receipt`, from `main` at `8d713154a2ebc38c657b6111757ee153e0e33677`. Commit: none.
- Changed files: `docs/model-compatibility.md` and this handoff. No code, tests, queue, configuration or other docs changed.
- Defect fixed: the compatibility page had no record of the realistic-photo calls and said the only live evidence was one software-labelled image.

## Input

One ChatGPT built-in image-generation photograph, SHA-256 `e2ca67b40670767b35ba3a254472eed43dd757e20262739b1ffb6ff3f53a354d`. Intended content: ambiguous overlapping brown cardboard offcuts, a masking-tape roll, short wooden craft sticks, scissors and a roughly folded cardboard stand with a bent or uneven front support. No ruler, scale marks, labels, text or people. Exact dimensions, thickness, stock counts and strength cannot be established from it. It is synthetic software-acceptance input, not an inventory, build or physical test. The image is not published or copied here.

The reviewed project goal and the reported problem in the requests both stated that the image was synthetic, that dimensions, inventory and physical results were unknown, and that no plan or physical work existed. The reported problem was framed as a user report ("appears bent at the front support"), not an established failure.

## Expected behavior (from the source contracts)

- Intake (`intake_runtime.py`): list visible candidate material labels and questions only; never infer millimeters, stock availability or test results.
- Diagnosis (`diagnosis_runtime.py`): read-only photo observation; keep the user report separate from visible observations; propose no repair, plan, inventory or test result; with no active plan, `affected_ids` empty and `failure_type` `unknown`; ask targeted questions when evidence is insufficient.

## Actual output (sanitized, November 2, 2026 UTC, main `8d713154`, model `muse-spark-1.3`)

| Stage | Reserved to settled | HTTP | Elapsed | Input | Output | Calls |
| --- | --- | --- | --- | --- | --- | --- |
| Intake | 20:45:43 to 20:45:52 | 200 | 9,484 ms | 2,442 | 1,716 | 1 |
| Diagnosis | 20:45:52 to 20:46:03 | 200 | 11,219 ms | 3,033 | 1,584 | 1 |
| Total | | | | 5,475 | 3,300 | 2 |

Sums: 2,442 + 3,033 = 5,475; 1,716 + 1,584 = 3,300. These are provider-reported tokens, not dollar billing. The ledger shows two reservations, each settled, with no pending or unknown entry.

**Intake.** Four candidate labels (corrugated cardboard sheets lying flat, a folded cardboard stand-like shape, a light-colored tape roll, light wooden craft sticks), each prefixed "candidate". Measurement source `unknown`. Five questions: tape type, cardboard type and construction, whether the sticks are craft sticks, how many cardboard pieces and sticks are actually available, and whether other visible items should be excluded.

**Diagnosis.** Eight visible observations (flat cardboard on a wooden table, tape roll, three light wooden sticks, scissors, an upright folded cardboard form with a triangular side profile, an uneven irregular front lower edge on that form, exposed corrugation on cut edges, and a plant and window in the background). Three hypotheses: the form is a candidate phone-stand shape with high uncertainty; the irregular front edge could be a fold, a cut edge or a synthetic-image artifact and is not confirmed as bending or damage; the sheets, tape and sticks are only candidate materials with no confirmed stock. Four questions or measurements: measured dimensions, whether any confirmed inventory, plan or test exists, additional angles of the front edge without assuming failure, and how to record candidate material identities with uncertainty. `affected_ids` empty, `failure_type` `unknown`. No active version or current operation existed.

## Assessment

- Passed as a connected-flow acceptance: authenticated project creation, private upload, intake and diagnosis ran through the real app routes against the configured provider (not an intercept or mock), returned schema-valid output and settled cleanly.
- Output matched the prompt contracts: no inferred dimensions or stock, uncertainty kept explicit, the user's "bent" report not promoted to a confirmed failure, no strength, load or physical-test claim, no repair proposal, empty `affected_ids`, `failure_type` `unknown`.
- Read against the image by eye: the visible items named (cardboard, tape, three sticks, scissors, folded stand, uneven front edge, plant, window) are present. The plant and window were not in the generation prompt but are in the image. Intake did not list scissors as a candidate label; the intake contract is for materials, and its fifth question asks about excluding other items. This is not a contradiction and no bug is claimed.
- No contradictory app behavior was found. No fix is proposed.

## Limits

- One synthetic photo, one sample per route. Not a latency or usage distribution and not a repeatability result.
- Not physical evidence. Measurements `unknown`, physical verification `not_checked`, no inventory confirmed, no plan activated.
- Intake and diagnosis output is untrusted proposal data. The model's statements about the image are not verified measurements.
- G0 is not complete. Still unverified: forced structured tool roundtrip, SAM, a consented real team photo, hosted deployment, full plan, repair and replanning with a live model, and any physical pass. Account region, allowed use and privacy settings were not checked.
- These counts are a separate set from the historical software-image receipts (5,393 input, 3,636 output); the two are not merged.
- No new external documentation verification; documentation facts remain dated October 30, 2026.

## Authorization and controls

Manual user authorization; harness reviewed independently by Terra; 18 offline control checks passed before activation; two lifetime attempts, one per stage; no retries; fsynced reservations and halt on unknown outcome; one 30-minute window from 20:44:57 to 21:14:57 UTC with no automatic renewal; server stopped after the sequence; both attempts are exhausted. Both Meta coding STOPs, the old expired harness, settings, ledgers and payments are unchanged. Keys stay server-only.

## Evidence handling

Read only sanitized values from the private acceptance folder in the main checkout (image provenance, window, preparation receipt, runtime ledger, intake and diagnosis receipts, review packet), plus the generated image for visual comparison. Project, revision and media identifiers, local paths, raw responses and the owner token, keys and settings were not copied or read.

## Checks

Prose-only change. No app tests were run or claimed. See the return report for the diff, encoding, link and source-consistency checks.

## Next action

Root freezes the head, obtains independent Sol/Terra review of the exact head before publication and passing remote checks before merge. Any further live attempt (tool roundtrip, SAM, real consented photo, region and privacy confirmation, design or repair) needs a new explicit authorization and window.
