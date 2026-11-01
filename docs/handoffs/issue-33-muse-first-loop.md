# Issue 33: Muse-first guarded feature loop

Owner: @ResniDev. Branch: chore/devloop. Existing draft PR33 is reused.

The guarded Node entry point starts a fresh Muse/OpenCode session from one bounded
JSON task packet. Muse owns production edits, test writing, offline checks and
ordinary repairs. Task paths include tests, reject shell metacharacters and linked
escapes, and are applied as finite permissions. Offline checks use exact command
keys; the Node test glob lives inside the checked-in npm script. Formatter scope
contains only the validated task files. Native compaction/pruning use the same
metered guarded provider. Codex/Claude plan, final-review or diagnose a stuck task;
Claude calls are fresh/bounded, Codex compacts at its native model threshold.

Credentials, guard settings, journals and installed executables stay outside Git.
The launcher checks the existing shared cap/remaining reservation, pending usage,
STOP and expiry, and never renews or resets them. It validates the exact clean,
registered FORMA checkout/branch and performs no reset/clean. The legacy Python
entry point is blocked before provider or cleanup work; its historical defects
are not represented as repaired. No autonomous queue or merging was enabled.

Live supervised verification: Muse wrote the complete read-only review-packet
helper and its Node tests, ran the checks, and fixed one failed test run. The
helper includes new/untracked file contents, validates all changed paths before
reading content, rejects linked/secret/binary/oversized inputs and leaves Git
state unchanged. An independent final review found a shell-metacharacter issue
in formatter paths; Muse fixed it and added regression coverage.

Verification: full npm run check passed (299 offline Python tests, 6 platform
skips, 15 initial Node tests, types/build/lint/format/contracts). After the narrow
path fix Muse ran 17 Node tests and 299 Python tests/6 skips plus lint, formatting
and contracts successfully; parent reran the actual npm test:devloop entry point.
No live product-provider test or physical evidence gate is implied. Two guarded
coding tasks are evidence that the development workflow runs, not product proof.

Final publication uses ordinary fast-forward pushes to the existing draft PR.
Remaining legacy queue/accounting/worktree cleanup work stays disabled; the active
supervised path does not depend on those functions. No force push or main merge.


The first Ubuntu CI run passed all 305 Python tests and found a test-fixture
portability error: Git cannot stage a child through a Linux symlink. Muse changed
only the fixture to stage the link parent and explicitly allow both platform
status paths before the same rejection assertion. Windows Node suite17/17 and
format checks passed with no skips; independent narrow review approved the fix.
The follow-up GitHub run is the Linux verification for that correction.
