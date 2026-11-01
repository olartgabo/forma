# Development plan

Status: October 31, 2026. Offline compiler, stand SVG, repair simulation and
bounded proposals are implemented, along with private project/inventory/photo storage.
The web supports local goal/photo/inventory intake. Install, dev and offline check commands are in the
[root README](../README.md). Runtime integration, live provider compatibility
and physical build/recovery evidence remain pending.

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

## Current progress and next work

Merged software includes the workspace (#18), domain contracts (#20), gateway
(#21/#35), compiler (#22/#30), stand renderer (#23/#34), bounded proposals
(#24/#31), replanner (#25/#28/#29/#32) and first persistence slice (#26).
PR numbers describe landed code; they do not establish the parent issue's
complete acceptance or a physical pass. The tracker currently closes #3/#5/#10;
their offline implementations still depend on real measurements and integration
before the complete build/recovery flow can run.

| Available now                                                         | Remaining acceptance or integration                                                                    |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Pinned tooling, offline CI and generated contracts                    | #1 schema integration review remains recorded as pending                                               |
| Pure stock/operation validator                                        | Measured inventory, cutting process and reviewed joint evidence from #2                                |
| Narrow triangular tape-stand compiler and eight SVG panels            | #8 exact physical attempt, tested profiles and supported build evidence                                |
| Scoped bounded intake/design/diagnosis/repair service                 | #4 live Spark/SAM evidence and #9 trusted callbacks/authenticated runtime integration                  |
| Repair simulation, remaining-stock reconciliation and recheck preview | Family continuation wiring; unsupported strategy/angle changes and completed-work undo remain blocked  |
| Owner-scoped SQLite project/inventory/photo routes with durable retries | #6 consented provider transfer, hosted identity/storage and immutable plan/event/material/evidence history |
| Next.js goal/photo/inventory workbench with saved tools and device constraints | #7 segmentation and provider interpretation, #11 manual/events, #12 approved revision transaction and #14 proof UI |

Next work follows the physical P0 path:

1. @olartgabo supplies the actual measurements, photos, tools, device/test
   conditions and upload decisions tracked in #2/#27. @ResniDev consumes reviewed
   process/profile records without replacing unknowns with fixture values.
2. @ResniDev runs the consented live smoke after account/region/privacy/quota
   prerequisites are confirmed, records sanitized results and connects trusted
   compiler/replanner callbacks for #9. Smoke fixtures do not satisfy G0.
3. @olartgabo connects scoped persistence to intake and the manual, then adds
   physical event/evidence history and explicit approved revision activation.
   Inventory revision IDs remain separate from active plan version IDs.
4. Both perform the generated build and real recovery, record outcomes under
   #13, then evaluate held-out cases and deployment under #15/#16.

Provider and persistence ownership share `apps/api`; keep edits disjoint and
record contract handoffs before dependent changes. Use the
[handoff index](handoffs/README.md) for exact interfaces and historical checks.

## Verification when implementing

1. Run the repository's actual formatter, typecheck, affected unit tests and CI
   commands. `npm run check` runs formatting, Ruff lint, generated-contract
   freshness, web TypeScript, offline pytest and the production web build.
   Report exact outputs and limitations from the actual tree checked.
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

Live and physical gates remain unverified; offline regression coverage exists
for G1, but no new gate pass is inferred from merged code or issue closure.
If G2/G3 miss October 31, narrow supported templates
or operations and stop optional feature work. Confirm actual portal deadlines
and timezone rules; dates above are planning targets from the supplied spec.

## Domain verification (#3)

Domain contracts are implemented. `npm run contracts:generate` regenerates
JSON Schema/OpenAPI/TypeScript; `npm run contracts:check` rejects drift and is
part of `npm run check`. The [handoff](handoffs/issue-3-domain.md) defines the
consumer boundary. The offline compiler/renderer/replanner consume these types;
the complete product journey and physical gates remain unverified.
