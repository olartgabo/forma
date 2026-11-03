"""Generate hypothetical construction from a finished target, then assess fabrication."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from forma_domain.generic_assembly import GenericAssemblyRequest
from forma_domain.stability_contracts import FiniteScalar
from forma_stability.generic_examples import assembly_example
from forma_stability.lab_assembly import AssemblyEditor, editor_request


class ShapeTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["box", "ramp", "triangle", "concave"]
    width_mm: Annotated[FiniteScalar, Field(gt=0, le=10000)]
    depth_mm: Annotated[FiniteScalar, Field(gt=0, le=10000)]
    height_mm: Annotated[
        FiniteScalar,
        Field(
            gt=0,
            le=10000,
            description="Vertical extent for box and ramp only. Triangle and concave targets are flat panels at z=0; height is not applicable.",
        ),
    ]


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shape: ShapeTarget | None = None
    editor: AssemblyEditor | None = None
    stage_index: Annotated[int, Field(strict=True, ge=0, le=63)] | None = None
    target: GenericAssemblyRequest | None = None
    synthetic_fabrication: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def one_target(self):
        if sum(v is not None for v in (self.shape, self.editor, self.target)) != 1:
            raise ValueError(
                "Choose a shape, a finished editor stage or a typed target"
            )
        if (self.editor is not None) != (self.stage_index is not None):
            raise ValueError(
                "An editor target requires exactly one selected finished stage"
            )
        return self


def shape_target(shape: ShapeTarget) -> GenericAssemblyRequest:
    request = assembly_example(shape.kind).model_dump(mode="json")
    extents = {
        "box": (0.2, 0.3, 0.1),
        "ramp": (0.2, 0.3, 0.2),
        "triangle": (0.2, 0.2, 1.0),
        "concave": (0.3, 0.3, 1.0),
    }[shape.kind]
    scale = (
        shape.width_mm / 1000 / extents[0],
        shape.depth_mm / 1000 / extents[1],
        shape.height_mm / 1000 / extents[2],
    )
    for part in request["assembly"]["parts"]:
        for facet in part["facets"]:
            for point in facet["vertices_local"]:
                for axis, factor in zip(("x", "y", "z"), scale):
                    point[axis] *= factor
    request["snapshot"]["assumption_notes"] = [
        "Invented target geometry: 100g per uniform panel, assumed rigid connections and full base contact. Dimensions do not establish material mass or strength. Generated stages are proposed states, not actual work."
    ]
    return GenericAssemblyRequest.model_validate(request)


def run_generation(payload):
    from forma_domain.construction_plan import ConstructionRequest
    from forma_stability.construction import generate_construction

    if not isinstance(payload, dict):
        raise ValueError("Provide a construction generation request")
    request = GenerationRequest.model_validate(payload.get("request", payload))
    if request.shape is not None:
        target = shape_target(request.shape)
    elif request.editor is not None:
        target = editor_request(
            dict(
                editor=request.editor.model_dump(mode="json"),
                stage_index=request.stage_index,
            )
        )
    else:
        target = request.target
    construction = generate_construction(ConstructionRequest(target=target))
    plan = report = None
    blockers = [
        "Fabrication has not been assessed: supply a reviewed material/process context, or explicitly opt into the invented lab fixture."
    ]
    if request.synthetic_fabrication:
        from forma_stability.construction_fabrication import build_fabrication

        assessment = build_fabrication(construction, allow_synthetic=True)
        plan, report, bindings, blockers = assessment
        if bindings:
            # Bind actual validated operation identifiers; construction evaluation
            # itself remains a proposal, not user-reported fabrication history.
            from forma_stability.construction import bind_operations

            construction = bind_operations(construction, bindings)
    return dict(
        label="Hypothetical generated construction; no operation has been completed or approved",
        request=request.model_dump(mode="json", exclude_none=True),
        construction=construction.model_dump(mode="json"),
        fabrication_plan=plan.model_dump(mode="json") if plan is not None else None,
        fabrication_report=report.model_dump(mode="json")
        if report is not None
        else None,
        fabrication_blockers=list(blockers),
        fabrication_basis="explicit_synthetic_fixture"
        if request.synthetic_fabrication
        else "not_assessed",
        target_note="Flat panel: width and depth define the shape; height is not applicable."
        if request.shape is not None and request.shape.kind in ("triangle", "concave")
        else "Finished target geometry; intermediate states are generated automatically.",
        fabrication_instructions=fabrication_instructions(plan)
        if plan is not None
        else [],
    )


def fabrication_instructions(plan):
    """Render actual operation arguments, without a second ordering authority."""
    parts = {p.id: p for p in plan.parts}
    output = []
    for op in plan.operations:
        if op.type == "cut_rect":
            panels = [parts[pid] for pid in op.args.child_part_ids]
            sizes = "; ".join(
                f"{p.id}: {p.geometry.width:g} x {p.geometry.height:g} mm at stock x={p.geometry.x:g}, y={p.geometry.y:g} mm"
                for p in panels
            )
            text = f"Cut {len(panels)} labelled rectangular panels from {op.args.stock_id}: {sizes}. Keep kerf {op.args.kerf_mm:g} mm and edge margin {op.args.edge_margin_mm:g} mm. Unallocated sheet material is waste unless explicitly retained. Check measurements and tools first."
        elif op.type == "tape_joint":
            text = (
                f"Connect {' and '.join(op.part_ids)} at {op.args.joint_id}, using {op.args.length_mm:g} mm of {op.args.stock_id}. "
                + " ".join(op.preconditions.human_checks)
            )
        elif op.type == "inspect":
            text = next(
                c.description for c in plan.checkpoints if c.id == op.args.checkpoint_id
            )
        else:
            text = (
                f"{op.type}: review the exact operation and its required confirmations."
            )
        output.append(dict(operation_id=op.id, instruction=text))
    return output
