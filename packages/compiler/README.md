# Assembly compiler

Owner: @ResniDev. Reviewer: @olartgabo. Issue: #5. Status: not implemented.

Pure deterministic validation consumes [domain](../domain/README.md) models,
confirmed stock and tested joint profiles. Return valid plans or concrete
errors/missing facts. Never call a provider, write a database or certify strength.

Validate source-region conservation, non-overlap, orientation, kerf, margins,
connector quantities, references, supported profiles and operation DAG order.
Keep offcut provenance and prohibit double-spending. Unknown critical dimensions
block irreversible work; unsupported/out-of-family plans are rejected.

First deliverable: allocation/operation checks with offline tests for impossible
cuts, oversubscription, reused stock, missing parts and impossible joints.
Physical profile limits must come from [joint tests](../../docs/joint-profiles.md).
