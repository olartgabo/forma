# PR 133 persisted preview compatibility

The required `PanelDiff.changed_from` field previously prevented approval of
saved previews and validation of same-key simulation replay receipts written
before the field existed. Legacy records now reconstruct their complete diff
before Pydantic validation. The response contract remains unchanged; generated
contracts need no regeneration.

Reconstruction loads the scoped immutable base plan and the saved preview plan,
uses their saved process/profile context to recover canonical renderer step keys,
and compares the saved manual hashes. It requires the rendered operation sequence
to match each saved manual and returns a 409 blocker if reconstruction is
unavailable. It never guesses panel pairs from their positions or replaces the
saved SVGs. Existing records and retry receipts remain unchanged.

Regression coverage removes `changed_from` from both SQLite storage boundaries,
approves the old saved preview, then replays the original simulation key after
activation. Both replacement-before-join and attached-brace continuation cases
must return the original result with shifted panels paired to their old indices.

Verification: merged `origin/main` before checking. `uv sync --locked` and
`npm ci` exited 0 (`found 0 vulnerabilities`). Focused API regression run:
`11 passed in 6.19s`. Full `npm run check` exited 0: format, Ruff, generated-contract freshness,
web TypeScript, browser helper tests, offline pytest, guarded devloop and build.
Pytest: `1104 passed, 4 skipped in 70.77s (0:01:10)`; the four skips require a
POSIX shell. Guarded devloop: `# tests 18`, `# pass 18`, `# fail 0`.
Next.js: `Compiled successfully in 1453ms`; static generation completed (4/4).
The complete local output is retained at `%TEMP%/forma-pr133-check.log`.
Self-review checked project scope, receipt immutability, saved-hash fidelity,
stale approval checks and generated-contract boundaries; no remaining finding.
No live provider calls or physical tests ran. Independent review and authorized
publication remain the next actions.
