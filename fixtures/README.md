# Synthetic pipeline fixtures

Owner: @ResniDev for domain/compiler cases. Measured inventories and evaluation
evidence remain @olartgabo's lane. These four files contain synthetic software
inputs, not measurements, physical builds, bench tests or G2/G3 evidence.

| File | Scenario | Frozen outcome |
| --- | --- | --- |
| `missing_connector.json` | Tape lost after a completed front join; a same-strategy catalogue alternative does not create tape | Blocked: `stock_exhausted`, `unsupported` |
| `damaged_slot.json` | Torn support after folding/front attachment; replacement needs physical undo | Blocked: two `unsupported` blockers |
| `size_mismatch.json` | Base-depth extension before cutting, then the same kind of change after cutting | Before cut feasible; after cut blocked: `unsupported` |
| `impossible_request.json` | Replace a cut brace from its already consumed sheet, with purchases disallowed | Blocked: `stock_exhausted` |

`damaged_slot` retains the spec's filename; this stand has no slot joint. The
case reports a torn folded/taped support and introduces no slot profile.

The connector-loss case records a current limitation: waste handling requires a
whole current region and cannot account for the declared connector-length loss.
Its unsupported-loss and remaining-length blockers are recorded as returned.
The fixture does not pretend a profile change replenishes missing tape.

Each file has top-level synthetic provenance and an explicit note. Numeric
dimensions, kerf, margins, thicknesses, profile limits and test settings are all
synthetic. User-provenance confirmations simulate history and are explicitly
labelled synthetic in their descriptions. `constraints.allow_purchases` is false.
The dimensioned spare in the damaged-support case is synthetic input stock.

Tests validate nested inputs with the existing `CompilerInput`, `StandParameters`,
`CutProcess` and `ReplannerInput` models. They compile and render the original
stand, replay each recorded history through simulation and ranking, compare exact
frozen status/codes/IDs, and render feasible continuations. Blocker lists preserve
duplicates. Mutation inputs are hypothetical alternative histories/resources or
patches: they demonstrate changed outcomes, not actual undo or restored material.
The default path rejects the same synthetic evidence without explicit opt-in.

The older files under `packages/replanner/tests/cases/` remain generic component
regressions; these root files exercise the stand pipeline. No competing domain
schema or provider call is introduced.

`inventory_A.json` and `inventory_B.json` are intentionally absent pending real
inputs from their owner. Physical evidence needs consent/redaction and links to
[build logs](../data/physical-tests/README.md). Passing these offline checks never
establishes a physical or live-provider result.
