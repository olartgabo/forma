# Issue 58: dedicated devloop preparation

Owner: @ResniDev. Code author: Muse Wonder through the existing guarded route.
Reviewer: independent Codex agent and supervising Codex. Branch:
agent/muse-loop-worktree-fix, stacked on chore/devloop (PR33).

Preparation no longer resets or cleans its path. It verifies canonical location,
repository top level, common Git directory, registered worktree identity and a
clean tracked/untracked state before reuse. Direct worktree/state-directory
symlink and junction aliases, ordinary nested directories and foreign repositories
are rejected. New worktrees start detached at freshly fetched origin/main.
Clean local commits survive reuse. No product schema or shared contract changes.

Validation after Muse's review repair:
- uv run --locked pytest -q: 305 passed, 6 skipped in39.85s, exit0.
- Ruff lint passed; changed Python files formatted with actual Ruff.
- git diff --check passed; only two allowed implementation/test files changed
  before this supervisor-written handoff.
- Four skips need POSIX shell; two file-symlink tests need Windows privilege.
  Both WORKTREE and STATE_DIR directory-junction tests executed successfully.
- Regressions preserve parent/foreign/dirty data and staged/untracked sentinels.

This is a preparation-only fix. Later per-task cleanup and captured sh default
cwd remain separate review limitations; PR33 stays draft and disabled alongside
its accounting, queue and complete-patch-review blockers. Static filesystem
checks are not protection against adversarial concurrent replacement.

Two guarded coding candidates ran. Code-generation usage is development usage,
not live product compatibility or physical recovery evidence. No product live
provider test or physical build ran. No main merge or force push.
Next: review this stacked slice, then finish remaining PR33 boundaries before
launching the original Spark runner. The separately guarded supervised Muse
route continues original product work within its unchanged lifetime cap/expiry.
