# Implementation handoffs

Create one file per active issue using [TEMPLATE.md](TEMPLATE.md). The handoffs
below describe implemented interfaces, checks actually run and remaining work.
Some retain their original branch/review status or historical test counts;
consult current source, PR history and [development progress](../development.md)
before treating those notes as the current integration state.

Pydantic schemas, generated contracts, fixture IDs and compiler blockers form the
cross-lane boundary for API/UI work. Record changes before dependent code is
edited. Keep the latest branch/commit and
remaining blockers clear so an agent can resume without repeating experiments.

| Issue | Handoff                                                                                                                       | Current scope and remaining work                                                                                                                                                                                    |
| ----- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #1    | [Workspace](issue-1-workspace.md)                                                                                             | Tooling and offline checks implemented; original schema review remains recorded as pending                                                                                                                          |
| #2    | [Physical intake](issue-2-physical-intake.md)                                                                                 | Material list and proposed experiments only; measurements and physical attempts pending                                                                                                                             |
| #3    | [Domain contracts](issue-3-domain.md)                                                                                         | Immutable Pydantic models and generated downstream contracts implemented                                                                                                                                            |
| #4    | [Meta gateway](issue-4-meta-gateway.md)                                                                                       | Offline adapter and explicit smoke implemented; live account/photo compatibility pending                                                                                                                            |
| #5    | [Compiler](issue-5-compiler.md)                                                                                               | Offline resource/operation validation implemented; actual measured process/profile inputs required                                                                                                                  |
| #6    | [Persistence](issue-6-persistence.md), [private media](issue-6-private-media.md), [initial plans](issue-6-plan-activation.md) | Scoped local storage, initial/manual approval and user-report history implemented; connected producer/consent and repair activation are integrated; hosted on one AWS volume (D033); sign-in remains pending        |
| #7    | [Local intake](issue-7-intake.md), [requirements](issue-7-requirements.md), [connected Muse](connected-muse-demo.md)          | Private gallery, measured/unknown inventory, requirements and consented Muse interpretation implemented; segmentation review and physical measurements remain pending                                               |
| #8    | [Stand and manual](issue-8-stand-manual.md)                                                                                   | Narrow stand compiler and deterministic SVG implemented; physical acceptance pending                                                                                                                                |
| #9    | [Bounded proposals](issue-9-bounded-proposals.md), [connected core](connected-next-core.md)                                   | Scoped authenticated runtimes connect proposals to compiler/replanner checks; recorded live observations use synthetic imagery; accepted real-build results remain pending                                          |
| #10   | [Repair simulation](issue-10-repair-simulation.md)                                                                            | Offline simulation implemented; listed PR #30/#32 dependencies have now merged; see [current interface and limits](../../packages/replanner/README.md)                                                              |
| #11   | [Physical progress](issue-11-physical-progress.md)                                                                            | Explicit active-plan reports, checks, photo evidence and material receipts implemented; failed checks pause reports pending diagnosis/revision; expected stock needs physical reconciliation                        |
| #12   | [Repair revision](issue-12-adapt-revision.md)                                                                                 | Simulation, explicit atomic approval, carried completions and Adapt UI implemented; Muse repair proposals now feed the review; second revisions and physical recovery remain unsupported or unverified respectively |
| #14   | [Proof summary](issue-14-proof-summary.md)                                                                                    | Versioned snapshots, revision records, evidence invalidations, carried work and photo-excluded text/JSON exports implemented; physical outcomes and measured waste/salvage remain pending                           |
| #16   | [Current-flow documentation](issue-16-current-flow-docs.md)                                                                   | Setup, architecture and development status reconciled with merged connected flow; AWS deployment verified ([deploy](../deploy.md)); submission acceptance remains pending                                           |

The [fabrication report](issue-150-fabrication-report.md) handoff covers the
read-only next-step report, its declared access/tool rules and its manual and
repair-preview panels for #150.

No handoff establishes a real provider result or physical pass through fixture
checks. User-confirmed measurements, observed build/recovery outcomes and
authenticated end-to-end integration remain separate acceptance evidence.

The [stand replacement continuation](issue-39-stand-continuation.md) documents
the shared family validator, replacement SVGs, bounded original uncut-base
extension and unsupported resize variants for #39. The
[attached-brace recovery](issue-44-brace-tape-undo.md) handoff covers explicit tape
undo, preserved build history and recovery manuals for #44.

The [repair revision](issue-12-adapt-revision.md) handoff covers adapt/simulate,
explicit atomic adapt/commit, carried completions and the Adapt screen for #12.
