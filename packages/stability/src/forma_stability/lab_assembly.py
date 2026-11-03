"""Friendly hypothetical panel editor adapter; geometry belongs to the producer."""

import math
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from forma_domain.models import ID, Text
from forma_domain.stability_contracts import FiniteScalar


class EditorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PanelState(EditorRecord):
    stage_id: ID
    translation_mm: tuple[FiniteScalar, FiniteScalar, FiniteScalar]
    rotation_deg: tuple[FiniteScalar, FiniteScalar, FiniteScalar]
    full_face_contact_assumed: bool
    rigid_body_assumed: bool


class EditorPanel(EditorRecord):
    id: ID
    label: Text
    vertices_mm: tuple[tuple[FiniteScalar, FiniteScalar], ...] = Field(
        min_length=3, max_length=64
    )
    mass_g: Annotated[FiniteScalar, Field(gt=0)] | None
    uniform_sheet_assumed: bool
    first_stage: Annotated[int, Field(strict=True, ge=0, le=63)]
    states: tuple[PanelState, ...] = Field(min_length=1, max_length=64)


class EditorStage(EditorRecord):
    id: ID
    label: Text


class EditorJoint(EditorRecord):
    id: ID
    first_panel_id: ID
    first_edge: Annotated[int, Field(strict=True, ge=0, le=63)]
    second_panel_id: ID
    second_edge: Annotated[int, Field(strict=True, ge=0, le=63)]
    first_stage: Annotated[int, Field(strict=True, ge=0, le=63)]
    rigid_assumed: bool


class AssemblyEditor(EditorRecord):
    panels: tuple[EditorPanel, ...] = Field(min_length=1, max_length=16)
    stages: tuple[EditorStage, ...] = Field(min_length=1, max_length=64)
    joints: tuple[EditorJoint, ...] = Field(default=(), max_length=32)
    required_margin_mm: Annotated[FiniteScalar, Field(ge=0)]


class EditorRequest(EditorRecord):
    editor: AssemblyEditor
    stage_index: Annotated[int, Field(strict=True, ge=0, le=63)]


