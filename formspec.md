# FORMA — Final Context & Build Spec

> **Turn what you have into what you need.**
>
> **The invention doesn't stop when the instructions fail.** FORMA understands your materials, generates a constrained physical design and an illustrated assembly manual, then revises the unfinished build when reality disagrees with the plan—while accounting for materials already used and work already completed.

**Document status:** FINAL implementation source of truth, v1.0 · **October 30, 2026**  
**Event:** Meta Global AI Developer Hackathon 2026 (virtual)  
**Track:** Indie Developer (confirm team membership/eligibility in the participant portal)  
**Primary theme:** Push the Frontier · **Secondary theme:** Build for Your World  
**Team:** Two engineers; assign Owner A (physical compiler/validation) and Owner B (product/Meta integration)  
**Deadline:** November 4, 2026, **9:00 PM US Eastern / 10:00 PM Bolivia** (check portal for changes)  
**Language:** English-first, Spanish supported for problem descriptions and generated guidance  
**Core product:** Mobile-friendly web app; no mandatory native app  
**Working definition of success:** Real user + real inventory + real physical build + non-scripted recovery + evidence that the final object works.

---

## 0. Executive decision: what we are building

FORMA is **not** a generalized structural-engineering model, a chatbot that invents cardboard projects, a photo-to-CAD magic trick, or an image generator pretending its illustrations are build plans.

FORMA is a **closed-loop, inventory-constrained physical assembly and recovery system** for a carefully supported class of **low-risk desktop fixtures made primarily from reused sheet materials**. A user describes a need, photographs what they have, confirms measurements, reviews feasible build options, and follows step-by-step, diagram-first assembly instructions. When a piece is damaged, missing, or the wrong size, FORMA uses visual evidence and the current assembly state to propose a constrained modification, then **validates the changed operations, tracks consumed material, preserves usable completed work, and invalidates any checks that must be repeated**.

**Central technical thesis:** A multimodal model can help propose and diagnose physical changes, while a deterministic **Assembly Compiler** enforces the machine-checkable portion of physical constraints, tracks irreversible transformations, and compiles each valid state into consistent instructions.

**One-sentence pitch:** *FORMA is an adaptive AI invention engine that converts scraps into usable objects and rewrites the build—not just the chat—when construction goes wrong.*

**Claim discipline:** In this prototype, "buildable" means *accepted by FORMA's documented family-specific checks and demonstrated through named physical tests*, **not** guaranteed safe or universally manufacturable. "Proof" means recorded evidence and checks, **not** a formal structural-safety certification. "Adapt" means a model-proposed, validator-approved **plan revision**, **not** unrestricted autonomous engineering.

### 0.1 The user, their job, and why it matters

**Primary initial user:** A novice maker, student, or hackathon participant working at a desk with limited tools and reused materials, who wants a useful organizer or holder and cannot reliably buy all ideal components.

**Job to be done:** "I have a physical problem and these scraps. Help me make a workable object. If a critical part does not fit, don't make me throw away an hour of work."

**Observed problem hypothesis (not yet validated):** Existing tutorials assume specific materials and dimensions. Generic conversational advice loses track of steps, stock, and completed operations. Image generators can silently alter assembly geometry. Makers improvise or restart when pieces are unavailable or damaged.

**Research requirement:** Interview/observe three target users if possible. Record their actual failure, what they currently do, how long recovery takes, and whether a fixed tutorial or iterative AI chat already solves it. No invented interview quotes or demand statistics.

### 0.2 Why this is distinctive

1. **Inventory-grounded:** Named, user-confirmed stock items with shape, size, remaining usable area and material consumption.
2. **Operation-grounded:** Assembly is a sequence of typed physical transformations with preconditions, effects, and reversibility.
3. **Physical-state aware:** The build has a committed plan state and a separately recorded observed state.
4. **Localized recovery:** Changes preserve completed work when feasible; rework, material loss, and rechecks are explicit.
5. **Deterministic diagrams:** Geometry and numbered labels come from a single source of truth; generated imagery cannot change the parts list or connections.
6. **Honest failure behavior:** The engine can reject infeasible designs, ask for a real measurement, or say additional material is necessary.
7. **Evidence-driven demo:** The output is a real functioning object, not a storyboard.

### 0.3 Hero demonstration

Two physically constructed versions of **one functional object** (e.g., an adjustable phone/desk stand) using different confirmed inventories and at least two materially different joints or dimensions. For the primary version, introduce a genuine failure after some operations have been completed, such as a torn slot, incorrect stock dimensions, or missing fastening material. Upload evidence. FORMA identifies what is observed versus inferred, proposes a safe replacement plan, **preserves completed valid operations**, reports what must be undone, compiles the new diagrams, and directs a physical recovery. Verify the actual function using a predetermined test.

**Do not choreograph a hardcoded "missing tape → use string" answer.** The failure type can be selected from a held-out supported set. Show a separate infeasible input where FORMA refuses to fabricate an answer.

### 0.4 Competition facts, assumptions and decisions

| Item | Status | Action |
|---|---|---|
| Indie track and two themes | Public official event page confirmed | Submit under Indie if participants eligible |
| Qualitative judging | Indie: creativity, technical ambition, and whether it works | Optimize for observed physical result, not agent count |
| 30/25/20/25 scoring weights (Impact / Meta / Technical / Demo) | From a third-party review; **not verified as official** | Use as internal heuristic only |
| November 4, 9 PM ET deadline | Confirmed on public event page | Recheck participant portal |
| Team size, waiver, media rights, deliverables, any credits | Depends on participant terms/dashboard | Verify on day 0; don't assume a specific credit allotment |
| Models listed below | Confirmed in public API documentation | Account-key smoke tests still required |

---

## 1. User experience — the shortest complete journey

1. **Describe:** "I need a stand that holds my phone for video calls. I have one cardboard sheet, strips from packaging, tape, and string. No glue gun."
2. **Inventory:** Upload one or more photos; FORMA identifies candidate objects; user confirms stock, dimensions, quantity, tools, and condition. Unknowns remain unknown.
3. **Constraints:** Confirm phone size/mass (or device class), viewing angle preference, budget, desired footprint, and acceptable joining methods.
4. **Invent:** Muse Spark proposes 1–2 design configurations **inside a supported family**, not arbitrary free-form inventions. Validator rejects infeasible ones. Display differences: materials, stability assumptions, cuts, joins, complexity, cost, and uncertainty.
5. **Compile:** Selected design creates immutable version `v1`: stock/cut layout, parts, joins, operations, assembly dependencies, SVG panels, bill of materials and checkpoints.
6. **Build:** User completes each action, takes optional checkpoint photos, and confirms any checks requiring hands-on testing. Completed work is logged separately from planned work.
7. **Fail:** At a real step, the user reports "The slot tore" with a photo. Perception identifies visible evidence and asks for any missing facts.
8. **Adapt:** FORMA proposes candidate repairs using the *remaining stock and already built pieces*. The compiler checks each; a revision preview names preserved work, unavoidable undo, new cuts, stock cost, changed instructions and invalidated checks.
9. **Approve:** User approves an adaptation; version `v2` becomes active. Older plan/evidence remains available.
10. **Verify:** User physically completes the build and runs a defined functional test. Results are recorded as user-observed evidence.

### Screens (P0)

| Screen | Essential UI | Nonnegotiable behavior |
|---|---|---|
| **Start** | Goal, photos, example supported projects | Show scope and safety limits clearly |
| **Inventory** | Image thumbnails, proposed labels, editable dimensions/count/condition, scale reference | Confirm all measurements that influence cutting; no fabricated dimensions |
| **Design** | 1–2 variants, BOM, remaining stock, risks, preview | Show *why* a design is feasible or why it is rejected |
| **Manual** | Large authoritative SVG, next/previous, exact operation, part IDs, material use, expected state | Phone-friendly; steps trace to versioned operations |
| **I'm stuck** | Photo upload + text (optional voice), current step pinned | Separates observed details, possible causes, and questions |
| **Adapt review** | Before/after diff, preserved operations, undo, lost stock, rechecks, new panels | Explicit approval; never silently overwrite progress |
| **Proof** | Evidence timeline, validations, unresolved unknowns, functional test, export summary | Clearly distinguishes checked, self-reported, inferred, and unverified |

**Accessibility:** Large labels and diagrams, high-contrast arrows, avoid color-only distinctions, all critical guidance readable without audio, thumb-accessible actions, bilingual text for core flows.

---

## 2. Product scope — ambitious thesis, narrow execution

