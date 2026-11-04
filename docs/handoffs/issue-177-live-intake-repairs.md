# Issue #177 follow-up: live intake repairs

Branch `issue/live-intake-repairs`. Decision D067. Follows the material
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
2. **Failure diagnostics** (`model_gateway.py`, `provider_diagnostics.py`).
   - Each trace keeps the provider finish reason (sanitised to
     `[a-z_]{1,32}`, otherwise `unrecognized`) and reported reasoning tokens.
   - Intake errors carry `diagnostics` (model, elapsed, finish reason, usage),
     never provider text.
   - A truncated answer is `incomplete_output`, and the web says it "ran out
     of room".
   - The fresh answer is bounded: 12 items, 80-character evidence and three
     short questions. Its largest valid form is under half of the fixed
     4096-token completion cap.
   - Intake still makes one attempt with no retries (#185).
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
   `plans.py`).
   - A saved item that contradicts its linked material sets
     `inventory_confirmed=false` and records a hold. Every design and
     fabrication path already checks confirmation, and plan activation now
     does too.
   - The material card shows a blocking panel with **Remove this material**,
     or the option to retype the item or the material.
   - Restoring confirmation happens only by resolving a hold. Inventory saves
     stay unconfirmed while a contradiction remains.
   - A new contradiction is refused during an active build.

## Offline regressions

- **Intake:** label-only replies from live runs 1 and 2, the run-3
  truncation (finish reason and usage kept, one call), `no_objects`,
  `partial`/`uncertain`/group answers, and the bound on answer size.
- **Gateway:** traces keep the finish reason and reasoning tokens, and
  unrecognised reasons are sanitised.
- **Photo measurement:** the suggestion finds the sheet and not the card, the
  notched sheet stays `enclosing_only`, a reference-only or cut-off scene
  gets no suggestion, a box around the card is refused, and the route test.
- **Reconciliation:**
  - Withdraw and restore confirmation.
  - Remove the contradicted material.
  - Retype the material and the item in one save.
  - Refuse a new contradiction during an active build.
- **Web:** legacy, no-objects and partial notices; SAM whole-photo and
  reference filtering; truncation messages.

## Live acceptance

- **Setup:**
  - Bounded run on head cf315d3 with the same three synthetic images.
  - Ran through the API routes in process, with item cards built by the web
    client's own rules in Node. Not a browser run.
  - Report: `output/claude-live-intake-repair-20261104/REPORT.txt`, ledger
    alongside it.
- **Limits:** authorization recorded first; at most 3 Spark calls and 1 SAM
  call, no retries, fixed end time, reserved before dispatch.

| Image              | Before            | Now                                                                                     |
| ------------------ | ----------------- | --------------------------------------------------------------------------------------- |
| Cardboard          | `items=[]`        | 1 item, `corrugated_cardboard`, a group with no count; card linked to a cardboard sheet |
| Plastic bottle     | truncated at 2048 | 1 item, `plastic_bottle`; card says build rules are not available, no stock             |
| Notched sheet      | `items=[]`        | 1 item, `corrugated_cardboard` with three alternatives; card linked                     |
| SAM, notched sheet | 0 boxes           | 0 boxes again (concept "Corrugated cardboard")                                          |

- **Calls:** all four finished normally; no unknown outcome and no retry.
- **Spark usage:** 11739 input and 3863 output tokens, 3515 of them reasoning
  (earlier: 11367 + 5514 with one truncation). No dollar charge was reported.
- **SAM:** 1 image processed with zero token counts, which does not prove a
  zero charge.
- **Region to estimator (fallback):** SAM found nothing, so the local outline
  suggestion supplied the region. The estimator returned `enclosing_only`
  280.0 x 190.0 mm (truth 280 x 190) and kept `irregular_outline`. This is the
  suggested-region fallback, **not automatic localization**. Why SAM returns
  no box for this scene is still unknown.

## Not done / limits

- Synthetic images only. This says nothing about real-photo accuracy or
  48-category coverage; `recognition_evaluate` still needs labelled real
  photos.
- The outline suggestion is a colour-edge heuristic for one dominant flat
  piece on a plain surface. Cluttered or low-contrast scenes return no
  suggestion, and the user draws a box.
- The reference corners for the client-side SAM filter are known only for a
  drawn rectangle or after an earlier estimate of the same photo. The
  estimator's own check still blocks a reference outline.
- SAM-to-estimator success has not been observed on any image.
- **Active builds:** a contradiction saved before this change in a project
  with an active build is held at startup, and confirmation is withdrawn.
  New contradictions are refused during a build. Repair search, repair
  commit and fabrication reports for that active build do not yet check
  confirmation (they check plan version and events), so they are not
  blocked. Gating them belongs to the repair and fabrication engines
  (@olartgabo); found in the final review.
- An uncommitted `fix/intake-failure-diagnostics` branch in another worktree
  overlaps the failure diagnostics here (it adds validation-issue paths and
  is D066 there). The two need one canonical implementation when both land.
