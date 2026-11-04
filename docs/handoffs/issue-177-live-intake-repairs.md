# Issue #177 follow-up: live intake repairs

Branch `issue/live-intake-repairs` (PR #188). Decision D071, which is one
implementation with D066 and D067 (#186/#187). Follows the material
catalog (D062, `issue-177-material-catalog.md`) and the photo estimator
(`issue-177-photo-measurement.md`).

## Why

A bounded live run on November 4, 2026 (Terra agents, head 7dc1744, report in
`output/terra-live-materials/REPORT.txt`) showed:

| Live test                      | Result                                                            |
| ------------------------------ | ----------------------------------------------------------------- |
| Synthetic corrugated cardboard | Sensible label, `items=[]`                                        |
| Synthetic notched sheet        | Sensible label and question, `items=[]`                           |
| Synthetic plastic bottle       | `incomplete_output` at the 2048-token cap; finish reason not kept |
| SAM, notched sheet             | Completed with zero boxes                                         |

The estimator measured the notched sheet correctly from a ground-truth box,
but no live region ever reached it.

A likely cause of the empty item lists: the connected intake prompt began with
the generic intake task, "List visible candidate material labels and questions
only", which contradicted the item request, and `items` defaulted to empty, so
a label-only answer validated as success.

## What changed

1. **Structured intake** (`intake_runtime.py`, `material_catalog.py`).
   - The connected call has its own prompt, `intake-items-v2`, and provider
     schema, `IntakeProposal`: `recognition` (`items`, `partial` or
     `no_objects`), `items` and `questions`, all required.
   - An unidentifiable object is an `uncertain` item, and a pile is one
     `group_count_unknown` item.
   - Label-only, empty or inconsistent answers are refused. Labels are
     derived from items.
   - The API `IntakeObservation` keeps its earlier fields. `recognition` is
     omitted when absent, and the web treats such a legacy answer as
     "no item cards" and adds nothing.
2. **Failure diagnostics and bounded reasoning** (`model_gateway.py`,
   `provider_diagnostics.py`, `intake_runtime.py`, `lib/intake-failure.ts`).
   - Reconciled with #186/#187 on main: photo intake uses
     `reasoning_effort=low`, an 8,192 completion ceiling and one 120-second
     attempt without retries. Other proposals are unchanged.
   - Errors keep main's public family (`invalid_response` etc.) and its
     diagnostics: allowlisted `reason`, model, elapsed time, usage and
     validation issues. This branch adds the sanitised provider
     `finish_reason` (`[a-z_]{1,32}`) and reported reasoning tokens. A
     truncated answer has reason `incomplete_output`, and the web adds "It
     ran out of room for the answer." There is no separate public code.
   - The fresh answer is bounded (12 items, 80-character evidence, three
     short questions); even its largest valid form fits the old 2,048 cap.
   - Labels alone never become cards, including on main's former fallback.
3. **Zero-detection recovery** (`guided-intake/index.tsx`, `model.ts`,
   `forma_photo_measure/suggest.py`, `POST /photo-outline-suggestions`).
   - SAM boxes covering at least 90% of the photo, or lying mostly on the
     marked reference, are dropped.
   - When nothing usable remains, the card explains why and keeps the photo,
     reference and material.
   - The card offers **Draw a box** and, for sheets and strips, **Suggest an
     outline**. The suggestion is local and deterministic: it excludes the
     reference and regions cut off at the edge, and is returned only when the
     outline search confirms it.
   - The estimator now blocks any outline lying mostly on the reference
     (`outline_is_reference`).
4. **Reconciliation** (`recognized_items_runtime.py`, `projects.py`,
   `plans.py`, `adapt.py`, `fabrication_runtime.py`, repair routes).
   - A saved item that contradicts its linked material records a hold and
     sets `inventory_confirmed=false` under a new inventory revision.
   - Design readiness and generation, construction, synthesis and plan
     compilation require confirmation, and plan activation now does too.
     Confirmation does not gate an active build's repair and fabrication
     actions, so those check the holds directly (below).
   - The material card shows a blocking panel with **Remove this material**,
     or the option to retype the item or the material.
   - Restoring confirmation happens only by resolving a hold. Inventory saves
     stay unconfirmed while a contradiction remains.
   - A new contradiction is refused during an active build. Contradictions
     saved earlier are held at startup, active builds included.
5. **Held active builds** (`require_no_holds`, `hold_blockers`).
   - While a material is held, these refuse with `409 blocked`: repair
     search, Muse repair advice (no provider call, and re-checked after the
     call), repair simulation, repair approval, fabrication assessment and
     scheduling a saved repair preview.
   - The active fabrication report stays readable as history but carries a
     `needs_confirmation` blocker naming the held stock, so it offers no
     order. The hold enters through the fabrication engine's existing
     context-blocker input; Gabo's fabrication rules are unchanged.
   - Events, evidence, plan versions and saved previews are never rewritten.
     An exact replay of an outcome recorded before the hold is still
     returned. Once the hold is released (for example by correcting the
     item), the same saved preview can be scheduled and approved.

## Offline regressions

- **Intake:** label-only replies from live runs 1 and 2, the run-3
  truncation (finish reason and usage kept, one call), `no_objects`,
  `partial`/`uncertain`/group answers, and the bound on answer size.
- **Gateway:** traces keep the finish reason and reasoning tokens, and
  unrecognised reasons are sanitised.
- **Photo measurement:** the suggestion finds the sheet and not the card, the
  notched sheet stays `enclosing_only`, a reference-only or cut-off scene
  gets no suggestion, a box around the card is refused, and the route test.
- **Held active builds** (`test_material_holds.py`): repair search,
  simulation, assessment and the blocked active report; a preview saved
  before the hold is neither scheduled nor approved, then is after release;
  an exact replay of an earlier approval; Muse repair advice refused with no
  provider call; and a correction saved during compilation makes that
  compile stale. The three gate tests fail with the gates removed.
- **Reconciliation:**
  - Withdraw and restore confirmation.
  - Remove the contradicted material.
  - Retype the material and the item in one save.
  - Refuse a new contradiction during an active build.
- **Web:** legacy, no-objects and partial notices; SAM whole-photo and
  reference filtering; truncation messages.

## Live acceptance

### Integrated version (head 34b3017)

- **Setup:** authorization recorded first in each ledger; same three
  synthetic images. Part A ran the API routes in process with cards built by
  the web client's own rules (at most 3 Spark + 1 SAM). Part B used the real
  web app in the built-in browser against the guarded local API (at most
  1 Spark + 1 SAM). 8,192 cap, low effort required, no retries, fixed end
  times, reserved before dispatch. Report:
  `output/claude-live-intake-integrated-20261104/REPORT.txt`.

| Image              | Result                                                                                   |
| ------------------ | ---------------------------------------------------------------------------------------- |
| Cardboard          | `recognition=items`, `corrugated_cardboard`, a group with no count; card linked to a sheet |
| Plastic bottle     | `plastic_bottle`; card says build rules are not available, no stock                      |
| Notched sheet      | `corrugated_cardboard` with three alternatives; card linked                              |
| SAM, notched sheet | 0 boxes in both parts                                                                    |

- **Visible fallback (Part B):** the card said SAM returned no region and kept
  the photo, reference and material. **Suggest an outline** drew a box around
  the sheet only, with "Check this suggested box". After that visible check,
  **Measure from photo** showed "Fits within 280 × 190 mm (not all usable)"
  and the irregular-shape notice. The reference lines (150 / 100 mm) are the
  synthetic card's sizes by construction, not ruler readings.
- **Usage:** 4 Spark calls, all `stop`: 15,921 input and 2,668 output tokens,
  2,204 of them reasoning. Part A alone used 11,739 + 1,888, against
  11,739 + 3,863 at default effort on cf315d3. 2 SAM images with zero token
  counts, which does not prove a zero charge. No dollar charge was reported;
  no unknown outcome or retry.
- **Observed gap, since fixed:** without the reference lines, "Suggest an
  outline" showed its error in the section status area, out of view of the
  button. After merging main's calibration guidance (#192), it opens and
  scrolls to the reference fields instead, as measuring does.

### Earlier run (head cf315d3, before the merge)

Same images, in process only: the same identities, 0 SAM boxes, the same
fallback estimate, and 11,739 + 3,863 Spark tokens (3,515 reasoning).

## Not done / limits

- Synthetic images only. This says nothing about real-photo accuracy or
  48-category coverage; `recognition_evaluate` still needs labelled real
  photos.
- The outline suggestion is a colour-edge heuristic for one dominant flat
  piece on a plain surface. Cluttered or low-contrast scenes return no
  suggestion, and the user draws a box.
- Before selecting a SAM box automatically, the client locates the whole
  reference locally; if it cannot, it selects nothing. The estimator's own
  check still blocks a reference outline.
- Why SAM returns no box for this scene is unknown.
- SAM-to-estimator success has not been observed on any image.
- The overlapping `fix/intake-failure-diagnostics` work landed on main as
  #186/#187 and is merged here as one implementation (D071).
