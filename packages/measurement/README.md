# Measurement decisions

Owner: @ResniDev. Reviewer: @olartgabo. Issue: #149. Offline; never confirms a value.

`design_decision(SearchInput, SynthesisResult, declined)` and
`active_decision(ActiveFacts, declined)` return a `MeasurementDecision`
(`forma_domain.measurement_contracts`) with exactly one outcome:

| Outcome | When |
| --- | --- |
| `question` | A confirmed value could change a supported decision. |
| `none_needed` | A built stand has a decisive modeled tipping result for every case. |
| `no_feasible_candidate` | Confirmed stock (or the requirements themselves) rule out every design, and no remaining question could help. |
| `unsupported` | Server design settings are missing (including for a new inventory revision), no reviewed profile pair covers the saved sheet material, the compiler needs an input no stock size can supply, the build state has no supported geometry, or a margin lies inside the recorded resolution (no interval propagation). |
| `physical_test_required` | Designs fit but stability needs a built stand, or the stand is not yet built. |
| `budget_exhausted` | The #148 search ran out of budget; no question is chosen from a partial search. |

## Thresholds come from the compiler

`thresholds(data, material)` finds the smallest grid design that compiles on
unlimited hypothetical stock of that material, then binary-searches (0.1 mm
steps) the smallest sheet width and height at which that design still compiles.
A confirmed value below the rounded threshold is decided by compiling at that
exact value, so rounding never excludes stock. It returns `Blocked` instead
when no reviewed tape/fold pair covers the material (`no_profiles`), when the
compiler refuses unlimited stock for an input reason such as missing profile
evidence (`needs_input`), or when no stock can work (`infeasible`); only the
last becomes `no_feasible_candidate`. The tape needs are the compiler's tape
use for that design and twice the confirmed overlap; the thickness range is the
overlap of each reviewed tape/fold profile pair for the material. The
hypothetical stock is used only to locate thresholds and never becomes a
candidate.

## Selection rule

1. Missing build requirements (device mass, angle, footprint limits).
2. Tape width/length, only when no confirmed tape is usable.
3. Sheets by ID: thickness, width, height, then usable area (only once width
   and height are confirmed).

Skipped: kinds the stand cannot use, sheets of a material with no threshold
(named in the reasons), stock confirmed outside a threshold (its
other values cannot rescue it), values marked unavailable (the whole stock is
skipped), and one material's questions when the other material already blocks
every design. Unconfirmed values are shown as estimates and still asked.
One question is returned; `pending_questions` counts the rest. No
probabilities, effort scores or information-gain claims.

For an active build: unbuilt → `physical_test_required`; reported assembled
without current #146 measurements → one assembled-stand question (all three
named pieces, both cases); complete → per-case margin against the required
margin and a first-order resolution band (support resolution plus the coarsest
centre-of-mass resolution). That band only flags margins a re-measurement
cannot settle; it is not a conservative bound.

`compare(before, after)` lists every changed saved fact (all stocks and
requirements, never truncated), newly unavailable values and new
assembled-stand measurement records, and whether the outcome, search status,
proposals or stability result changed. When only the next question changed, the
explanation names it.