### P0 — must work to submit

- [ ] One **supported parametric family**: small tabletop holders/organizers, with a specific mandatory demo object (adjustable desk/phone stand).
- [ ] At least **two meaningful parameterizations/inventory variations** of the hero object; differences cannot be only illustrative textures.
- [ ] 1–2 user-confirmed stock sheets with measured dimensions, plus strips/tape/string or another physically tested compatible connector.
- [ ] Support at least **three physically tested joint/repair strategies** across the demo test set (e.g., fold-brace, tab-slot, and tape/lash); only advertise those actually validated.
- [ ] Material accounting for rectangular stock, cut allocation, and remaining regions; reject oversubscription.
- [ ] Typed operation set and deterministic geometry, validator, dependency graph, and SVG manual.
- [ ] Muse Spark-based image/problem interpretation, constrained design proposal, and discrepancy-aware repair proposal.
- [ ] SAM 3.1 for **at least one genuinely useful** inventory or checkpoint segmentation flow if endpoint smoke test succeeds; user-correction fallback always exists.
- [ ] Versioned plan changes with preserved completed work, explicit physical undo, required rechecks, and invalidated evidence.
- [ ] User-confirmed physical checks and photographs at meaningful checkpoints.
- [ ] Real physical build, real failure, successful repair; an infeasible case; evaluation versus baselines.
- [ ] Hosted web app, working project persistence, error/fallback states, reproducible demo, submission artifacts.

### P1 — only if physical P0 is green

- [ ] Muse Image enhancement for selected instructional panels, visually compared to deterministic diagrams; user can always see the authoritative version.
- [ ] Voice input via Muse Voice Transcribe and optional speech playback; not necessary for troubleshooting.
- [ ] Spanish/English UI polish and per-step narration.
- [ ] Printable PDF/manual export **if** renderer stable (otherwise print CSS / SVG export).
- [ ] Third independent builder and additional inventory/failure samples.
- [ ] Lightweight editable/rotatable 3D preview derived from the same geometry.
- [ ] Shareable versioned proof report.

### P2 — explicitly after hackathon

- [ ] More assembly families (desk lamps, shelves, organizers, safe low-voltage hobby electronics).
- [ ] Full parametric CAD with STEP/STL and automated nesting for arbitrary polygons.
- [ ] Advanced kinematic/mechanical solvers and physical simulation.
- [ ] Continuous camera guidance and world-state tracking with video.
- [ ] Persistent inventory across projects; inventory sourced from purchased and salvaged items.
- [ ] Community-verified builds, forks, revisions, material-substitution knowledge base.
- [ ] Dataset of failures and successful repairs; fine-tuned/open-weight verifier.
- [ ] Native mobile or AR/wearable guidance; robotic execution.
- [ ] Local marketplace and safe electronics purchasing integration.

### Explicitly OUT for the hackathon

No free-form universal hardware invention; no autonomous use of blades/tools; no mains/high-voltage, batteries assembled from loose cells, soldering circuits of unknown safety, pressure vessels, medical devices, structural supports for humans, vehicle systems, weapons, heavy load-bearing components, or claimed engineering certification. No continuous video requirement, automatic photo-based exact measurement, or fabricated product prices and engineering tolerances.

**Hard product constraint:** When a user's request falls outside the supported family, explain the limit and offer a supported variation or refuse; do **not** invent arbitrary assembly operations to appear capable.

---

## 3. Architecture — Meta reasons, the compiler decides, humans verify

```text
┌────────────────────────────── FORMA Web (Next.js / React) ──────────────────────────────┐
│ Goal + inventory   Design choice   SVG manual   Stuck/photo   Adapt diff   Proof log   │
└────────────────────────────────────┬─────────────────────────────────────────────────┘
                                     │ typed REST / async job status
┌────────────────────────────────────▼─────────────────────────────────────────────────┐
│ FORMA API (FastAPI, Pydantic)                                                         │
│ Auth/session | project service | state machine | model gateway | evidence store       │
│                                                                                      │
│  Model coordinator (bounded)                        Deterministic compiler           │
│  ┌─────────────────────────────────┐              ┌────────────────────────────────┐ │
│  │ Muse Spark 1.3                  │ --proposals→ │ validate typed operations      │ │
│  │ - interpret goal & observation  │              │ allocate stock / cut layout    │ │
│  │ - choose candidate repairs      │ ←rejections─ │ verify joints & dependency     │ │
│  │ - ask targeted questions        │              │ state transitions / undo cost  │ │
│  └─────────────────────────────────┘              │ compile diagrams & checks      │ │
│            ▲         ▲                            └─────────────────┬──────────────┘ │
│       SAM 3.1    Muse Image                                            │                │
│      image masks  style-only illustration (optional)         Versioned Build Graph    │
│                                                            + operations + evidence   │
└─────────────────────────────────────────────────────┬────────────────────────────────┘
                                                      │
                               PostgreSQL / SQLite dev + object storage (images, SVG)
```

### Architectural rules

1. **No generated image is authoritative geometry.** All dimensions, coordinates, BOM, labels, joint locations, and cut lines originate in compiled structured data.
2. **The model never commits physical state.** It proposes typed objects/patches; deterministic code validates; user approves; evidence records actual state.
3. **No unconfirmed dimensions become fabricated facts.** A photo alone does not establish centimeter scale; require a ruler/reference or manual input.
4. **Every physical operation refers to existing inventory/part IDs, known geometry, and an allowed operation type.**
5. **Nothing is "preserved" simply because it is a completed step.** Preserve only if its part geometry, required interfaces, dependents, and verification evidence remain valid under the new version.
6. **No irreversible action without an explicit confirmation/checkpoint.** Especially cuts and permanent bonding.
7. **Every approved revision is atomic and immutable.** No partial graph writes, silent reordering of completed steps, or retroactive rewriting of evidence.
8. **No infinite agent loop.** Bounded candidate generation, validation feedback, retry limit, then ask the user or refuse.
9. **No claim of verified physical function without actual test evidence.** Model scores are not calibrated reliability measurements.
10. **No model-provider details in the core domain.** The compiler must run entirely offline with fixture inputs.

### Services / ownership

| Module | Owner | Implementation | Responsibility |
|---|---|---|---|
| `domain` | A | Python/Pydantic models | IDs, units, typed materials/parts/actions, state |
| `compiler` | A | Pure Python | validate, stock allocation, joint checks, dependency analysis |
| `replanner` | A | Python | candidate cost, preserved work, inverse ops, evidence invalidation |
| `renderer` | A | SVG Python or shared TS geometry | stable, numbered instruction diagrams + cut templates |
| `model_gateway` | B | Python Meta SDK/HTTP | Spark, SAM, optional Image/Voice; timeouts and tracing |
| `orchestrator` | B | bounded state machine | prompt → proposal → deterministic tool → result |
| `web` | B | Next.js/React/TypeScript | workbench, manual, adaptation review, mobile polish |
| `evidence` | shared | DB + file storage | photos, user actions, physical test results, provenance |
| `evaluation` | shared | scripts + actual builds | perturbation matrix, baselines, time and quality metrics |

---

## 4. Physical domain and the Assembly Compiler

### 4.1 Supported design family

**Mandatory hero:** One freestanding, low-mass tabletop phone stand / reading stand with a sloped support and back brace, made from recycled cardboard/paperboard and simple removable or low-risk join methods. The demo should be *visibly different* across two inventories: dimensions, bracing angle/geometry, stock allocation and joint type where physically feasible.

**Additional within-family variant (only if time):** A desk cable/charging organizer using the same sheet-cutting and joining engine. Avoid suggesting the organizer includes a charging circuit or safe battery electronics.

**Limits to document and verify:** sheet thickness range measured physically; maximal object mass, angle range, stock minimum dimensions, supported tools and joining methods. Do not invent default safe working loads; empirical tests bound what was actually built.

**Physical verification protocol:** Define the real test mass/device, stand angle, contact geometry, duration, and repeated use test before building. Examples of *proposed* tests: upright stability on a flat desk; support a named phone model for 60 seconds; tap screen gently; perform three insert/remove cycles. Only report a pass when observed and recorded.

### 4.2 Units and geometry contracts

