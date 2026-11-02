# Issue 57: devloop context and destination paths

Owner: @ResniDev. Independent reviewer: Codex supervisor. Branch: chore/devloop.
Related: #57 and draft PR #33.

Exact-file scope entries now match exactly. Reads and writes reject Windows
absolute/drive/UNC/alternate-stream/device paths, traversal, credential artifacts,
generated/lock files and filesystem aliases. All requested context paths validate
before any file opens. Context is complete UTF-8, bounded to 60,000 bytes per file
and 240,000 bytes total; oversized files fail explicitly rather than truncate.
Reads intentionally use the same lane allowlist as writes. Root spec files are
supervisor context, not model-selected context paths. Canonical checks validate
static filesystem state; they are not isolation against concurrent file swaps.

No product schemas or generated contracts changed. On the integrated main tree:
- uv run --locked pytest -q: 297 passed, 6 skipped, exit 0.
- Tooling subset: 51 passed, 6 skipped. Four skips require POSIX shell; two
  require file-symlink privileges. A real Windows directory-junction escape test ran.
- Ruff lint/format and git diff --check passed.

No live provider or physical test ran. The runner remains disabled: durable
accounting for every dispatch, registered worktree ownership before cleanup,
checkout-independent self-exclusion and complete review/staging remain open.
D013 records the user's Codex coding fallback and Muse preference.
Next: repair those remaining boundaries and verify before launching the runner.
