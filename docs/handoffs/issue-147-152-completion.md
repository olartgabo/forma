# Saved stability output and assembly overlay follow-up

The relevance check on November 4 found #147 merged through #168 and the assembly
viewer merged through #169, with deployment repair #178. This follow-up preserves
those implementations and closes two remaining integration gaps: untrusted model
prose could claim physical success, and the viewer did not consume saved reports.

Issue branch: `issue/147-152-current-completion`, based on `d21334f`.
Product decision: D060. No new solver, report store or physical pose producer.

Owned changes are the existing stability Muse runtime/route and history UI, the
assembly display adapter/route/domain contract, and their regression tests.
The saved-report freshness check also marks engine/dependency upgrades stale.
The shared API generator and generated contracts are integrated serially after
the two source changes. Current intake, photo localization, measurement decisions
and deployment configuration remain the baseline.

Verification results will be recorded on the final combined tree. No live model
call or physical observation is authorized by these software checks. The external
provider verification window remains expired.
