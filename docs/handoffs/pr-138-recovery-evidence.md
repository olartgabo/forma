# PR #138 recovery evidence repair

The evaluation report counted every passed disruption-labelled FORMA attempt as
a recovery, even when Proof recorded neither a failure nor an approved revision.
The recovery numerator now requires `ProofFacts.recovered` for FORMA. Baselines
retain their observer-recorded disruption and outcome labels.

No API or domain contract changes. Completion counts stay separate from recovery.
Regression coverage includes passed initial builds, recorded failures without a
revision, successful recorded recovery, and all three baseline methods. The CLI
regression reads an exported initial-build software history and reports zero
recoveries despite its disruption label.

Focused check: `uv run --locked pytest packages/eval/tests -q` returned
`11 passed in 1.81s`. Full repository checks and independent review are required
after integrating the repaired parent PRs. All test histories are synthetic;
no physical build, failure or recovery is claimed.
