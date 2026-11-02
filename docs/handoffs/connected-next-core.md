# Coordinated connected core lanes

Latest user direction explicitly requests at least three actual Muse workers on
separate core demo priorities. Offline engine/fixture expansion remains paused.
The next three additive lanes own disjoint source and regression-test paths:

1. Input readiness: authenticated GET /api/projects/{id}/designs/readiness,
   DesignReadiness in design_runtime.py. Report current project/revision,
   inventory confirmation, missing_inputs and safe context blockers using existing
   snapshot/missing-input logic. Input completeness is not a valid plan or physical
   pass. Never call a model or mutate state. Own designs route/runtime tests.
2. Saved project discovery: authenticated GET /api/projects with bounded pagination,
   SavedProjectSummary/SavedProjectList in projects.py. Return only owner-scoped
   summaries (ID, goal, revision, confirmation, active version), stable ID ordering
   and next_cursor. No migration, full inventories, media bytes or other owners.
   Own projects.py and its existing tests only.
3. Connected smoke command: demo_smoke.py and test_demo_smoke.py. Default to
   read-only health/project/media checks. Live saved-photo intake requires an
   explicit flag and transfer consent. Owner credential stays out of arguments
   and output; provider key is never read. Report actual diagnostics/usage only,
   stable redacted errors and nonzero failures; no physical pass claims.

Canonical Pydantic records remain the API source. After all three lanes pass,
ONE Muse integration task registers new API records in the generator, regenerates
TypeScript and adds the connected client/UI affordances. Individual lanes must
not edit generate.py, generated contracts, each other's files or teammate branches.
Do not weaken checks for the staged integration; report what's pending honestly.
No compiler/replanner algorithms, synthetic calibration or fake inventory are
part of these tasks. Missing measured stock and calibrated process/profile facts
remain actual prerequisites for accepted manual generation.

## Integration scheduling update

Readiness and saved-project endpoints passed their scoped checks and independent
reviews and are now combined on the owned integration branch. The smoke CLI has
two independent review repairs in progress in its separate lane. Because it uses
existing endpoints and shares no export/UI files, the API export and UI coordinator
can proceed in parallel; final combined checks/publication must still include the
reviewed CLI commit. No incomplete smoke result may be called a live pass.

## Reviewed connected acceptance (November 2 UTC)

All three original Muse lanes completed in separate checkouts, followed by one
Muse API-contract/UI coordinator. Independent scoped reviews approved the APIs,
UI/contracts and the smoke CLI. The CLI review repairs enforce media project
scope and a caller deadline even during blocked connection setup. An OS-blocked
DNS/connect daemon may linger until the OS returns; it checks cancellation before
sending HTTP headers/body and then closes. Caller cleanup grace is 0.2 seconds.

Combined automated checks passed 457 Python tests and 31 client tests, with
canonical contracts, formatting, lint and TypeScript checks. Production build
results are recorded separately with the final publication evidence.

Actual isolated HTTP/browser checks reopened the saved synthetic-photo project
from the owner-scoped list and displayed the saved-input checklist. The checklist
reported unconfirmed inventory and missing stock, requirements, reviewed joint
profiles and measured process parameters without calling a model.

The explicit opt-in smoke command sent the existing consented synthetic photo
through the real application API to muse-spark-1.3: 12,641 ms, one model call,
2,333 input and 1,442 output tokens reported by the provider, five candidate labels
and four questions. The safe server trace matched these counts. These are usage
counts, not a bill. Measurements remained unknown and physical verification was
not checked. No inventory, plan approval or physical progress was fabricated.

To repeat locally, provide an existing owner credential through
FORMA_SMOKE_OWNER_TOKEN or --credential-file and run
`python -m forma_api.demo_smoke --api-origin <origin> --project-id <id> --media-id <id> --timeout 30`.
This is read-only by default. Add both `--live-intake --transfer-consent` only when
authorized to transfer that saved photo and project goal to Muse. Provider keys
remain server-only. The CLI prints redacted structured results, never the owner
credential or photo bytes. Offline feature work remains paused.
