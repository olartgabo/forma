# Development plan

Status: November 2, 2026. The local workbench connects private intake, consented
Muse proposals, compiled manual approval, physical reports, repair review and
atomic revision approval, and versioned Proof/export. Install, dev and offline
check commands are in the [root README](../README.md); the connected sequence is
in the [demo runbook](demo-runbook.md). Physical build/recovery evidence, hosted
acceptance and the evaluation/submission package remain pending.

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

Merged software includes the core offline modules, scoped persistence, connected
Muse requests, approved repair revisions and versioned Proof (#95). Subsequent
merges through #110 add repair proposals in the browser, usage/consent handling,
bounded retry behavior and diagnosis explanations. Merged code and issue closure
do not establish physical acceptance. The connected handoffs record actual
software observations with synthetic imagery; no physical result follows from them.

| Available now                                                                         | Remaining acceptance or integration                                                                        |
| ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Pinned tooling, offline CI and generated contracts                                    | #1 schema integration review remains recorded as pending                                                   |
| Pure stock/operation validator                                                        | Measured inventory, cutting process and reviewed joint evidence from #2                                    |
| Narrow triangular tape-stand compiler and eight SVG panels                            | #8 exact physical attempt, tested profiles and supported build evidence                                    |
| Scoped consented Muse intake/design/diagnosis/repair runtimes                         | #4 real-team-photo SAM evidence and account/deployment prerequisites; accepted real-build model output     |
| Repair simulation, stand continuation and explicit revision approval                  | Generic strategy/angle changes and a second repair on a repaired version remain unsupported                |
| Owner-scoped SQLite projects, private media and immutable plan/event/evidence history | #6 hosted identity/storage/retention; real remaining-material reconciliation                               |
| Next.js manual approval, physical reports and versioned Proof/export                  | #13 actual build/recovery; #15 measured waste/salvage, timings, baseline comparisons and physical outcomes |

Next work follows the physical P0 path:

1. @olartgabo supplies the actual measurements, photos, tools, device/test
   conditions and upload decisions tracked in #2/#27. @ResniDev consumes reviewed
   process/profile records without replacing unknowns with fixture values.
2. @ResniDev verifies remaining live compatibility prerequisites, especially SAM
   on a consented real team photo, and supplies reviewed process/profile context
   for the measured inventory. Existing synthetic-photo software observations
   do not satisfy the complete G0 gate.
3. Both use the connected runbook for a generated build and actual recovery
   under #13. @olartgabo records physical events, named test conditions and
   outcomes without replacing unknowns with synthetic values. Inventory revision
   IDs remain separate from active plan version IDs.
4. @olartgabo evaluates inventory B, held-out cases and comparable baselines
   under #15, then verifies persistent hosting, fresh-session access, recording
   and participant-portal requirements under #16. The evaluation harness
   (`python -m forma_eval`) reports these counts from the attempt manifest and
   Proof exports; the protocol and build-log template define required evidence.

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

Complete live and physical gates remain unverified; offline regression coverage exists
for G1, but no new gate pass is inferred from merged code or issue closure.
If G2/G3 miss October 31, narrow supported templates
or operations and stop optional feature work. Confirm actual portal deadlines
and timezone rules; dates above are planning targets from the supplied spec.

## Domain verification (#3)

Domain contracts are implemented. `npm run contracts:generate` regenerates
JSON Schema/OpenAPI/TypeScript; `npm run contracts:check` rejects drift and is
part of `npm run check`. The [handoff](handoffs/issue-3-domain.md) defines the
consumer boundary. The offline compiler/renderer/replanner consume these types;
physical build/recovery and hosted acceptance remain unverified.