def _transform(state):
    # Extrinsic X then Y then Z physical rotations: Rz @ Ry @ Rx.
    x, y, z = (math.radians(v % 360) for v in state.rotation_deg)
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    return dict(
        rotation=(
            (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
            (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
            (-sy, cy * sx, cy * cx),
        ),
        translation_m=dict(
            zip(("x", "y", "z"), (v / 1000 for v in state.translation_mm))
        ),
    )


def editor_request(payload):
    from forma_domain.generic_assembly import GenericAssemblyRequest

    request = EditorRequest.model_validate(payload)
    editor, index = request.editor, request.stage_index
    if index >= len(editor.stages):
        raise ValueError("Choose an existing stage")
    stage_ids = [s.id for s in editor.stages]
    if len(set(stage_ids)) != len(stage_ids):
        raise ValueError("Stage IDs must be unique")
    for panel in editor.panels:
        if panel.first_stage >= len(editor.stages):
            raise ValueError("Panel first stage is outside this assembly")
        ids = [s.stage_id for s in panel.states]
        if len(set(ids)) != len(ids) or not set(ids) <= set(stage_ids):
            raise ValueError("Panel states must uniquely reference declared stages")
    if any(j.first_stage >= len(editor.stages) for j in editor.joints):
        raise ValueError("Joint first stage is outside this assembly")
    parts, uniforms, contacts = [], [], []
    for panel in editor.panels:
        if panel.first_stage > index:
            continue
        state = next((s for s in panel.states if s.stage_id == stage_ids[index]), None)
        if state is None:
            raise ValueError(f"Supply a physical pose for {panel.id} at this stage")
        facet_id = panel.id + "-face"
        parts.append(
            dict(
                part_id=panel.id,
                mass_kg=None if panel.mass_g is None else panel.mass_g / 1000,
                center_of_mass_world=None,
                contacts=[],
                rigid_body_assumed=state.rigid_body_assumed,
                facet_poses=[dict(facet_id=facet_id, transform=_transform(state))],
            )
        )
        if panel.uniform_sheet_assumed:
            uniforms.append(panel.id)
        if state.full_face_contact_assumed:
            contacts.append(facet_id)
    value = dict(
        assembly=dict(
            project_id="editor-project",
            plan_version_id="editor-assembly",
            parts=[
                dict(
                    part_id=p.id,
                    facets=[
                        dict(
                            facet_id=p.id + "-face",
                            vertices_local=[
                                dict(x=x / 1000, y=y / 1000, z=0.0)
                                for x, y in p.vertices_mm
                            ],
                        )
                    ],
                    seams=[],
                )
                for p in editor.panels
            ],
            joints=[
                dict(
                    joint_id=j.id,
                    first=dict(
                        facet_id=j.first_panel_id + "-face", edge_index=j.first_edge
                    ),
                    second=dict(
                        facet_id=j.second_panel_id + "-face", edge_index=j.second_edge
                    ),
                )
                for j in editor.joints
            ],
            stages=[
                dict(
                    stage_id=s.id,
                    label=s.label,
                    present_part_ids=[
                        p.id for p in editor.panels if p.first_stage <= i
                    ],
                    active_joint_ids=[
                        j.id for j in editor.joints if j.first_stage <= i
                    ],
                )
                for i, s in enumerate(editor.stages)
            ],
        ),
        stage_id=stage_ids[index],
        snapshot=dict(
            project_id="editor-project",
            plan_version_id="editor-assembly",
            inventory_revision="editor-hypothetical",
            history_cursor=None,
            completed_operation_ids=[],
            basis="hypothetical",
            support_frame=dict(
                rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                translation_m=dict(x=0.0, y=0.0, z=0.0),
            ),
            gravity_world_m_s2=dict(x=0.0, y=0.0, z=-9.80665),
            parts=parts,
            rigid_joint_ids=[
                j.id
                for j in editor.joints
                if j.first_stage <= index and j.rigid_assumed
            ],
            assumption_notes=[
                "Hypothetical editor inputs, not observed work. Opt-in uniform source mass and full-face contact assumptions. Standard gravity is assumed; no connector mass is inferred."
            ],
        ),
        policy=dict(
            policy_id="editor-policy",
            version="v1",
            length_tolerance_m=1e-9,
            force_tolerance_n=1e-9,
            moment_tolerance_n_m=1e-9,
            relative_tolerance=1e-12,
            required_margin_m=editor.required_margin_mm / 1000,
            uncertainty_method="analytic_interval",
            evaluation_budget=16,
            required_check_types=["support", "tip"],
            required_case_ids=["component-1"],
        ),
        uniform_mass_part_ids=uniforms,
        full_face_contact_facet_ids=contacts,
    )
    return GenericAssemblyRequest.model_validate(value)


def run_assembly(payload):
    from forma_domain.generic_assembly import GenericAssemblyRequest
    from forma_stability.generic_assembly import evaluate_assembly

    if not isinstance(payload, dict):
        raise ValueError("Provide an editor request or an exact assembly request")
    raw = payload.get("request", payload)
    request = (
        editor_request(payload)
        if "editor" in payload and "request" not in payload
        else GenericAssemblyRequest.model_validate(raw)
    )

    def reject_observations(value):
        if isinstance(value, dict):
            if (
                value.get("provenance") == "measured"
                or value.get("confirmed")
                or value.get("evidence_ids")
            ):
                raise ValueError("The lab cannot authenticate measured evidence")
            for child in value.values():
                reject_observations(child)
        elif isinstance(value, list):
            for child in value:
                reject_observations(child)

    if request.snapshot.basis != "hypothetical":
        raise ValueError("The lab accepts hypothetical snapshots only")
    reject_observations(request.model_dump(mode="json"))
    result = evaluate_assembly(request)
    return dict(
        label="Hypothetical assembly experiment; no fabrication approval or physical evidence",
        request=request.model_dump(mode="json"),
        result=result.model_dump(mode="json"),
        editor=EditorRequest.model_validate(payload).editor.model_dump(mode="json")
        if "editor" in payload and "request" not in payload
        else None,
    )
