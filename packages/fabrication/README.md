# Fabrication

Owner: @olartgabo. Reviewer: @ResniDev. Issue: #150. Status: offline report
implemented; modeled access only, no physical observation.

`fabrication_report(data: FabricationInput, *, process: CutProcess,
allow_synthetic=False) -> FabricationReport` is pure, offline and
deterministic. It says which planned operation can be attempted next, why each
other remaining operation is waiting or blocked, which tool and access
assumptions the builder must confirm, and one supported order for the rest. It
never completes a step, authorizes cutting, records an event or changes stock.
Contracts live in `forma_domain.fabrication_contracts`.

## Inputs

- `lineage`: every plan version from the root to the one being scheduled, each
  with its events and evidence in ingestion order, plus the approved revision
  boundary (`carried_operation_ids`, `base_last_event_id`).
- `remaining_stock`: the API's existing expected-stock ledger for that version.
- `declared_tools`: saved tool names plus explicit scoped availability declarations,
  or `None` if availability is unknown. Tool gaps block readiness.
- `context_blockers`: server-side gates such as unreviewed profile evidence.
- `profile_evidence`: original saved profile records, scoped to the project;
  catalogue records may have independent version IDs.

The report reruns `forma_compiler.validate_plan` on the scheduled plan and
passes its blockers through unchanged. It additionally checks the current
remaining-stock projection against actual history: known source identities and region geometry, confirmed offcut creation,
consumed parents and connector use. It does not reimplement plan geometry checks.

## Replay

History is replayed in the order it was reported. Joint attach and detach come
from each confirmed operation's own effects, so a carried attach followed by a
confirmed peel leaves that joint detached even though both operations are
complete. At each revision boundary the carried work must already be confirmed,
unchanged since confirmation and approved against the base version's last
event. Damaged parts stay damaged across versions; an approved revision clears
the base version's failed checks. Out-of-order, duplicate, foreign or
contradictory reports make the report `history_conflict` and block every step.

## Declared rules (`fabrication-rules-v1`)

- The tabletop family records `cut_rect`, `fold`, `tape_joint`, `detach`,
  `inspect` and `functional_test`; other operation types are unsupported.
- A part held by an attached joint cannot be marked, slotted or folded until an
  explicit detach frees it. A join waits for pending preparation on its parts
  unless an explicit join → detach → preparation dependency path releases them.
- A join whose access is not confirmed is blocked.
- Tool classes per operation match declared available tool names by whole words.
  A gap blocks readiness until the builder supplies actual tool names.
- Unknown or unconfirmed current connector lengths block pending joins. Only
  known numeric, calculated, unconfirmed balances appear in
  `required_connector_measurement_ids` for a fresh per-report measurement.
  Unknown or other unconfirmed starting balances require inventory confirmation
  before plan approval or material-history reconciliation; a report cannot
  establish original resources. A confirmed starting balance may be spent
  hypothetically while constructing the supported order.

The supported order is a deterministic topological order over dependencies,
required joints, detach producers and the access rule, tie-broken by manual
order among feasible operations. Blocked eligible steps are reconsidered after
each transition; an independent ready step remains visible. Dependencies that
contradict the access rule are reported as a cycle.
Execution-state IDs hash the plan with the completed, attached, damaged and
failed sets. `snapshot.inputs_sha256` binds the complete typed input, cutting
process and synthetic-evidence opt-in, including profile evidence and gates.

Access is modeled from declared rules (`access_basis`), never observed
(`observed_usability: not_assessed`).
