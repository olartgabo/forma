# Physical joint profiles

Status: **no profiles physically verified**. Validation owner: @olartgabo;
compiler owner: @ResniDev. Issues: #2 and #5.

The first family is a small reused-sheet tabletop stand. Candidate strategies
from the spec are tab/slot, folded brace and tape/lash. They are experimental
ideas until the measured bench tests support them. Three physically tested
joint/repair strategies are the P0 target across the demo set.

## Profile record

For each actual profile record:

- Stable profile ID, status, test date, operator and evidence IDs.
- Material source, condition, thickness range, tool and measurement method.
- Geometry, orientation, feature access, minimum margins and kerf.
- Measured tab/slot fit or connector requirements and tolerated error.
- Reversibility, observed destructive removal and consumed connector length.
- Defined device/load and test procedure, actual outcomes and failure limits.
- Which inventory/build exercised it and which unknowns remain.

Never fill an unmeasured tolerance or working load with an assumed safe default.
Only promote a profile after reviewing evidence. Copy redacted observations
into [data/physical-tests](../data/physical-tests/README.md), retaining provenance.
Synthetic geometry fixtures must remain labeled synthetic.