- Coordinate frame: millimeters, integer or decimal with documented tolerance; origin at top-left of each flat stock sheet.
- Stock pieces: polygons in P2; **P0 rectangular sheets and rectangular/slot operations** only.
- Each stock has `usable_regions` after cuts. A cut operation consumes a parent region and creates explicitly dimensioned child parts plus offcut regions. Use a 2D cut planner with non-overlap, orientation restrictions, edge margins, and kerf allowances.
- For fold actions, record line endpoints, direction, intended angle category and reachable face; model approximate thickness/fold allowance only for physically tested material profiles.
- Components inherit material and source stock provenance; part IDs never silently change across revisions.
- Camera poses for diagrams are deterministic; SVG labels and arrows are overlays, not baked into generative pictures.
- Unknown thickness, flexibility, strength, and hidden connections must stay uncertain; ask for a measurement or check instead of guessing.

### 4.3 Assembly operation semantics

| Operation | Preconditions | Effects | Physical reversibility |
|---|---|---|---|
| `measure` | Accessible physical item; measurement method specified | Adds confirmed measurement evidence | N/A |
| `mark` | Part exists; feature within bounds | Adds mark/reference geometry | Usually reversible only by replacement of mark |
| `cut_rect` | Source region large enough incl. kerf; safe tools confirmed | Consumes region; creates child part(s) and offcuts | **Irreversible** |
| `cut_slot` | Slot lies within bounds; correct margin/thickness tolerance | Creates slot geometry, changes parent part | **Irreversible** |
| `fold` | Fold line within bounds; material can fold; clearance verified or user-check required | Changes part state / hinge geometry | Partially reversible; may permanently weaken |
| `insert_tab` | Compatible tab/slot profile; accessible sides | Creates mechanical attachment | Generally reversible if not damaged |
| `tape_joint` | Tape stock and surface accessible | Consumes tape; joins parts | Removal may destroy cardboard; record as destructive if necessary |
| `tie_joint` | String/cord stock sufficient; accessible tie path | Consumes length; creates attachment | Usually reversible (cutting cord may consume it) |
| `attach_brace` | Compatible geometry and accessible joint features | Adds brace and load path | Depends on underlying joint |
| `detach` | Joint type supports removal; not load-bearing during removal | Removes attachment, maybe consumes material | May have loss cost |
| `inspect` | Target visible or manual access possible | Records visual/human evidence | N/A |
| `functional_test` | Assembly stable enough to test; test defined | Records user-observed pass/fail | N/A |

**Compiler meaning:** "Executable" refers to **typed, validate-able plan semantics**, not robot-performed manipulation. Explicitly label checks the compiler *cannot* prove: hidden fastener access, actual cardboard strength, visual-only weight capacity, unseen cracks, friction, or real stability.

### 4.4 Required deterministic checks (P0)

| Check | What code can check | What still requires a person |
|---|---|---|
| Schema & IDs | unique IDs, references, units, enum values, versions | none |
| Inventory conservation | no negative inventory, no stock double-spend, material accounting | actual stock condition |
| Cut feasibility | 2D containment, non-overlap, kerf, min border margins, supported orientation | safe cutting and tool suitability |
| Joint geometry | slot/tab widths within measured tolerance and tested profiles | actual friction/tear quality |
| Assembly ordering | DAG order, prerequisites, operations applied once | actual access and manipulation |
| Undo plan | supported reverse operation + estimated material loss | whether object can be disassembled intact |
| Stability heuristic | footprint, approximate center of mass where mass inputs are known | load test on actual surface |
| Verification freshness | evidence tied to graph version, parts, operations and checks | whether observed evidence is sufficient |

**Critical rejection cases:** impossible cut; missing material; insufficient remaining offcut; unsupported joint; physically irreversible step demanded to be preserved despite geometry change; unknown critical dimensions; unsafe load/operation; request outside domain; insufficient evidence for a specific diagnosis.

### 4.5 Material allocation / salvage

- Every material instance has a physical source ID (`stock-01`, `strip-02`, etc.), dimensions, orientation and condition.
- A cut references source and transforms its region set. Subsequent allocations can only consume remaining usable regions.
- Offcuts retain provenance and can be reused **only if their derived dimensions are sufficient**.
- Include a configurable kerf and an edge-safety margin drawn from the tested process; never assume zero kerf.
- `cut_rect` does not magically create extra sheet area. Detect negative quantities, overlap, or reusing the same offcut twice.
- If a stock item is damaged after cutting, record damaged regions or mark the entire piece unusable; recalculate from the actual remaining inventory.
- Inventory uncertain? Proposed plan remains `needs_measurement`; do not enable the next irreversible operation.

### 4.6 Joint catalogue

Store verified **joint profiles**, not generic joint guesses:

```yaml
joint_profiles:
  - id: tab_slot_cardboard_v1
    requires: [measured_sheet_thickness, cut_slot, insert_tab]
    tolerated_error_mm: null   # fill only after physical tests
    test_evidence: []           # required before promoting to supported
  - id: folded_brace_v1
    requires: [measured_sheet_thickness, fold, attach_brace]
    tolerated_error_mm: null
    test_evidence: []
  - id: tape_or_tie_brace_v1
    requires: [measured_joint_access, tape_joint_or_tie_joint]
    tolerated_error_mm: null
    test_evidence: []
```

Fill actual tolerances and materials via measured bench tests; until then mark profiles `experimental`. Unsupported profiles must not silently pass as certified.

---

## 5. Build Graph, state and versioning

**Build Graph** is an intermediate representation containing a **plan**, inventory/material transactions, component geometry, action graph, expected checkpoints, and links to observations. Observed physical state and evidence are **separate** from desired plan state.

### 5.1 Minimal typed schema (illustrative, not exhaustive)

```ts
type ID = string;
type Mm = number;
type VerificationState = "not_checked" | "user_confirmed" | "vision_observed" | "failed" | "unknown" | "invalidated";
type PhysicalAction = "measure" | "mark" | "cut_rect" | "cut_slot" | "fold"
  | "insert_tab" | "tape_joint" | "tie_joint" | "attach_brace"
  | "detach" | "inspect" | "functional_test";
type Reversibility = "reversible" | "lossy" | "irreversible" | "not_applicable";

type Rect = { x: Mm; y: Mm; w: Mm; h: Mm; rotationDeg: 0 | 90 };
type Condition = "usable" | "damaged" | "uncertain";

interface Measurement {
  value: number | null; unit: "mm" | "g" | "deg";
  source: "user_ruler" | "known_reference" | "calculated" | "unknown";
  confirmed: boolean;
}
interface Stock {
  id: ID; kind: "sheet" | "strip" | "tape" | "cord";
  material: "cardboard" | "paperboard" | "other_supported";
  widthMm?: Measurement; heightMm?: Measurement; thicknessMm?: Measurement;
  remainingLengthMm?: Measurement; condition: Condition;
  usableRegions: Rect[]; imageIds: ID[];
}
interface Part {
  id: ID; sourceStockId: ID; geometry: Rect;
  featureIds: ID[]; condition: Condition;
}
interface Joint {
  id: ID; profileId: ID; partIds: ID[];
  interfaceFeatureIds: ID[]; confirmedAccessible: boolean | null;
}
interface Operation {
  id: ID; type: PhysicalAction; partIds: ID[]; stockIds: ID[];
  dependsOn: ID[]; args: Record<string, unknown>;
  reversible: Reversibility; expectedStateId: ID;
  requiresUserConfirmation: boolean;
}
interface Checkpoint {
  id: ID; afterOperationId: ID;
  method: "photo" | "ruler" | "human_inspection" | "functional_test";
  description: string; invalidatedBy: ID[];
}
interface BuildPlan {
  projectId: ID; versionId: ID; parentVersionId?: ID;
  family: "tabletop_fixture_v1"; status: "draft" | "validated" | "blocked" | "active";
  stocks: Stock[]; parts: Part[]; joints: Joint[];
  operations: Operation[]; checkpoints: Checkpoint[];
  constraints: Record<string, unknown>;
  compilerVersion: string; createdAt: string;
}
interface PhysicalEvent {
  id: ID; projectId: ID; versionId: ID; operationId?: ID;
  kind: "operation_confirmed" | "observation" | "measurement" | "damage" | "test";
  evidenceIds: ID[]; recordedAt: string; actor: "user" | "system";
  observation: string; verificationState: VerificationState;
}
interface AdaptProposal {
  baseVersionId: ID; proposedPlan: BuildPlan;
  preservedOperationIds: ID[]; undoOperations: Operation[];
  newlyRequiredOperations: ID[]; invalidatedCheckpointIds: ID[];
  stockDelta: Record<ID, number>; constraintsSatisfied: boolean;
  compilerErrors: string[]; rationale: string;
}
```

