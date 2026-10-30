# Issue #2 physical intake handoff

Status: partial; physical measurements and bench attempts are blocked on
hands-on input. Do not close #2 from this documentation change.

- Issue: [#2](https://github.com/olartgabo/forma/issues/2).
- Owner: @olartgabo. Reviewer: @ResniDev.
- Branch: `issue/2-physical-inventory-record`; base: `main`.
- Changed paths: the October 30 intake in `data/physical-tests`, its README,
  `docs/joint-profiles.md`, and this handoff.
- Behavior: records the supplied material list with provenance and unknowns,
  proposes three experimental bench strategies and a functional test to agree
  before building. No runtime behavior changes.
- Contract changes: none. Measured JSON fixtures wait for #3's schema.
- Physical/live results: not attempted; no photos, dimensions or test outcomes
  were supplied. All joint strategies remain experimental.

## Acceptance state

Stock measurements, tools, orientation/condition, three bench-tested strategies,
actual tolerances and a real build attempt remain pending. The functional test
procedure is proposed; actual device/mass/angle/surface are unknown. Intake is
progress toward #2 and does not satisfy its physical acceptance criteria.

## Validation

- `git diff --check`: exit 0.
- Local Markdown link check: exit 0,
  `Markdown links: 6 local targets exist across 4 changed files`.

No application checks exist on the main-branch documentation base; workspace
checks are introduced separately in [PR #18](https://github.com/olartgabo/forma/pull/18).
Documentation checks cannot establish a physical pass.

## Next action

@olartgabo measures labeled cardboard sources, records actual tools/connectors,
selects the test device and records the first hands-on attempt with the existing
build log. @ResniDev consumes reviewed measurements/profiles after #3. No
electronics or bottle-processing scope is added to P0.
