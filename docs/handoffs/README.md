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

| Issue | Handoff                                            | Current scope and remaining work                                                                                                                       |
| ----- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| #1    | [Workspace](issue-1-workspace.md)                  | Tooling and offline checks implemented; original schema review remains recorded as pending                                                             |
| #2    | [Physical intake](issue-2-physical-intake.md)      | Material list and proposed experiments only; measurements and physical attempts pending                                                                |
| #3    | [Domain contracts](issue-3-domain.md)              | Immutable Pydantic models and generated downstream contracts implemented                                                                               |
| #4    | [Meta gateway](issue-4-meta-gateway.md)            | Offline adapter and explicit smoke implemented; live account/photo compatibility pending                                                               |
| #5    | [Compiler](issue-5-compiler.md)                    | Offline resource/operation validation implemented; actual measured process/profile inputs required                                                     |
| #6    | [Persistence](issue-6-persistence.md), [private media](issue-6-private-media.md), [initial plans](issue-6-plan-activation.md) | Private project/inventory/photo and immutable plan/manual storage with initial approval implemented; user-report/evidence/material history in #11; live producer, hosted identity, consented transfer and repair activation pending |
| #7    | [Local intake](issue-7-intake.md), [requirements](issue-7-requirements.md) | Goal/project reopening, private gallery, measured/unknown inventory, tools and device constraints implemented; segmentation and provider interpretation pending |
| #8    | [Stand and manual](issue-8-stand-manual.md)        | Narrow stand compiler and deterministic SVG implemented; physical acceptance pending                                                                   |
| #9    | [Bounded proposals](issue-9-bounded-proposals.md)  | Scoped proposal service implemented; trusted runtime callbacks and live evidence pending                                                               |
| #10   | [Repair simulation](issue-10-repair-simulation.md) | Offline simulation implemented; listed PR #30/#32 dependencies have now merged; see [current interface and limits](../../packages/replanner/README.md) |
| #11   | [Physical progress](issue-11-physical-progress.md) | Explicit active-plan reports, checks, photo evidence and material receipts implemented; failed checks pause reports pending diagnosis/revision; expected stock needs physical reconciliation |
| #14   | [Proof summary](issue-14-proof-summary.md) | Consistent initial-plan/report snapshots, provenance and photo-excluded text/JSON exports implemented; repair/invalidation and physical verification remain pending |

No handoff establishes a real provider result or physical pass through fixture
checks. User-confirmed measurements, observed build/recovery outcomes and
authenticated end-to-end integration remain separate acceptance evidence.
