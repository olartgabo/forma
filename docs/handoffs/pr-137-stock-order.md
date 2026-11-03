# PR 137 stock ordering repair

The progress projection applied completed cuts before recorded waste and salvage.
Recovering an original region and then cutting it could therefore leave the
consumed parent beside its offcuts. Progress now applies local consumption
receipts in ingestion order, while carried completions precede the current
version's reports. The replanner interleaves confirmed physical operations with
material records chronologically and checks the same remaining ledger.

The API regression covers waste followed by a blocked cut, salvage followed by
a successful cut, exact offcut output, offcut waste/recovery, rejected reuse of
the consumed parent and a real replanner replacement attempt. A second regression
checks that project deletion removes the stored material-report retry snapshot
and physical records. Deletion now includes the `:materials` receipt scope.

Changed modules are API progress/persistence and the pure offline replanner.
No domain or generated API schema changed. The PR 136 repair was integrated from
`86a5b01`; the merge retains both the material and multi-part-damage regressions.

Verification:

- `uv sync --locked` and `npm ci`: exit 0.
- `uv run --locked pytest apps/api/tests/test_progress.py packages/replanner/tests apps/api/tests/test_adapt.py -q`: `196 passed in 12.07s`, exit 0 before PR 136 integration and the deletion regression.
- `NEXT_TELEMETRY_DISABLED=1 npm run check`: exit 0 on the integrated tree.
  Formatting, Ruff, generated contracts and web types passed; web tests reported
  `# pass 106`, `# fail 0`; pytest reported `1127 passed, 4 skipped in 56.78s`
  (the four skips require a POSIX shell); devloop reported `# pass 18`,
  `# fail 0`; production build reported `Compiled successfully in 1216ms`.
- `git diff --check`: exit 0.

No live provider calls or physical attempts were made. These are software
regressions and establish no physical pass. Independent review and publication
remain with the coordinating owner.
