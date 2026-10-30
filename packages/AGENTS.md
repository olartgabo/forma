# Offline package rules

The root [AGENTS.md](../AGENTS.md) applies. Read each package README before edits.

`domain`, `compiler`, `replanner` and `renderer` must run with fixture inputs
without HTTP, database, provider credentials or UI imports. Validation produces
typed results and actionable blockers; never mutate the user's physical history.

`eval` may opt into live model/physical adapters explicitly. Keep its default
checks offline and distinguish synthetic results from actual physical evidence.

@ResniDev owns domain/compiler/replanner/renderer; @olartgabo owns evaluation.
Generate downstream contracts from domain models. Coordinate schema changes
before editing consumers and never hand-edit generated output.
