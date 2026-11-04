# Construction stage recovery

The construction integration retains PR #197's approximate photo flow and
PR #200's safe unknown-outcome receipts. Approximate requests pass the same
request-local budget through the route and generator, with a one-round cap.
The construction-only gateway uses a shared 120-second deadline, low reasoning,
and no automatic HTTP retry. Detailed generation allows at most two calls
(initial proposal and one correction); approximate generation allows one.
The common design gateway, credentials and runtime STOPs are unchanged.

## Reproduced failures and behavior

An otherwise valid panel wider than the saved sheet produces hypothetical
construction steps and an allocation blocker. Previously, a malformed, refused
or truncated correction discarded that first checked result. The runtime now
retains its geometry and fabrication blockers, records a visible correction
failure message, and retains provider-reported usage for both responses. It does
not promote the original candidate to fabrication approval.

If deterministic evaluation uses the remaining request time before a correction
starts, the runtime returns the first checked candidate and an explicit message
that no correction was sent. This avoids misclassifying a local, pre-dispatch
deadline as a new unknown provider outcome. A timeout, network error or budget
error raised by a correction still propagates to the existing unknown-receipt
gate; no retry key is changed and no uncertain receipt is cleared.

Missing reviewed joint profiles previously prevented even the generation of
geometrically valid assembly stages. Geometry now passes through the canonical
construction engine independently of fabrication prerequisites. The candidate
keeps the missing material/profile/process blockers and cannot gain a fabrication
plan from those missing records. Missing profiles alone do not trigger another
model call. Piece geometry, naming and relationships remain model proposals;
this code contains no preset replacement design or invented physical evidence.

## Read-only receipt inspection

Authenticated GET `/api/projects/{project_id}/construction/receipts` checks
project ownership and returns at most 16 newest construction receipt identities
(key and digest), pending/unknown/completed state, and an allowlisted error code.
It opens SQLite in read-only mode and constructs no gateway or material context.
Legacy unknown receipts are inspected without rewriting them. Raw responses,
proposals, exception text and arbitrary diagnostic fields are omitted. A corrupt
response remains unknown. This endpoint neither reconciles provider billing nor
releases a blocked request.

## Verification and limitations

- Focused construction runtime and route tests: 68 passed in 22.63 seconds.
- Ruff check and formatting passed for the four construction source/test files.
- Tests use deterministic fake transports; no provider calls or physical tests ran.
- Two additional offline replays used the privately saved deployed project
  snapshot (three stocks), missing process/profile context and fake responses.
  Neither raised before dispatch to the fake transport. Questions-only returned
  no candidates; hypothetical joined panels returned four construction stages
  with fabrication blocked and no fabrication plan. Each used one fake call.
  Private goal, notes, stock identities and photo references are not published.
- Shared API contract regeneration is owned by the concurrent assembly-view lane.
- Fake-clock regression proves that a first response taking 70 seconds leaves
  only 50 seconds for the correction. Fake transports verify that timeout,
  network errors and retryable HTTP errors cause no automatic retry.
- The previous construction path used a 20-second transport timeout inside a
  60-second request budget. The bounded deadline improvement does not prove
  the cause of the historical approximately 60-second failure.
- The original unknown provider outcome remains unresolved. Safe receipt
  metadata helps future diagnosis; it does not recover missing historical usage.
