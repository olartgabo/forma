# Issue #177 follow-up: material catalog and identified-item cards

- Issue: [#177](https://github.com/olartgabo/forma/issues/177). Depends on
  [#181](https://github.com/olartgabo/forma/pull/181) (guided photo intake,
  `Stock.name`, photo estimates); this branch is cut from its head and must
  merge after it.
- Owner: @ResniDev (domain catalog, model output contract, prompt text).
  Reviewer: @olartgabo for the shared web and persistence mounts below.
- Branch `issue/material-catalog`. Agent: Claude Code desktop on Opus 5.5 (the
  session could not switch to Sonnet; the user chose to continue on Opus). No
  Meta/Muse/OpenCode coding worker or Meta-backed compaction was used.

## Scope

Bounded as requested: catalog and contracts, then connected suggestion cards,
then the measured-evaluation tooling. The 48 categories are recognition
categories, not newly supported fabrication materials (D061).

| Owned (new)                                                                                                                                                       | Shared mount changed (needs @olartgabo review)                                                                                                                  |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `packages/domain/src/forma_domain/material_catalog.py` and its tests                                                                                              | `apps/api/src/forma_api/proposal_service.py`: `IntakeObservation.items` (optional, default empty)                                                               |
| `apps/api/src/forma_api/recognized_items_runtime.py`, `routes/recognized_items.py`, `recognition_evaluate.py` and tests                                           | `apps/api/src/forma_api/intake_runtime.py`: catalog rules in the trusted system prompt                                                                          |
| `apps/web/src/components/guided-intake/recognized.ts`, `identified-items.tsx`, `apps/web/src/lib/recognized-items.ts`, `apps/web/tests/recognized-items.test.mjs` | `apps/api/src/forma_api/projects.py`: router mount, purge on project delete                                                                                     |
|                                                                                                                                                                   | `apps/api/src/forma_api/generate.py`, `packages/domain/src/forma_domain/generate.py`: register contracts, emit `apps/web/src/lib/generated/material-catalog.ts` |
|                                                                                                                                                                   | `apps/web/src/components/guided-intake/index.tsx`: item cards, Muse items, SAM box choice, one Save                                                             |
|                                                                                                                                                                   | `package.json` (`test:web`), `apps/web/src/app/globals.css`, `apps/api/tests/test_intake_route.py`                                                              |

Unchanged: fabrication rules, compiler, repair search, viewer, photo estimator,
#149 decisions, intake consent, receipts and the bounded gateway.

## Contract

- `CategoryInfo` per category: `id`, `label`, `group`, `form`,
  `material_family` (a family to suggest, never a confirmed composition),
  `composition_unknown`, `support`, and `stock_kind`/`stock_material` only when
  build rules exist. `CAPABILITY_FOR_FORM` maps form to a measurement
  capability.
- `ItemIdentity`: `outcome` `catalog` | `other` | `uncertain`. Only `catalog`
  selects a `category_id`; `other` carries a free `other_label`; `uncertain`
  selects nothing. Up to three distinct `alternatives`, never the selection.
- `ItemProposal` (Muse): identity, `visible_evidence`, approximate normalised
  `box` or null, `visibility` (`full`/`partial`/`unclear`), `instance`
  (`single`/`group_count_unknown`). Extra fields, such as a count, are refused.
- `RecognizedItem` (saved card): stable `id`, editable `name`, identity,
  `identity_source` (`muse_suggestion`/`user`), photo, box and its source
  (`muse_approximate`/`sam`/`user`), visibility, instance, optional `stock_id`
  and `user_fields` (what the user edited).
- `PUT /recognized-items` replaces the list with `expected_revision` and an
  idempotency key (exact retry replays; same key, other body 409; stale
  revision 409). A link is accepted only for a category with build rules and a
  saved stock of the same kind and material. GET reports broken links (photo
  deleted, stock removed or retyped) instead of hiding them.

### Build-rule mapping

| Category                       | Uses existing rules for | Note                                                       |
| ------------------------------ | ----------------------- | ---------------------------------------------------------- |
| Corrugated cardboard           | cardboard sheet         |                                                            |
| Thin packaging card, cardstock | paperboard sheet        | thickness still needs a ruler                              |
| Duct, masking, clear tape      | tape                    | generic tape-joint rules; adhesion of this tape not tested |
| String or twine                | cord                    | generic tie-joint rules; strength not tested               |

Double-sided and electrical tape, paper, wood, plastics, foams, fabrics, glues,
ties, clips, foil, wire and fasteners: identified only.

### Measurement by form

| Form                                 | Categories (examples)                                                           | What a photo may give                            |
| ------------------------------------ | ------------------------------------------------------------------------------- | ------------------------------------------------ |
| Flat sheet                           | cardboard, card, paper, plastic sheet, foil                                     | Planar outline beside the card                   |
| Thick sheet                          | plywood, cork, foam board, EVA foam                                             | Outline only with the card on the same top face  |
| Soft sheet                           | felt, fabric, denim                                                             | Outline as laid; may stretch                     |
| Stick or strip                       | craft sticks, skewers, dowels, straws, hot-glue sticks                          | Visible length and width lying straight and flat |
| Tube, container, block, small part   | paper tube, PVC, bottles, cups, trays, offcuts, foam blocks, caps, clips, bolts | No size from one photo; ruler or more views      |
| Roll, adhesive container, loose cord | tapes, glue, string, wire                                                       | No remaining quantity from a photo               |

This change shows these capabilities on each card. Photo measurement itself
still runs only for supported sheet and strip stock through the #181 estimator;
extending the estimator to unsupported flat items and sticks is not done.

## Behaviour

- "Suggest materials from this photo" (consented, one bounded call) now returns item
  proposals. Each becomes an Identified item card with a stable ID and readable
  name ("Plastic bottle", "Plastic bottle 2"). Two bottles stay two cards; a
  pile stays one card marked "A group (not counted)". Uncertain items are named
  "Unknown item". Items with build rules also get a linked material card; the
  rest stay identified only. Without items, the old label path is unchanged.
- Each card shows: what it is (select of 48 categories in six groups, "Not
  sure", "Something else…"), look-alike alternatives as one-click choices,
  visibility, group/single, the material family with "exact composition
  unknown" where relevant, build-rule support ("Identified; build rules not
  available yet" is a normal result) and what a photo can measure. The
  approximate box is drawn on the photo and labelled by its source.
- Corrections mark `user_fields` and `identity_source: user`. A later Muse
  suggestion never changes an existing card: one that overlaps a card on the
  same photo (IoU ≥ 0.5) is skipped and reported; others are added.
- "Find it in the photo" (SAM) on a linked material picks the SAM box that
  overlaps the item's own box, not the largest, so similar objects do not swap.
- One "Save materials" saves the inventory first, then the item cards; with only
  item changes it saves the cards alone. Changing a card's identity drops a link
  that no longer fits.

## Checks run

Targeted, on this branch: domain catalog tests (15), recognized-item API tests
(4), recognition scoring tests (2), intake route tests (35, including the
catalog case), web item-model tests (6), typecheck and lint. The full check
result on the pushed head is recorded in the PR.

## Connected demo (local, synthetic)

On a local development server with a throwaway credential and a synthetic
rendered photo (no provider call; cards seeded through the API): four cards
rendered (two bottles, one partly hidden with a look-alike alternative, a
cardboard sheet and an uncertain group); correcting bottle 1 to food container
and "Use as a material" on the cardboard, then one Save, stored the inventory
and then the cards; after reload the correction ("You chose what this is") and
the link were kept. Re-identifying the saved cardboard as plastic sheet showed
the warning on the saved material.

## Review

Independent Sol review (Codex CLI, `gpt-6.1-sol`, read-only) of f865e37:
REQUEST_CHANGES, 6 major and 1 minor. Repaired: a correction that unlinks a
generated, unsaved material removes it and flags a saved one; a save whose
answer was lost is retried with the same key before later edits; cards save
after an inventory save only when that save's stock set landed; editing and
Muse suggestions wait for the saved cards to load; Save stays visible while
card changes are pending; proposals in one answer never suppress each other
and each saved card absorbs at most one overlapping proposal; photos without
a prediction reach the scene report. Re-review result is in the PR.

## Recognition evaluation

**Not run. Recognition accuracy is unvalidated.** No labelled real photographs
exist in this checkout, and the live verification window is expired, so no Muse
call was made. Coverage of the 48 categories is not claimed from the enum, the
prompt or the tests.

Procedure:

1. Photograph real items covering every category, with clutter, similar-looking
   pairs (for example cardstock and thin packaging card, felt and fabric scrap,
   wooden dowels and bamboo skewers, PVC pipe and paper tube), partial
   occlusion and objects outside the catalog. Keep photos and manifests out of
   git.
2. Label each visible instance (category or `other`, box, full/partial) in a
   manifest before running any model; put tuning photos in `calibration`.
3. Record proposals for the `evaluation` photos through the consented intake
   route within an authorised live window, and the user's reviewed cards.
4. Run `uv run python -m forma_api.recognition_evaluate manifest.json predictions.json`.
   It reports per-category correct, confident wrong selections (with what they
   were confused with), abstentions, `other` answers, misses, correct answers
   found only in alternatives, spurious and unlocated proposals, groups, user
   corrections, per-scene results, the categories without real instances and
   whether a coverage claim is allowed.
5. Record the report (without photos) here.

## Limits

- Boxes from Muse are approximate and only locate; they never measure.
- Hidden stock, thickness, composition, strength, mass and remaining quantity
  stay unknown.
- No usability claim: no participant testing.
- Not done: photo measurement for unsupported flat items and sticks, multi-view
  sizes, per-category build rules.
