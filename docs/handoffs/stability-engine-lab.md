# Test the engine directly

From the repository root, run:

```powershell
uv run --locked python -m forma_stability --lab --port 3031
```

Open <http://127.0.0.1:3031>. Stop with Ctrl+C. Use the printed numeric loopback
address; other hostnames and cross-origin requests are rejected. This launches
only a small local workbench around the actual `evaluate_stability` function.
It does not run the FORMA app, database, Muse, or any provider. It writes no
measurements or project history and needs no key. The browser can explicitly
download an input/report/feedback file to the user's usual download location.

## Start with the actual compiled stand

The primary panel imports a real `BuildPlan` and calls the existing canonical
geometry producer. Its built-in JSON asset was exported from the actual compiler
and API software fixture, not drawn by hand. The sample remains synthetic.
Paste a compiled `BuildPlan` or an API response containing `version.plan` to
inspect another supported stand. Invalid/unsupported plans fail visibly.

Isometric 3D, front and side projections display the returned canonical facets,
source part IDs and fold area fractions. These fixed diagnostic projections
contain no new physical geometry or product-viewer scene engine. The origin is
the front base hinge, x across width, y rearward, z up. This differs from the
centered frame of the analytical rectangle cases below.

Select each hypothetical operation prefix to inspect the actual plan's IDs,
dependencies, attachment effects and existing manual instructions/tools. This
creates only an in-memory synthetic replay; no physical event is saved. The
initial view is a dashed planned-target reference. Prefixes 1–5 remain explicitly
unsupported for assembled geometry/contact, with **no numerical report**. A dashed
finished reference is not the current-stage shape. At prefix 6 or later the
existing producer can resolve the nominal assembled state. Functional tests are
never simulated as passed, including when their step is selected.

To calculate that supported hypothetical assembly, enter masses once per source
part (including allocated tape/connector shares), device world COM/mass, criterion
and the explicit uniform-mass/contact/rigidity assumptions. The folded support and
lip use the canonical single source centroid and are never counted twice. An
optional **Load invented load example** button makes a visibly hypothetical
experiment; it does not measure a stand. Move device y outside the base or remove
an assumption to inspect a failure or unresolved result. COM and critical-edge
overlays come from the real evaluator.

The standalone lab is an inspection tool, not Gabo's product 3D viewer or a new
fabrication scheduler. Full physical poses/contacts at intermediate construction
steps are not implemented by this diagnostic. Their unresolved state is itself
an engine limitation to report, not a false staged-mechanics claim.

Download **stand experiment and feedback** to preserve the exact original plan,
selected prefix, hypothetical loads, canonical geometry and result. Replay it
without trusting its stored report:

```powershell
uv run --locked python -m forma_stability --plan-input forma-compiled-stand-feedback.json
```

## Analytical unit cases

The initial numbers and all four presets are **invented mathematical examples**,
not evidence about your stand. Inputs are hypothetical even when entered manually.
The rectangular contact lies at z=0, centered at x=y=0. The server converts grams
to kilograms and millimetres to metres; the exact SI input and policy are visible.
Blank mass or COM fields mean unknown. Clearance, numerical tolerance and gravity
are explicit editable inputs. There is no assumed engineering safety reserve.

### Five useful attempts to break the scalar mechanics

1. **Centered:** 100 g stand plus 200 g device, both x=y=0, contact 200 by 100 mm.
   Expect 50 mm minimum clearance and 0.14715 N·m restoring moment at g=9.81.
2. **Exactly on edge:** move only device y to 75 mm. Combined y is 50 mm,
   clearance is zero, and with zero required margin the result is indeterminate.
3. **Outside:** device y=100 mm makes combined y about 66.67 mm and clearance
   about -16.67 mm. The tipping criterion fails.
4. **Mass scaling:** double both masses. COM and clearance stay unchanged;
   restoring moment doubles. Changing only one mass can change COM.
5. **Unknown and unsupported:** clear a mass/COM field; it must not pass.
   Uncheck horizontal support, rigidity or gravity-only applicability; the
   result must be unsupported, not a plausible numerical pass.

Also increase the required clearance above the calculated clearance: that
criterion must fail even while COM remains geometrically inside the contact.
Changing only COM height leaves horizontal, gravity-only tipping clearance
unchanged. That is a deliberate model limit: lateral pushes and dynamics are
not simulated. This lab does not determine sliding, tape strength, bending or
real-world safety. The geometry is a diagnostic rectangle, not the plan producer.

## Inspect, edit and report

The form calls the real evaluator; there is no copied mechanics formula in the
browser. The SVG is only a projection of the returned COM, support and critical
edge. Open **Exact engine input and policy** to test raw typed cases, invalid
inputs or interval quantities. Intervals currently remain indeterminate; finite
sampling does not certify them. This pure boundary cannot authenticate provenance
or evidence strings supplied in an edited packet; that is the connected API's job.

Write what you changed, expected and observed in the feedback box, then download
the bundle and send it back. The download contains the last calculated inputs and
report, not unsaved form/JSON changes. A displayed result becomes historical as
soon as an input changes. Useful feedback includes both incorrect results and
misleading explanations, missing controls, confusing units or useless output.

For command-line experiments, save the editor's `{ "input": ..., "policy": ... }`
packet or use the downloaded feedback bundle and run:

```powershell
uv run --locked python -m forma_stability --input case.json
```

The normalized input, policy and freshly calculated report print as JSON. A
downloaded bundle's stored report is ignored and recalculated from its inputs.
The same cases can be
verified offline with `uv run --locked pytest packages/stability/tests/test_lab.py`.
Software checks and hypothetical reports establish no physical outcome.
