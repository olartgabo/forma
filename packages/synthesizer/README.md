# Synthesizer

Owner: @ResniDev. Reviewer: @olartgabo. Issue: #148. Offline; proposals only.

`search(SearchInput, SearchBudget) -> SynthesisResult` proposes at most two
designs of the one supported stand family (three-panel triangular tape stand with
a folded lip) from the owner's saved stock. `probe(...)` changes one allowlisted
dimension of a design and re-evaluates it. Records live in
`forma_domain.synthesis_contracts`. No provider, HTTP, storage or UI.

## Domains

For each saved sheet with exactly one usable region, three finite grids in mm:

| Parameter            | Lower bound                                 | Upper bound                                          |
| -------------------- | ------------------------------------------- | ---------------------------------------------------- |
| `part_width_mm`      | confirmed device width                      | min(region width − 2 margins, max footprint width)   |
| `support_length_mm`  | confirmed device contact height             | region height − 2 margins − lip                      |
| `footprint_depth_mm` | reach of the shortest support + 5 mm        | max footprint depth                                  |

Bounds snap to a 5 mm grid; at most five values per grid (the step widens in
5 mm multiples). An empty grid names the limiting stock or requirement. The
support angle is the confirmed requirement and the lip comes from the confirmed
stand parameters; neither is searched. Unknown stock dimensions are never
assumed: the result is `needs_input`.

## Search

Order: sheet, tape, tape/fold profile pair (all by ID), then width, support and
depth ascending. Each node is one `compile_stand` call (which runs the
independent `validate_plan`). `max_nodes` (deterministic) and `max_seconds`
bound it. Outcomes: `candidates_found` (possibly with `exhausted` set),
`search_exhausted` (no acceptable design before the budget ran out),
`infeasible` (every grid point evaluated, none accepted), `needs_input`, and
`active_build` (fresh designs never replace an active build).

Accepted designs are ranked by consumed sheet region area, then panel area, then
their values. The second proposal prefers another sheet, then another base depth.
At most eight finalists are fully evaluated.

## Candidate report

`evaluate` recompiles the design, re-renders the manual (`render_manual`),
projects shared canonical geometry (`project_nominal_geometry`) and schedules
it with the published `fabrication_report`. It returns canonical named pieces
(`piece_reference`), the derived brace and its formula, material use (whole
region consumed; unallocated area is waste), construction steps, the cut-layout
SVG and a check matrix:

- `compiler`, `canonical-geometry`: modeled pass or failure.
- `fabrication-order`: pass, failure (plan-level compiler blockers or an order
  cycle) or missing input (e.g. undeclared tools).
- `fabrication-access`: always `unverified`; observed usability is not assessed.
- `stability-tip-{portrait,landscape}`: `missing_input`, or
  `evidence_incompatible` when saved measurements exist for another geometry.
- `retention-*`, `joint-strength`: `unsupported`.

A modeled failure makes the report `rejected`; rejected reports are never
proposed. Identical inputs give identical results: the search ID hashes every
input revision and the budget, and candidates compile with a fixed timestamp.

## Probe

`probe(data, budget, design, parameter, value)` requires every design value to
lie in the server's grids and the lip, angle, stock and profiles to match saved
records. It evaluates the changed design and lists the pieces whose dimensions
changed (a base-depth change regenerates the base and the brace).
