# Development plan

Status: workspace scaffold. Install, dev and offline check commands are in the
[root README](../README.md). Domain contracts are implemented; product flows remain pending.

## Named ownership

The user assigned @ResniDev physical compiler and Meta integration, and
@olartgabo product and validation. This overrides the original A/B split in
formspec.md while preserving its product scope and acceptance criteria.

| Area                                                 | Owner      | Issues            |
| ---------------------------------------------------- | ---------- | ----------------- |
| Workspace and real checks                            | @olartgabo | #1                |
| Physical materials, joint tests and build acceptance | @olartgabo | #2, #13           |
| Domain and generated contracts                       | @ResniDev  | #3                |
| Gateway, live smoke tests, bounded reasoning         | @ResniDev  | #4, #9            |
| Compiler, stand SVG and replanner                    | @ResniDev  | #5, #8, #10       |
| Scoped API, persistence and uploads                  | @olartgabo | #6                |
| Intake, manual, adaptation and proof UI              | @olartgabo | #7, #11, #12, #14 |
| Evaluation, deployment and submission                | @olartgabo | #15, #16          |

Issue numbers refer to the [GitHub tracker](https://github.com/olartgabo/forma/issues/17).
The other engineer reviews each lane's changes. Both participate in real builds.

## Parallel starts

- @olartgabo: choose pinned workspace tooling in #1 and collect actual measured
  materials/photos in #2. Publish real install/dev/check commands with the app scaffold.
- @ResniDev: define the domain/schema handoff in #3; begin provider-access
  investigation for #4 using actual team photos as soon as they are available.
- Agree generated contract paths, error envelopes and operation IDs before
  connecting UI/API/compiler. API provider and persistence ownership share
  `apps/api`; keep provider edits separate from route/storage edits.

## Verification when implementing

1. Run the repository's actual formatter, typecheck, affected unit tests and CI
   commands after issue #1 introduces them. Report exact outputs and limitations.
2. Keep compiler tests offline. Test oversubscription, duplicate source/offcut
   use, impossible cuts/joints, invalid operation order and missing measurements.
3. Test preservation/undo, consumed stock across versions, stale evidence,
   optimistic concurrency and idempotent retries.
4. Review project scope/auth, upload decoding/limits, secret redaction,
   provider deadlines and safe error states before pushing.
5. Live model checks and physical tests are separate evidence. Record which
   checks actually ran and never turn unattempted fields into passes.

## Gates

| Target from spec | Required evidence                                                               | Owner                             |
| ---------------- | ------------------------------------------------------------------------------- | --------------------------------- |
| Oct 30: G0       | Real Spark structured image/tool call; useful SAM result or documented fallback | @ResniDev                         |
| Oct 31: G1       | Known impossible stock/geometry cases rejected offline                          | @ResniDev                         |
| Oct 31: G2/G3    | Real functioning build and non-hardcoded validated repair                       | Both; @olartgabo records outcomes |
| Nov 1            | Complete revision/persistence/review hardening                                  | Both                              |
| Nov 2-3: G4      | Second inventory, held-out failures, impossible case and baseline caveats       | @olartgabo                        |
| Nov 3-4: G5      | Hosted flow, recorded backup, reproducible source and portal verification       | @olartgabo                        |

All gates start unverified. If G2/G3 miss October 31, narrow supported templates
or operations and stop optional feature work. Confirm actual portal deadlines
and timezone rules; dates above are planning targets from the supplied spec.

## Domain verification (#3)

Domain contracts are implemented. `npm run contracts:generate` regenerates
JSON Schema/OpenAPI/TypeScript; `npm run contracts:check` rejects drift and is
part of `npm run check`. The [handoff](handoffs/issue-3-domain.md) defines the
consumer boundary. Product/compiler/physical gates remain unverified.