**Schema rules:** Use Pydantic as backend source of truth; export OpenAPI/JSON schemas; generate TS types. Every model output and API mutation gets runtime validation. Replace generic `args` with a closed discriminated union for actual implementation; it's shown compactly here only for readability. IDs are never reused. No recursive schema in Meta structured-output requests; flatten to bounded outputs.

### 5.2 Three separate truths

1. **Plan truth:** `BuildPlan(vN)`—what the system recommends and expects.
2. **Execution truth:** confirmed physical events—what the person reports doing, in chronological order.
3. **Evidence truth:** images, measurements, tests, and interpretations—with provenance and confidence *categories*, never uncalibrated numeric probabilities.

A new plan version never erases older physical events. An event may be **obsolete for the current plan** while remaining historically true.

### 5.3 Revision transaction

1. Snapshot active version and confirmed physical events.
2. Generate **candidate patches** through bounded model output (prefer operations, not whole-graph freeform rewrites).
3. For each patch, apply to a *copy* of the plan; run schema, stock, geometry, accessibility and supported-profile checks.
4. Compute changed parts/constraints and transitive invalidation through operation and checkpoint dependencies.
5. Determine whether completed work is compatible with the new plan. Preserve compatible actions; specify physical undo for incompatible ones; fail if irreversible operations cannot be undone under the available materials.
6. Compute repair cost (see below) and select best *feasible* proposal; request manual confirmation for physical unknowns.
7. Show diff with explicit: `kept`, `redo`, `undo`, `consumed/wasted`, `new stock`, `recheck`, `cannot recover`.
8. On user approval, atomically commit `vN+1`, associated transactions and evidence invalidations. If rejected, keep current version and logs unchanged.
9. Re-render panels whose **render dependency hashes** changed, not all panels just because a version number changed.

### 5.4 Repair objective and guardrails

For feasible candidate `c`, minimize:

```text
repair_cost(c) =
    5 * count_irreversible_completed_actions_lost(c)
  + 3 * count_required_physical_undos(c)
  + 2 * count_new_irreversible_actions(c)
  + 1 * estimated_extra_minutes(c)
  + 1 * material_waste_fraction(c) * scale
  + 1 * estimated_new_purchase_cost(c) / reference_budget
```

**These weights are initial heuristics, not learned or validated preferences.** The compiler must first reject hard constraint failures. Do not rank an impossible candidate using this score. Print both cost terms and the resulting human-understandable reasons.

**Tie-break:** prefer fewer unknown physical checks and fewer new cuts. Preserve user agency; never automatically command disposal of completed parts.

### 5.5 Cache invalidation

- Diagram key: `renderer_version + camera + operation + part geometries + visible joint states + style`.
- Generated image key: `source_diagram_hash + prompt/style version + reference_image_hash + image_model_id`.
- Evidence key: `checkpoint + observed part/feature IDs + plan version dependencies`.
- Reuse unaffected SVG/image panels across graph versions. A rendering cache hit is **not** evidence that a physical checkpoint remains valid.

---

## 6. Muse and Meta AI integration — exact responsibilities

**Base API URL:** `https://api.meta.ai/v1`. Set `MODEL_API_KEY` on the server only. Do not assume the account has access or credits until a live authenticated test passes. Current model IDs below are documented as of October 30, 2026; override via environment configuration, never scattered hardcoded strings.

| Model | ID | Core role | Required at submission? |
|---|---|---|---|
| Muse Spark | `muse-spark-1.3` | Multimodal interpretation, typed candidate design/repair, diagnostic questions, bounded tool reasoning | **Yes** |
| Segment Anything Model | `sam-3.1` | Pixel masks / boxes for an inventory item or discrepant component | **Target P0**; manual review fallback |
| Muse Image | `muse-image-1.0` | Attractive, reference-grounded assembly illustrations **only after deterministic render**, never geometry | **P1** (demo enhancement) |
| Muse Voice Transcribe | `muse-voice-transcribe-1.0` | Spoken problem descriptions and hands-free stuck questions → transcripts | **P1** |
| Muse Glimmer (open weights) | 30B family, exact checkpoint from official docs | Potential local specialized verifier or failure triage | **P2**; not needed for deadline |
| Muse Spark Open (open weights) | 816B total / 42B active MoE | Longer-term hosted/self-run research | **Out of MVP**; hardware burden inappropriate |

### 6.1 Muse Spark 1.3 — what gets delegated

**Call A — `interpret_intake`:** Given user goal, stock photos, visible proposals, manually confirmed dimensions and constraints, return `GoalSpec`, `CandidateInventory[]`, missing questions. All image-derived dimensions must have `source=unknown` until confirmed.

**Call B — `propose_design`:** Return at most two `DesignCandidate` records from the supported family. Parameters include support angle, panel count, part sizes, stock allocation preferences, joint profile IDs, and explicit assumptions. Reject unknown operation names.

**Call C — `diagnose_failure`:** Given image, current step, expected diagram, inventory and execution events, separate:
- `visible_observations`: e.g., "slot appears torn";
- `hypotheses`: e.g., "slot may be too close to edge";
- `questions_or_measurements`: what would distinguish hypotheses;
- `proposed_failure_type` and affected IDs, with explicit uncertainty.

**Call D — `propose_adaptation`:** Given a **structured snapshot** and a confirmed problem, return up to 3 typed candidate patches. Model cannot invent resources, rewrite completed physical events, or claim the user performed an action.

**Call E — `explain_revision`:** Explain compiler-approved patch in simple language, with preserved work, undo, new material, and rechecks. No unsupported safety guarantees.

**Model routing:** One model with narrow typed prompts and function permissions, rather than nine autonomous personas. A reviewer prompt can critique a candidate **only if** the deterministic validator passes or exposes specific weaknesses. Tool calls are capped (default 4 total model/tool rounds per request) and instrumented.

**Reasoning budget:** Standard effort for simple parsing and explanations, higher effort for a complicated repair *only if latency/cost allows*. Structured output (`response_format` with JSON Schema on Chat Completions; `text.format` on Responses API) constrains syntax; it does **not** guarantee physical truth. Tool calls must be executed on the server after parameter validation.

### 6.2 SAM 3.1 — segmentation, not structural judgment

Use **one concept per request** or box/point prompts to segment a specified object. Hosted SAM accepts image/video through Responses API and returns masks/bounding boxes; use the official output parser when appropriate.

**P0 practical flow:** User photographs stock and marks "this cardboard sheet" or "this torn section". SAM produces a polygon/overlay that the user confirms or corrects. The region can support inventory review and crop selection, but it **cannot establish thickness, exact dimensions without scale, hidden geometry, or structural safety**.

**Fallback:** user draws a box and labels object manually; Spark can still reason over the cropped photo. Keep this path fully functional if SAM is unavailable, slow, or segments the wrong object.

**Track identity:** Do not confuse tracked objects across new photos. Maintain explicit user-linked part IDs. Continuous video tracking is post-hackathon.

### 6.3 Muse Image — appearance separated from instruction authority

The default manual is **fully usable without Muse Image**: clean SVG line art, labeled parts, arrows, fold and cut indicators, numeric dimensions, and checkpoints. Once stable, Muse Image generates one or several reference-guided presentation illustrations of the expected state.

**Input:** Single authoritative SVG/PNG render + exact visible part list + fixed camera framing + style brief + "do not add/remove parts or move connections." **Output:** enhanced illustration with no measurements baked in.

**QA:** Compare against authoritative SVG and part masks / manual check. If a part count, orientation, joint location or dimension appears altered, discard enhancement and show deterministic SVG. UI clearly labels generated artwork as illustrative. An image-edit response cannot be treated as a pixel-perfect patch.

**API caveat:** Muse Image uses the Responses API with an `image_generation` tool. Its documented image-edit endpoint **does not support the `mask` parameter**; do not build masked-inpainting dependencies. Disable unnecessary model-side web/image search for private technical diagrams where supported. Keep labels/measurements as programmatic overlays.

### 6.4 Muse Voice Transcribe — optional hands-free input

Use documented file transcription (`POST /v1/asr/transcribe`) or real-time WebSocket (`wss://api.meta.ai/v1/asr/realtime`). It produces **speech-to-text**, not voice synthesis. Voice output can use browser speech synthesis, but must not block the text interface. Prefer file transcription/push-to-talk over full-duplex "phone call" under deadline pressure.

**Model nuance:** Muse Spark 1.3 documentation warns audio understanding is not fully supported; route raw audio to Muse Voice Transcribe rather than assuming 1.3 handles streaming voice as well as text/images.

