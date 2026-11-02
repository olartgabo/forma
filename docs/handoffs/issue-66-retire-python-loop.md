# Issue66: retire the disabled Python engine

The guarded Node launcher is now the only active development path. The Python
compatibility entry point is import-safe and exits nonzero for every invocation,
including old/help/unknown flags, before any work. Deleted only the unused
budget.py, muse.py, scope.py and their exclusive test_scope.py. Git history keeps
the source; no runtime ledger/state/worktree or external guard file was touched.

Muse authored the tombstone, retained regression tests and clearer README/policy.
The supervisor applied its explicit four tracked-file deletions using a source
patch because the worker could not execute file-removal commands. Judge schema,
usage-limit, fresh/bounded/native-compaction and attribution cases remain; active
Node sources/tests/scripts are unchanged. Final policy review restored the two
review-repair limit and distinguishes Meta accounting from native subscriptions.

Actual full npm run check passed:266 Python tests,4 Windows/POSIX skips,17 Node
tests,formatting,lint,contracts,TypeScript and production build. The Python count
is lower because retired implementation coverage was removed; product coverage
and active Node checks remain. Independent final review approved the source and
policy correction. No provider-product or physical acceptance is claimed.

Updates existing PR33; refs66. Legacy worktree-cleanup PR59 is superseded by
retirement rather than reviving destructive cleanup in the active workflow.
