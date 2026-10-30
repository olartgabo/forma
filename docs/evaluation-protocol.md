# Evaluation protocol

Status: **no cases executed or physical results recorded**.
Owner: @olartgabo; @ResniDev reviews compiler/repair claims. Issues: #13 and #15.
Source: formspec.md section 14.

## Before a build

Confirm inventory dimensions and provenance, tools, tested material/joint
profile, actual device/mass, angle, surface, duration and repeated-use test.
Choose some supported disruptions after implementation to avoid tuning all
repair paths to known examples. Never create an unsafe physical test to fill
the matrix. Use [BUILD-LOG.md](../data/physical-tests/BUILD-LOG.md).

## Matrix

| Case                       | Inventory A                       | Inventory B   |
| -------------------------- | --------------------------------- | ------------- |
| Missing connector          | Not attempted                     | Not attempted |
| Dimension mismatch         | Not attempted                     | Not attempted |
| Damaged joint              | Not attempted                     | Not attempted |
| Explicitly infeasible case | Not attempted; one total required | Not attempted |

Label every result as fixture-only, compiler-validated, bench-tested,
physically attempted or physically passed. Record the blocker and failure
count. Target two distinct completed physical objects and one unexpected
successful recovery; fixtures never stand in for those builds.

## Comparisons and reporting

Compare FORMA with single-prompt LLM instructions, iterative vision chat and a
fixed tested parametric template. Keep inventory, disclosed information, model
access, measurement conditions and attempt count comparable; document limits.
Target three observed users and one non-team builder where available, and
report actual counts and consent rather than assuming recruitment succeeded.

Report numerator/denominator for completion, recovery, valid patch and
preservation rates. Record invalid stock uses, incorrect preservations,
failure-to-recovery elapsed time, waste area, human instruction corrections,
questions and actual model latency/usage. Judge preservation compatibility
using compiler output plus human physical inspection. Explain zero-denominator
cases instead of inventing a rate.

No result table may contain illustrative numbers presented as observations.
Keep current [submission gates](submission.md) unchecked until evidence exists.