### 6.5 Open-weight Meta models: realistic boundary

Muse Glimmer is a 30B multimodal open-weight option suited to post-hackathon local specialization. Muse Spark Open is an 816B-total-parameter MoE and is **not** a sensible 6-day local fine-tuning target. If fine-tuning later, choose a narrow task (e.g., categorize assembly discrepancy from photo + step context), curate consented labels from **different builds**, split train/test by physical build, and compare against base-model inference. Never claim LoRA on a text model solves segmentation or material safety.

### 6.6 Day-0 model compatibility checklist

- [ ] Account and geographic use permitted; key works from the actual deployment region.
- [ ] Authenticated Muse Spark **image + text** response returns a typed inventory proposal.
- [ ] Structured output round-trip with validator; tool call invokes deterministic checker.
- [ ] SAM call returns mask/box on a **real team photo**, not only documentation examples.
- [ ] Muse Image reference-guided generation/edit test succeeds if P1 is pursued.
- [ ] Voice transcription on a short Spanish/English sample if P1 pursued.
- [ ] Record actual latency, errors, approximate tokens and cost for all calls.
- [ ] Confirm privacy mode (Standard vs Contributor), quotas and any credits in dashboard.
- [ ] Record exact endpoints, model IDs, SDK version, request/response samples in `docs/model-compatibility.md` with sensitive fields removed.

### 6.7 Costs and operational discipline

Current public Standard pricing is token-based for Spark, per-image for SAM, per-generated-image for Muse Image, and per-audio-hour for Voice; **recheck the official pricing page immediately before submission**. Do not state a per-build cost until a real end-to-end trace exists. Add budgets by project/job, cache identical perception requests, cap retries, and log `model_id`, latency, token/image counts, and errors. Strip API keys, personal content and identifiable photos from public logs. Contributor mode may permit Meta training on submitted content; use Standard by default unless users deliberately consent and the team chooses otherwise.

---

## 7. Planning and repair protocol

### 7.1 Bounded agent pipeline (not nine subagents)

```text
intake text/photos
  → Spark interpretation + user confirmation
  → family-bound design candidate generation (max 2)
  → deterministic compilation / rejection reasons
  → user selects valid plan
  → operations + SVG manual + checkpoints
  → user builds / commits physical events
  → photo + Spark diagnosis (observed vs hypothesized)
  → ask targeted measurement if necessary
  → Spark proposes max 3 patches
  → deterministic validation + repair-cost ranking
  → user approves candidate diff
  → atomic version commit + re-render affected steps
  → user physically verifies outcome
```

**Compiler is authoritative, not the judge of real-world physics.** Whenever code cannot verify a premise (e.g., actual tab grip), the plan must require a manual check rather than silently pass.

### 7.2 Tools exposed to Muse Spark

| Tool name | Inputs | Returns | Rule |
|---|---|---|---|
| `get_project_snapshot` | project ID | version + inventory + events | read-only |
| `get_supported_joint_profiles` | material/operation filters | tested profiles and limits | never invent profiles |
| `simulate_patch` | base version, typed patch | check results, stock changes, cost, diagram hashes | **no commit** |
| `request_measurement` | part, property, why needed | UI measurement prompt | cannot fabricate result |
| `request_photo` | step / target | upload requirement | cannot fabricate image |
| `explain_validator_error` | code, context | human-readable explanation | no override authority |
| `propose_alternate_inventory` | constraints | needed physical purchase/stock | must mark unavailable |

The model has **no direct `commit_plan`, `mark_operation_completed`, or `record_test_pass` tool**. Only authenticated user action and server validation may do so.

### 7.3 Candidate rejection and stopping

- 3 repair candidates max; bounded tool rounds; no hidden infinite retry.
- If all fail checks, report exact blockers and either ask for a measurement or identify required new stock.
- If physical uncertainty is high, request a new photo, ruler measurement, or manual fit test; do not hallucinate certainty.
- If request crosses the safety boundary, stop with a helpful explanation; no fallback design that hides the risk.
- Allow user to choose a less elegant but feasible repair only if hard constraints pass.

### 7.4 Example (for unit fixture; **not a scripted production branch**)

```json
{
  "event": "damage_reported",
  "plan_version": "v1",
  "current_operation": "op-slot-03",
  "user_text": "The tab tore this slot and I still have tape and a spare strip.",
  "observed": ["visible tear near slot", "tab no longer holds"],
  "unverified": ["remaining sheet strength", "actual tape length"],
  "allowed_adaptation": {
    "candidate": "replace_slot_joint_with_brace_joint",
    "preserve": ["op-cut-base", "op-fold-back"],
    "requires": ["measure-spare-strip", "assemble-brace", "tape-joint"],
    "invalidate": ["slot-fit-check", "previous-stability-check"]
  }
}
```

This is a **test case**, not proof that the patch is physically feasible. The real implementation must verify stock, access and geometry and require a final load test.

---

## 8. Manual rendering: a consistent "assembly instruction" experience

**Style:** Precise, minimal, high-contrast, paper-white technical panels with neutral materials and restrained accent color. Isometric or orthographic views with consistent pose and exploded placement, intuitive arrows, part-number chips, recognizable fold/cut symbols. Inspired by the clarity of modular toy instructions, **not using LEGO branding, proprietary instructions, or copied assets**.

### Authoritative pipeline

1. `BuildPlan` → select operation and preceding expected state.
2. Generate 2D/2.5D geometry from the measured parts and joint feature metadata.
3. Render SVG using stable coordinates/camera and overlay part IDs, cut/fold lines, tools, dimensions, arrows, remaining-stock mini-map.
4. Check diagram includes exactly the expected parts for the step; link each symbol to its operation/part ID.
5. Render HTML step details and explicit checkpoint acceptance criteria.
6. Optionally feed deterministic render into Muse Image for a **separate decorative panel** with fail-safe fallback.

**No independent per-step prompting without a shared scene source.** This avoids step-to-step part mutations. A visual revision is derived from changed model geometry. Cached unchanged steps remain byte-identical where render inputs are identical.

### Manual screen per step

- Title: `Step 04 / 09 — Attach rear brace`.
- Parts required, source stock IDs, tools and estimated time (clearly estimated).
- Diagram showing current state, target state, and single action.
- Exact dimensional annotations generated by code, where available.
- Warnings before cutting/permanent joining; confirm measurement.
- Expected result and `Verify` action, including whether it needs photo, ruler, touch/fit or functional test.
- Controls: Previous, Next, I'm stuck, Report material issue, View remaining inventory.
- `Adaptation available` state when build differs from plan; never auto-advance an unverified irreversible step.

---

## 9. FORMA Adapt — the real differentiator

### Failure classes (supported P0)

| Failure | Evidence | Potential response | Explicit refusal condition |
|---|---|---|---|
| Missing connector | Confirmed inventory change | swap tested compatible joint type | no compatible join method remains |
| Wrong measured dimension | User measures critical part | resize future parts or change geometry | required cut already irreversible and no stock to recover |
| Damaged slot / torn panel | Photo + user confirmation | brace, move connector, replace damaged part | damage affects unsupported load path |
| Material shortfall | Consumption ledger | use salvage/offcuts; request purchase | no usable stock and purchase not allowed |
| Unclear photo | low visual evidence | targeted photo / manual check | cannot diagnose safely from available info |
| Unsafe or impossible proposal | hard constraint check | explain and stop | always block; no fabricated fix |

### What adaptation must visibly show

```text
Original version: v1
Reason: rear-panel tab-slot joint damaged at step 4
Completed before failure: 3 operations
Preserved: 2 operations (base cut, back fold)
To undo: 1 reversible action (remove detached tab)
Added: 2 operations (cut replacement brace from remaining offcut; attach with tape)
Lost material: 1 damaged tab (identified source stock)
Checks to repeat: joint grip, stand stability
Updated panels: steps 4–6 only
Requires user approval before activation
```

The numbers above illustrate the UI format; **do not display them as measured demo results**. Real quantities must be computed from actual events and plan versions.

### Repair correctness properties

- Every preserved operation refers to unchanged relevant part/feature geometry and valid prerequisites.
- If a previously completed cut is incompatible with the new geometry, either account for replacement stock or reject patch.
- Material consumed in v1 is unavailable in v2 unless a specific salvage event returns a usable offcut.
- No previously passed checkpoint remains valid if its predicate depends on changed geometry, joint or material.
- Replacing an operation does not silently mark it completed.
- An accepted version either has a consistent continuation or is blocked with reasons.

