# Replanner

Owner: @ResniDev. Reviewer: @olartgabo. Issue: #10. Status: not implemented.

Consume domain snapshots, physical events, remaining stock and typed patches.
Use the offline compiler to validate copies before ranking feasible repairs.
Return kept/undo/redo, lost material, new stock, invalidated checks, cost terms
and concrete blockers. API services own persistence and approval.

Preservation requires compatible geometry, interfaces, dependencies and evidence.
Incompatible completed cuts require replacement stock or rejection. Consumed
material never returns without a real salvage transaction. Changed dependencies
invalidate downstream checks; replacements remain incomplete.

First deliverable: minimal Oct 31 repair simulation, followed by Nov 1 coverage
for irreversible loss, dependent rechecks and preserved unaffected work.
See [revision architecture](../../docs/architecture.md).
