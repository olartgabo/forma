# Issue #7: tools and build requirements

Owner: @olartgabo. Branch: `issue/7-tools-constraints`.

## Contract handoff before implementation

Extend the API-owned inventory confirmation envelope rather than changing domain
or proposal-service contracts. `BuildRequirements` contains `tools` (at most 32
distinct, trimmed names of at most 80 characters), nullable `device_description`
and the existing domain `Constraints`. `Project.requirements` defaults to null
for saved projects. `InventoryUpdate.requirements` is optional: omission preserves
the saved requirements; an explicit null clears them. Inventory and requirements
share the existing optimistic revision and idempotent transaction.

Tool names are unique case-insensitively. Known mass/footprint values must be positive and confirmed; a known support angle
must be greater than zero and less than 90 degrees and confirmed. Unknown values
remain null with unknown provenance. Evidence references and nonempty profile IDs
are rejected until trusted evidence/catalogue integration exists. Tool names are
user-reported availability, never permission to execute an operation. This slice
does not change compiler/provider contracts or authorize cutting.

The browser edits requirements inside the inventory form and sends both in one
immutable retry payload. API Pydantic records generate the browser types. Existing
inventory clients can omit requirements without erasing them. Provider integration
can later read `project.requirements.constraints` when building a trusted snapshot;
it still needs reviewed process/profile inputs and consent before photo transfer.

## Validation and remaining work

Implemented in API project records/exporter and browser inventory form. Existing
projects load without a migration because the new field defaults to null. The
retry digest preserves legacy nested Stock defaults and distinguishes omitted
requirements from explicit null. Both HTML item-ID patterns now escape their
hyphen for the browser's Unicode-set regex parser.

Independent API/React review found no blocking regression. The review included
project ownership, stale writes, immutable retry payloads, deletion receipts,
rollback and generated-schema reuse. The MCPJam review-lessons checklist was
applied to the diff. No provider/compiler/domain implementation changed.

Actual root `npm run check` exited 0. Output excerpts:

```text
All matched files use Prettier code style!
78 files already formatted
All checks passed!
Generated contracts are current
Generated API contracts are current
# tests 10
# pass 10
# fail 0
============================= 269 passed in 6.13s =============================
✓ Generating static pages using 5 workers (4/4) in 487ms
```

The command also completed Next route generation, strict TypeScript and the
production build. The client checks emitted existing Node module-type and
experimental MockTimers warnings.

Browser checks used an isolated SQLite directory, a synthetic owner credential
and explicitly synthetic device data. Confirmed mass/source/tools restored after
refresh; blank angle/footprint fields stayed unknown. Editing a number or source
cleared confirmation, and an unconfirmed mass blocked saving. A second-session
update produced the stale-save panel; reload restored its tools. Dropping a save
response after commit locked editing until retry; the retry sent identical bytes
and returned `replayed: true`. Inspected desktop/mobile requirements screenshots;
the 390-pixel viewport had no horizontal overflow. Browser pattern probes rejected
spaces and accepted a valid hyphenated stock ID.

Design generation, hosted sign-in, manual/event storage, consented provider
transfer and physical evidence remain open. Next implement trusted compiled-plan
storage/activation in #6 before recording physical work in #11; never trust a
browser-supplied plan's `validated` status. Model snapshot integration can consume
saved requirements but still needs trusted profile/process data and consent.