---

## 10. FORMA Proof — evidence, not invented certainty

**Definition:** A versioned build history connecting planned physical operations to observed actions, photos, measurements and final function checks.

### Evidence categories

| Category | Example | Can FORMA claim it happened? |
|---|---|---|
| `user_confirmed` | User taps "cut complete" | Yes, **as user-reported** |
| `vision_observed` | A brace looks attached in the photo | Yes, **as visible appearance** |
| `manually_measured` | Ruler shows measured width | Yes, with method and provenance |
| `functional_test_passed` | User tests support for specific device and reports pass | Yes, **for that defined test only** |
| `model_hypothesis` | "The slot may have weakened due to edge distance" | No, hypothesis only |
| `unknown` | Hidden joint grip, material tensile strength | No |
| `invalidated` | Previous stability check after altered brace | Must be repeated |

### Mandatory checkpoints (hero family)

1. Actual stock dimensions confirmed before cutting.
2. Cut panel size measured or confirmed after cutting.
3. Joint fit tested manually, not inferred from pixels.
4. Device/stand stability tested after final assembly using defined test conditions.
5. Recheck of every checkpoint affected by revision.
6. Final photo and outcome note (pass/fail; no forced success).

**Report fields:** goal, dated version history, inventory used/wasted/salvaged, all operation statuses, changed parts, requested measurements, per-test results, photos (if sharing consented), final open risks, build duration (measured if recorded), and environment/physical device used for functional test.

---

## 11. Persistence, privacy, security and reliability

### Data storage

| Entity | Storage | Notes |
|---|---|---|
| Project and scope/constraints | PostgreSQL | JSONB typed versions acceptable for MVP |
| Inventory and material transactions | PostgreSQL | Immutable transaction events |
| Plan versions + patches | PostgreSQL | append-only, optimistic version check |
| Physical events and checkpoints | PostgreSQL | never silently rewrite evidence |
| Photos and generated diagrams | S3-compatible object store (or local disk in dev) | private by default; content-address where useful |
| Model traces/metrics | DB / structured logs | strip secrets, mask private media URLs |

**Local dev fallback:** SQLite and local assets are acceptable if setup/hosting would otherwise delay physical tests, provided data model semantics are preserved. Avoid introducing Redis, job queues and background workers solely to look enterprise-scale. In-process jobs with persisted status and sane concurrency caps are enough for P0; use ARQ + Redis only if actual load or timeout demands it.

### Privacy and safety

- No public display of private homes, faces, addresses, student data, or room photos by default.
- Informed consent before sending private photos/audio to hosted Meta endpoints and before sharing examples publicly.
- Provide deletion of project/media and retention controls within MVP capabilities; document any external API retention limitations accurately.
- Standard non-training mode for sensitive user inputs by default; do not silently choose Contributor mode for a discount.
- Secure file upload: allowlist MIME types, byte limits, image decoding checks, random IDs, signed/private URLs, auth checks.
- Never expose `MODEL_API_KEY` to browser; prohibit prompt-to-shell execution and arbitrary model-authored code execution.
- Rate limits, input size constraints, model retries with exponential backoff, request timeouts and server-side cost limits.
- Treat image captions, uploaded text and model output as untrusted. Typed tool allowlists only; models cannot access unrelated projects or mutate logs.
- Safety stop for excluded devices/materials; explicit hand-tool risks and user confirmation before sharp-tool cuts.

### Failure handling

| Failure | Behavior |
|---|---|
| Spark unavailable | Let user inspect existing validated manual, edit inventory and review previous versions; no fabricated new adaptation |
| SAM inaccurate/unavailable | Manual box and label; do not block project |
| Muse Image inconsistent/unavailable | Display authoritative SVG and skip generated art |
| Missing critical measurement | Ask for ruler/scale, block cut and repair approval until confirmed |
| Infeasible model proposal | Show compiler reasons; retry bounded number; request new stock or stop |
| Upload/network interrupted | Keep saved operation events; retry idempotently; show status accurately |
| Revision conflict | Reject stale write, reload base version, ask to re-review diff |
| Physical test fails | Mark failed, reopen diagnosis; never mark project complete |

---

## 12. API contracts and workflow state machine

### REST endpoints (suggested)

```text
POST   /api/projects                        create project with goal and scope
GET    /api/projects/{id}                   project, active version, state
POST   /api/projects/{id}/photos             upload image metadata / signed URL
POST   /api/projects/{id}/interpret          async intake interpretation
PATCH  /api/projects/{id}/inventory          user confirms materials/measurements
POST   /api/projects/{id}/candidates         generate family-bound candidates
POST   /api/projects/{id}/compile            validate/build candidate, render manual
GET    /api/projects/{id}/versions/{v}       immutable version + compiler report
GET    /api/projects/{id}/manual/{v}         SVG steps, BOM, checkpoints
POST   /api/projects/{id}/events             record user operation/measurement/check
POST   /api/projects/{id}/diagnose           photo + current step → observations/questions
POST   /api/projects/{id}/adapt/simulate     candidate patches + validation + diff
POST   /api/projects/{id}/adapt/commit       explicit approval + expected base version
POST   /api/projects/{id}/functional-test    evidence and defined result
GET    /api/projects/{id}/proof              versioned evidence report
GET    /api/jobs/{id}                        status, trace ID, errors (no secrets)
GET    /api/health                           dependency readiness
```

**Write safeguards:** All mutations have authenticated project scope and idempotency key. `adapt/commit` requires expected active `version_id`; reject stale writes with `409`. Confirm irreversible operation events at the client and validate allowed predecessor states on the server.

**State machine:**

```text
DRAFT → INVENTORY_CONFIRMED → DESIGN_PROPOSED → VALIDATED → BUILDING
                                                   ↘ BLOCKED (explain why)
BUILDING → DIAGNOSING → REVISION_PROPOSED → REVISION_APPROVED → BUILDING
                  ↘ NEEDS_MEASUREMENT / UNSUPPORTED / NO_FEASIBLE_REPAIR
BUILDING → TESTING → COMPLETE (only on defined functional test passed)
                  ↘ FAILED → DIAGNOSING
```

**Job states:** `queued`, `running`, `waiting_for_user`, `succeeded`, `failed`, `cancelled`. Expose timestamps and a safe error code; never claim a tool operation succeeded before a verified result.

---

## 13. Repository, engineering standards and task ownership

```text
forma/
  formspec.md                         # THIS document; source of truth
  README.md                           # 90-second setup, run, test, demo
  .env.example                        # never credentials
  apps/
    web/                              # Next.js/React mobile workbench
      src/app/
      src/components/{inventory,manual,adapt,proof}/
      src/lib/api.ts
    api/                              # FastAPI app + Meta gateway
      src/forma_api/{routes,services,models,providers}/
      tests/
  packages/
    domain/                           # Pydantic domain model + schemas
    compiler/                         # stock, operations, joints, graph checks
    replanner/                        # candidate patches, preservation, undo
    renderer/                         # authoritative SVG generation
    eval/                             # harness, scoring, baseline comparisons
  fixtures/
    inventory_A.json
    inventory_B.json
    missing_connector.json
    damaged_slot.json
    size_mismatch.json
    impossible_request.json
  data/
    physical-tests/                   # redacted measurements + results
  docs/
    model-compatibility.md
    joint-profiles.md
    evaluation-protocol.md
    demo-script.md
    decisions.md
  scripts/
    smoke_meta.py
    run_evaluation.py
```

**Pragmatic repo simplification:** If two engineers move faster in a single Next.js+Python monorepo without separate packages, keep the conceptual boundaries and tests, not the exact folder depth.

### Working agreements

- Assign one owner per module and one reviewer for compiler-affecting changes.
- Commit per working vertical slice; no giant "everything at once" PR.
- Validate all schemas; make material and graph mutations pure/deterministic wherever possible.
- Seed reproducible fixtures. Add unit tests for every hard constraint and bug found in a real build.
- Treat all prompts as versioned source; log model and prompt version for every proposal.
- No speculative nine-agent framework, unnecessary microservices or premature infra complexity.
- Never claim a fixture test proves physical feasibility; attach physical evidence and conditions.
- Avoid changing production model IDs, schema contracts and joint profiles without smoke tests.
- All tests reproducible with no API key except separately marked model integration tests.

---

## 14. Evaluation: the difference between a polished demo and evidence

### 14.1 Primary questions

