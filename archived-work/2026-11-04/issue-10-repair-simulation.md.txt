# Issue #10 repair simulation handoff

Status: in review

- Issue and acceptance criteria: Issue #10, following #8. PR #32 is stacked on PR #30 (`agent/muse-unused-stock`); neither PR is merged.
- Owner and reviewer: Owner @ResniDev; reviewer @olartgabo because the change affects the compiler.
- Branch and commit: PR #32 stacked on `agent/muse-unused-stock` (PR #30); exact commit recorded in the PR.
- Changed files and module boundary: `packages/replanner/src/forma_replanner/simulation.py` and `packages/compiler/src/forma_compiler/validation.py` plus their tests; replanner/compiler only, no domain/API/web/persistence edits.
- Implemented behavior: A source outside `_touched_stock_ids` (not referenced by parts, operations, material transactions or replacement patches) is preserved only if it equals its original record. Any difference fails with `needs_confirmation`. Touched sources keep the kind/material/dimension/usable-condition gates and the confirmed connector-length gates. Region reconciliation and duplicate detection still run for all stock. Unknown material is never promoted or fabricated. Touched is `packages/replanner/src/forma_replanner/simulation.py:81-93`; untouched rule and comment block is `packages/replanner/src/forma_replanner/simulation.py:548-560`; unused-stock validation is `packages/compiler/src/forma_compiler/validation.py:138-181`. Regression tests: `test_future_resize_with_identical_unused_unknown_sheet`, `test_future_resize_with_identical_unused_unknown_connector`, `test_unused_unknown_stock_with_unchanged_region_is_retained`, `test_unknown_source_referenced_by_replacement_patch_still_blocks`, `test_changed_unused_unknown_connector_is_not_treated_as_confirmed`, `test_unused_unknown_stock_does_not_block_and_is_retained`, `test_unused_unknown_stock_overlapping_regions_still_block`, `test_unused_stock_knownwidthoverflow_still_blocks`, `test_unused_stock_knownheightoverflow_still_blocks`, `test_unused_stock_partialknownaxisfits_is_accepted`, `test_unused_measured_sheet_is_accepted`, `test_cut_from_unknown_stock_still_blocks`, `test_joint_with_unknown_tape_still_blocks`.
- Contract/schema changes and generation command: No domain or generated-contract changes were made.
- Checks actually run, exact output and exit status: Check results are recorded in the PR by the loop.
- Live model/physical evidence, or explicitly not attempted: not attempted.
- Pending decisions and blockers: PR #30 must merge before #32 can rebase/merge.
- Next concrete action and receiving owner: Review and merge PR #30 first, then rebase or merge #32; receiving owner @olartgabo for review.
