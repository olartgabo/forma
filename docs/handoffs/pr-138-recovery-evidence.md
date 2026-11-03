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

Independent review also found nonphysical Proof records contributing to waste,
preservation and recovery timing. Those metrics now use only physical entries,
and timing requires a recorded recovery. Regressions cover each nonphysical
evidence level alone and mixed with a physical attempt, plus unrecovered timing.

Focused check: `uv run --locked pytest packages/eval/tests -q` returned
`18 passed in 1.18s`. After integrating repaired PRs #136 and #137,
`NEXT_TELEMETRY_DISABLED=1 npm run check` exited 0: `1145 passed, 4 skipped in
53.35s`, web `# pass 107`, `# fail 0`, devloop `# pass 18`, `# fail 0`, and
production build `Compiled successfully in 442ms`. The four skips require a
POSIX shell. Full output: `%TEMP%/forma-pr138-final-check.log`.

Independent finding recheck and authorized publication remain next. All test
histories are synthetic; no physical build, failure or recovery is claimed.