1. Can FORMA produce a valid plan **without allocating more stock than exists**?
2. Can a novice follow the deterministic manual to construct a functioning object?
3. Given an actual material failure, can the system produce a **validated continuation** that preserves correct previous work?
4. Does it reject an impossible or unsafe request instead of offering a fictitious fix?
5. Does FORMA outperform reasonable alternatives on comparable tasks?
6. Do Meta models contribute to interpretation/repair rather than merely generate decoration?

### 14.2 Minimum physical evaluation matrix

Two distinct confirmed inventory configurations (`A`, `B`) × three perturbations:

| Case | A | B | Expected capability |
|---|---|---|---|
| Connector unavailable | A1 | B1 | alternative tested joint or honest stop |
| Dimension mismatch | A2 | B2 | reconcile cut geometry without double-spending stock |
| Damaged joint | A3 | B3 | repair or replace, invalidate affected checks |

Plus **one explicitly infeasible case** (e.g., no usable stock and purchases forbidden, or an irreversible wrong cut with no replacement). For a genuine test, select at least some variants **after the system is implemented** rather than designing all branches around known examples.

**Full physical builds target:** 2 successful completed objects (different inventories) + 1 successful unexpected recovery; run other scenarios as structured bench tests if time limits full builds. Report exactly which cases were simulated, compiler-validated, physically attempted and physically passed. **Never equate six fixture tests to six physical builds.**

**User study target:** Three makers observing/attempting the flow; at least one builder not on the engineering team, if available. Document actual counts and caveats.

### 14.3 Baselines — not straw men

| Baseline | Control | Comparison |
|---|---|---|
| **Generic single-prompt LLM** | Same problem/inventory, no build graph | step/stock errors, manual usability, recovery |
| **Iterative vision chat** | Same model allowed to inspect new photos and provide advice repeatedly | physical recovery success, total time and corrections |
| **Fixed parametric template** | One tested stand template with selectable dimensions | ability to handle constraints/failure and material efficiency |
| **FORMA** | Spark proposals + compiler + evidence + adaptation | above plus preserved-work percentage and failures |

Maintain comparable user information, model access where feasible, number of attempts and measurement conditions. State limits when time or sample size prevents controlled comparison.

### 14.4 Exact metrics and formulas

```text
physical_completion_rate = physically_completed_and_tested / physically_attempted
recovery_success_rate   = successful_recoveries / recovery_attempts
valid_patch_rate        = candidate_patches_passing_compiler / patches_evaluated
invalid_stock_uses      = count of allocations with oversubscribed consumed stock
incorrect_preservations= count of completed operations wrongly kept after incompatibility
preservation_rate       = compatible_completed_operations_preserved / compatible_completed_operations
repair_elapsed_minutes  = time from failure submission to verified resumed/finished step
material_waste_ratio    = physically unusable material area / starting usable sheet area
manual_corrections      = times human amended generated instructions
question_count          = user clarifications and measurements requested per adaptation
visual_panel_mismatch   = changed/additional/missing parts in image vs. deterministic render
```

For `preservation_rate`, define compatibility using a documented adjudication method (compiler + human physical check), not compiler output as its own ground truth. Report **numerator and denominator** for every rate. Never present subjective model-confidence values as calibrated probabilities.

### 14.5 Quality gates (planning targets, not results)

| Gate | Minimum requirement to claim demo success |
|---|---|
| **G0: Meta** | Real Spark call + schema/tool round-trip; SAM tested on actual photo or documented fallback |
| **G1: Compiler** | 100% of known impossible cuts and oversubscription fixtures rejected; no hidden mutation of physical events |
| **G2: Physical build** | One real assembled functioning object + recorded test, without manually inventing untracked steps |
| **G3: Adapt** | One non-hardcoded physical failure repaired with visible graph diff, preserved work, correct stock ledger and rechecks |
| **G4: Generalization** | A second inventory or held-out substitution **and** one impossible case handled honestly |
| **G5: Submission** | Hosted demo + recorded backup + source/repro guide + results with failure counts |

**Go/no-go:** If G2/G3 are not achieved by the end of October 31, stop adding features; either use a catalog of **physically tested templates with adaptation** (still FORMA) or drastically reduce the supported operations. Do not switch to an unrelated project without proven feasibility of its core real-world test.

### 14.6 Physical build log (required format)

```text
Build ID: ____   Inventory: A / B   Operator: ____   Date: ____
Object and dimensions: ____   tools/materials: ____
Plan version: ____   physical profile limits: ____
Start/end times: ____  First actual failure: ____
Photo/evidence files: ____   units/measurement method: ____
Model calls & human clarifications: ____
Original completed operations: ____
Preserved/undone/invalidated: ____
Additional material and stock source: ____
Repair accepted/rejected because: ____
Functional test: procedure ____ / conditions ____ / pass-fail ____
Baseline attempt: ____   caveats / remaining unknowns: ____
```

---

## 15. Execution plan — October 30 to November 4 (two engineers)

**Critical path:** tested joints + first real assembly → deterministic compiler → real repair → measured outcome → polish. Physical experiments begin on day 0. Do not wait until November 3.

| Date | Owner A — Physical compiler & evaluation | Owner B — Product & Meta | Concrete gate |
|---|---|---|---|
| **Oct 30 (Day 0)** | Select stand geometry; physically test 2–3 joint variants, document tools, tolerances, failure cases; build first crude physical object | Repo/UI shell; live Spark structured-output + SAM smoke tests; inventory intake | **G0; one real build attempt, joint test notes** |
| **Oct 31 (Day 1)** | Stock allocation, operation model, validators, SVG manual; physically attempt an unexpected joint failure and repair | Spark design + diagnosis + typed patch; inventory confirmation; adapt review skeleton | **G2/G3 decision gate: real build and repair** |
| **Nov 1 (Day 2)** | Replanner preservation/undo, evidence invalidation, impossible fixtures; second inventory attempt | Manual viewer, checkpoint events, compare before/after patch UI; work through real photos | End-to-end revision transaction works |
| **Nov 2 (Day 3)** | Run matrix cases, test baseline methods, fix uncovered invalid geometry | Photo troubleshooting + SAM overlay, polish mobile; optional reference-grounded Muse Image panel | Held-out failures + impossible case documented |
| **Nov 3 (Day 4)** | Final independent build, performance/robustness tests, captured metric table | Deployment, presentation, demo footage, user study if possible, optional voice only if safe | Real measured result + final video draft |
| **Nov 4 (Day 5)** | Regression, evidence reconciliation, README/repro and joint-profile documentation | Submit demo/project; verify links/auth; backup recording and screenshots | **Submission before 9 PM ET** |

### 15.1 Time allocation / priority

- **45%**: real-world build experiments, inventory/operation correctness, graph repair.
- **25%**: actual user flow and dependable SVG manual.
- **15%**: Meta perception/diagnosis integration and debugging.
- **10%**: controlled evaluation + demo recording.
- **5%**: contingency and optional visual polish.

Percentages are suggested team allocation, not a claim of tracked time. Keep a deployment/submission buffer on Nov 4.

### 15.2 Ordered cut list if behind

1. Community/public design library, marketplace, purchases, persistence across unrelated projects (already out).
2. Fine-tuning and local open-weight deployment.
3. Voice/video calling and real-time tracking.
4. Generative illustration enhancement beyond a single panel.
5. Extra design families and 3D model view.
6. Multi-variant concept cards; keep one validated candidate plus an alternative if possible.
7. SAM overlays if they don't improve a real diagnosis (keep Spark and manual image correction).

**Never cut:** measured stock, deterministic diagrams, validated operations, actual physical test, real repair, preservation/undo tracking, infeasible-case behavior, demo evidence, and a meaningful Meta reasoning loop.

---

## 16. Judge-facing demonstration (target 2:30–3:00)

| Time | What the viewer actually sees | What it proves |
|---|---|---|
| **0–15s** | A real desk problem + scraps in hand; no ideal kit | Real problem, real inventory |
| **15–40s** | Photo upload, user corrects stock dimensions; Spark interprets goal, compiler produces plan | Multimodal input and grounded constraints |
| **40–65s** | Authoritative illustrated manual and physical construction in progress | Assembly instructions are linked to physical actions |
| **65–95s** | A selected unexpected failure on camera; user uploads photo; Spark reports evidence and asks for missing info if needed | Real-world discrepancy diagnosis |
| **95–125s** | Compiler rejects/accepts candidates; visible diff: kept steps, undo, stock cost, rechecks; updated panel | **Adapt is not a chat response** |
| **125–155s** | Builder performs actual repair and a named functional test | Measured physical result |
| **155–175s** | Second inventory, infeasible case, tiny honest evaluation table | Generalization and trustworthy boundaries |

