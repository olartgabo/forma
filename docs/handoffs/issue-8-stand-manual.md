# Issue #8 stand and SVG handoff

Status: software implementation; physical acceptance remains unverified.
Owner @ResniDev; reviewer/consumer @olartgabo. Branch issue/8-stand-manual,
stacked on #3 and #5. No model/provider, persistence or web edits.

## Interfaces and geometry

Import `StandParameters`, `compile_stand`, `render_manual` from forma_renderer.
Root packaging installs packages/renderer/src/forma_renderer and pytest discovers
packages/renderer/tests. No dependency or lock changes.

`compile_stand(request: CompilerInput, parameters: StandParameters, *,
process: CutProcess | None = None, allow_synthetic=False) -> CompilerResult`.
Requires one identified sheet with one region, one tape stock, three panels,
one allowed measured tape profile and one fold profile. Resolves profile evidence
against supplied same-project observations. Duplicates, missing/colliding IDs,
unsupported profiles and geometry produce typed blockers, not partial plans.
Actual dimensions/confirmation, process evidence and tool/access checks are
required by default. Synthetic evidence is accepted only with explicit opt-in.

Support blank width/height and support angle come from the candidate; lip and
base depth are explicit measured StandParameters. Effective support length is
blank height minus lip. Top contact has horizontal reach S*cos(angle), rise
S*sin(angle). Rear base contact must lie beyond that reach; brace length is
hypot(depth-reach, rise). Device width/contact-height/thickness must fit the
support/lip; footprint and angle must meet confirmed constraints. Real fold
allowance, friction, strength, grip, access, stability and device retention remain
manual checks bounded by physically tested profiles, not mathematical proof.

The nominal assembly is three rectangular panels (support/base/brace) arranged
as a triangle, a valley-fold retaining lip, and front/rear/apex tape hinges.
Each tape strip consumes full panel width; tape width must allow confirmed
face overlap. Whole sheet source region consumed; unused area is reported waste
and not returned as an offcut. No stock is silently recovered.

Stable IDs use stand-support/base/brace, stand-lip-fold, stand-joint-front/rear/
apex. Operation sequence: cut-panels, inspect-cuts, fold-lip, front/rear/apex
attach, inspect-fit, functional-test. Every operation carries typed effects and
dependencies. There are ruler/fit/final-test checkpoints and explicit user
confirmation throughout. The caller must log actual completion/evidence and
rechecks separately; the manual performs no physical event writes.

`render_manual(plan: BuildPlan, *, process=None, profile_evidence=(),
allow_synthetic=False) -> Manual` independently validates compiler checks plus
exact supported IDs/topology/fold features, operation/checkpoint consistency and
positive triangle geometry. Unsupported/malformed plans return no panels and
blockers. A Manual contains frozen tuple Panels (operation/part/checkpoint IDs,
SVG, SHA256 dependency hash, tools), BOM rows and physical_verification
not_attempted. The accepted status refers to software checks only.

## Determinism and SVG

Flat views use top-left stock coordinates, numeric dimensions/origins and dashed
cut/fold lines. Side views derive all lengths/angles from the plan, show numbered
hinges and part labels, and distinguish current/prior/future planned joins.
Tool lists, expected state and checkpoints remain visible. Text uses XML escaping;
long instructions expand SVG height instead of covering geometry. Labels are
external legends to avoid collision on narrow stock. Display dimensions round
to two decimals; stored plan geometry is retained.

Panel hashes cover renderer-version plus exact SVG bytes. Plan version/time are
excluded so unchanged panels can be reused across versions. Any visible change
changes the hash; checkpoint validity still requires independent replanner checks.
Synthetic opt-in adds visible watermarks and changes panel bytes/hash.

## Checks and next action

Renderer regression tests cover two distinct synthetic inventories/dimensions/
angles, full XML IDs/checkpoints/tools, byte identity, version-independent cache,
per-panel hash/bytes equivalence for all eight panels under a footprint-depth
change with fold panel 2 reused and the other seven panels invalidated,
alternate-fixture coverage showing fold panel 2 invalidates on support angle/blank-height change,
physical-default rejection, unknown measurements, short stock, incompatible device contact,
XML escaping, malformed supported IDs, missing checkpoints/mass/fold/topology,
duplicate IDs/evidence and long text. All fixtures are labelled software-only; no
actual physical build/test attempted.

A one-off local visual inspection of synthetic panels was performed using headless Edge.
It is not reproduced by any repository test and is not physical evidence.

Next: @olartgabo supplies measured stock and actual tested profile/process
records; both engineers perform the exact build and document observed deviations.
Do not close physical #8 acceptance or claim buildability from fixture checks.

Check results are recorded in the pull request, not in this file.
