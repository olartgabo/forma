# Evaluation harness

Owner: @olartgabo. Reviewer: @ResniDev. Issue: #15. Status: not implemented.

Run deterministic fixture checks by default; opt into live provider/physical
experiments explicitly. Consume domain/compiler/replanner/renderer outputs.
Keep baseline conditions comparable and preserve actual failures.

First deliverable: the two-inventory/three-perturbation matrix and impossible
case with result categories, numerator/denominator metrics and a reproducible
offline command. Connect actual build logs separately. Never call six fixture
passes six successful builds. See [evaluation protocol](../../docs/evaluation-protocol.md).