**Opening hook:** "Tutorials assume you have the right parts. Real life doesn't. FORMA updates the build when the materials—and the build itself—change."

**The magic moment:** Put the half-built object beside the old and new manuals. Show the same existing base kept, a different joint/brace attached, and the final object passing a user-performed test. Say exactly which physical work was preserved.

**Live judge perturbation:** If possible, let a judge select one of **multiple genuinely supported** disruptions. Don't promise arbitrary real-time repair from any material. Have a working recording as backup, clearly labelled as recorded; never misrepresent prerecorded video as an uncut live test.

**Show on screen:** elapsed time and model/tool latency from actual logs, compiler reasons, plan diff, original photo, physical test outcome, version IDs, and a transparent list of failures. Never invent before/after improvements or success rates.

**Pitch (short):**

> "What if anyone could build useful things from the materials they already own—and the instructions changed when the real world didn't cooperate? FORMA turns a messy inventory into a validated assembly plan and a visual manual. When a part fails, Meta's multimodal models understand what changed; our assembly compiler checks feasible repairs, preserves completed work, and rewrites only the remaining build. We demonstrate that on a real object, not just a render."

### Judging risk checklist

| Judge question | Answer supported by evidence, not marketing |
|---|---|
| "Isn't this just Gemini Live or an LLM tutorial?" | Show typed physical operations, inventory transactions, versioned preservation, an objectively invalid patch rejected |
| "Are your generated pictures consistent?" | SVG is authoritative; Muse Image is optional and must pass QA |
| "Does the object really work?" | Show raw physical test conditions and outcome |
| "Is the adaptation hardcoded?" | Test held-out perturbation + impossible case; expose compiler traces |
| "How can you know it is safe?" | You cannot infer structural safety from photo; scope low risk, test physically, state limits |
| "Why Meta?" | Spark proposes grounded repair from conflicting image/plan constraints; SAM isolates evidence; other components are deterministic validators |
| "Why nine agents?" | There are no nine mandatory agents; bounded reasoning and explicit compiler contracts |
| "What if it fails?" | Show rejection, exact blocking constraint, manual measurement request, and no fake success |

---

## 17. Release, acceptance criteria and submission package

### Definition of done

- [ ] One real user problem and the initial audience described without invented market validation.
- [ ] User can create a project, upload a real inventory photo and correct materials/dimensions.
- [ ] Meta Spark request truly runs and its output feeds typed design/repair proposal validation.
- [ ] At least one SAM segmentation works in the demo flow **or** limitation honestly documented and manual fallback works.
- [ ] No invalid stock allocation, unsupported operation or impossible geometry silently passes known fixtures.
- [ ] One mobile-readable deterministic manual with part IDs, cuts, joins, and checkpoints.
- [ ] One real physical object built through those steps with attached evidence.
- [ ] One real unexpected failure leads to a validated revision and a completed physical repair.
- [ ] Revision report correctly identifies preserved work, physical undo/rework, additional stock, and invalidated checks.
- [ ] One infeasible case is rejected with concrete reasons.
- [ ] Second inventory/build documented if physically completed; do not mark planned tests as passed.
- [ ] Model latency/cost logs collected; failure conditions handled.
- [ ] Actual qualitative/quantitative results and baseline caveats are in README/demo.
- [ ] Submission and deployed links verified through the participant portal.

### Submission package

1. Deployed demonstration (demo account or public sandbox, no keys exposed).
2. 2.5–3 minute video with real physical construction and recovered failure.
3. GitHub repository or reproducible source package with documented setup, tests and fixture datasets.
4. `docs/model-compatibility.md` recording exact Meta calls and environment compatibility.
5. `docs/evaluation-protocol.md` plus redacted physical results with denominators and negatives.
6. Screenshots of old/new diagrams, plan diff, inventory ledger and observed test.
7. Short project summary/technical write-up explaining why Meta perception is necessary and where deterministic checks take over.
8. Contributor and media-consent information as required by organizer terms.

### Unresolved items to decide on day 0

- [ ] Which actual physical stand and supported material thickness range is the hero fixture?
- [ ] Which 2–3 joints pass a real bench test; what are their measured tolerances?
- [ ] Which exact inventories A/B are in hand and photographed?
- [ ] Where is the non-team user/builder available and what test can they perform?
- [ ] Do participant accounts have model access, allowed geography, approved team configuration and enough credit?
- [ ] Does Muse Image meaningfully improve illustrations without introducing misleading geometry? If not, omit.
- [ ] Is physical recovery possible for at least one held-out failure by October 31? If no, narrow immediately.
- [ ] What constraints are **physically verified** versus only simulated in software?

---

## 18. Official references (verified October 30, 2026)

**Hackathon and rules**
- Meta Global Hackathon: https://dev.meta.ai/events/global-hackathon
- Official page lists Indie track, themes, models, and November 4 9 PM ET submission deadline. Participant-specific terms/rules require dashboard review.

**Model API and contracts**
- Catalog and model IDs: https://dev.meta.ai/docs/models
- Meta API overview/base URL: https://dev.meta.ai/docs/overview
- Muse Spark structured output: https://dev.meta.ai/docs/cookbook/structured-output
- Muse Spark tool calling: https://dev.meta.ai/docs/cookbook/tool-function-calling
- Spark image understanding: https://dev.meta.ai/docs/image-understanding
- SAM 3.1 API and semantics: https://dev.meta.ai/docs/sam/overview
- SAM segmentation prompts: https://dev.meta.ai/docs/sam/segmenting
- SAM cookbook: https://dev.meta.ai/docs/cookbook/sam-api-basics
- Muse Image generation/editing caveats: https://dev.meta.ai/docs/image-generation
- Muse Image cookbook: https://dev.meta.ai/docs/cookbook/image-generation-basics
- Muse Voice transcription: https://dev.meta.ai/docs/cookbook/voice-api-fundamentals
- Muse Glimmer open-weight details: https://dev.meta.ai/docs/muse-glimmer
- Muse Spark Open: https://dev.meta.ai/docs/muse-spark-open
- Pricing/privacy modes: https://dev.meta.ai/docs/pricing-rate-limits
- Geographic/model designations: https://dev.meta.ai/legal/geographic-use-policy

**Internal inputs synthesized into this final document**
- Original `context.md`: FORMA's product vision, Build Graph, Adapt/Proof, design system and multi-model architecture.
- External reviewer `Pasted markdown(8).md`: requires real physical validation, explicit operation semantics, material conservation, preserved-work accounting, credible baselines, and honest refusal.
- `senal-spec(1).md`: serves as the structural/style template—clear problem, system invariants, bounded model responsibilities, deterministic engine, real-world measurement, milestones, evaluation, pitch guardrails.

---

## 19. First implementation handoff to coding agents

> **Read `formspec.md` completely before coding. This is the final project spec. Do not treat P1/P2 as mandatory. The core innovation is a physically tested plan revision preserving completed work. Build the deterministic compiler and one real vertical slice before UX embellishment or additional agents.**

**Owner A, first PR**
1. Create the typed inventory/part/operation/plan/event models and fixture inventory A.
2. Implement stock region allocation, non-overlapping cuts, kerf/margins, and clear compiler error codes.
3. Implement one tested stand geometry, at least one joint profile and SVG steps.
4. Add tests for oversubscription, out-of-bounds cut, duplicate stock use, missing part, impossible joint, stale checkpoint.
5. Physically assemble the exact generated stand; document differences and amend the compiler until it matches reality.

**Owner B, first PR**
1. Build project creation, real photo upload, inventory correction and manual step screens.
2. Create `model_gateway` with a live `muse-spark-1.3` structured image/text call and `sam-3.1` segmentation spike; save sanitized compatibility details.
3. Constrain design output to Owner A's typed operation/geometry contracts; never fabricate dimensions.
4. Implement diagnosis and adaptation review with preserved/undo/rechecks shown before commit.
5. Connect physical event tracking and photo evidence; exercise end-to-end on the real build.

**Shared first checkpoint:** One object physically built and then deliberately disrupted, with a **genuinely generated, compiler-approved repair** and completed physical recovery. Only then expand features.

**Nonnegotiable principle:** *Make the real world the benchmark. Make the compiler the constraint boundary. Make Meta the reasoning engine. Make the user the final verifier.*
