import type { MuseConstructionResult } from "./generated/api-contracts";

const object = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string =>
  typeof v === "string" && v.length <= 10000;
const id = (v: unknown): v is string =>
  typeof v === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,95}$/.test(v);
const list = (v: unknown, max: number): v is unknown[] =>
  Array.isArray(v) && v.length <= max;
const strings = (v: unknown, max = 128) => list(v, max) && v.every(text);
const point = (v: unknown) =>
  object(v) &&
  [v.x, v.y, v.z].every((n) => typeof n === "number" && Number.isFinite(n));
const vertices = (v: unknown) =>
  list(v, 256) && v.length >= 3 && v.every(point);
const status = (v: unknown) =>
  ["proposed", "needs_measurement", "blocked"].includes(String(v));

/** Validate identity and every field consumed by the complete manual view.
 * The authenticated server remains responsible for physical/engine validation.
 */
export function validConstructionResult(
  value: unknown,
  projectId: string,
  revisionId: string,
): value is MuseConstructionResult {
  if (
    !object(value) ||
    value.project_id !== projectId ||
    value.inventory_revision_id !== revisionId ||
    !status(value.status) ||
    !strings(value.questions, 16) ||
    !list(value.candidates, 2) ||
    !object(value.diagnostics)
  )
    return false;
  const diagnostics = value.diagnostics;
  if (
    diagnostics.status !== "ok" ||
    !text(diagnostics.model) ||
    ![
      diagnostics.elapsed_ms,
      diagnostics.model_rounds,
      diagnostics.tool_executions,
    ].every((n) => typeof n === "number" && Number.isFinite(n) && n >= 0)
  )
    return false;
  const candidates = new Set<string>();
  return value.candidates.every((candidate) => {
    if (
      !object(candidate) ||
      !id(candidate.candidate_id) ||
      candidates.has(candidate.candidate_id) ||
      !text(candidate.title) ||
      !text(candidate.rationale) ||
      !status(candidate.status) ||
      !strings(candidate.blockers, 64)
    )
      return false;
    candidates.add(candidate.candidate_id);
    if (
      candidate.estimated_materials !== undefined &&
      (!list(candidate.estimated_materials, 16) ||
        !candidate.estimated_materials.every(
          (m) =>
            object(m) &&
            text(m.label) &&
            [m.width_mm, m.height_mm, m.thickness_mm].every(
              (n) =>
                n === null ||
                (typeof n === "number" && Number.isFinite(n) && n > 0),
            ),
        ))
    )
      return false;
    if (
      candidate.fabrication_report !== null &&
      (!object(candidate.fabrication_report) ||
        !text(candidate.fabrication_report.status) ||
        !text(candidate.fabrication_report.order_status))
    )
      return false;
    if (
      candidate.fabrication_plan !== null &&
      !object(candidate.fabrication_plan)
    )
      return false;
    const plan = candidate.construction;
    if (plan === null) return true;
    if (
      !object(plan) ||
      !text(plan.generator_version) ||
      typeof plan.target_hash !== "string" ||
      !/^[a-f0-9]{64}$/.test(plan.target_hash) ||
      !strings(plan.limitations) ||
      !object(plan.request) ||
      !object(plan.request.target)
    )
      return false;
    const target = plan.request.target;
    if (
      !object(target.assembly) ||
      target.assembly.project_id !== projectId ||
      !id(target.assembly.plan_version_id) ||
      !object(target.snapshot) ||
      target.snapshot.project_id !== projectId ||
      target.snapshot.inventory_revision !== revisionId ||
      target.snapshot.plan_version_id !== target.assembly.plan_version_id ||
      !list(target.assembly.parts, 128) ||
      !target.assembly.parts.length
    )
      return false;
    const parts = new Set<string>(),
      facets = new Map<string, string>();
    const versionId = target.assembly.plan_version_id;
    for (const part of target.assembly.parts) {
      if (
        !object(part) ||
        !id(part.part_id) ||
        parts.has(part.part_id) ||
        !list(part.facets, 128) ||
        !part.facets.length
      )
        return false;
      parts.add(part.part_id);
      for (const facet of part.facets) {
        if (
          !object(facet) ||
          !id(facet.facet_id) ||
          facets.has(facet.facet_id) ||
          !vertices(facet.vertices_local)
        )
          return false;
        facets.set(facet.facet_id, part.part_id);
      }
    }
    if (
      !list(plan.piece_catalog, 128) ||
      plan.piece_catalog.length !== parts.size
    )
      return false;
    const catalog = new Set<string>();
    for (const piece of plan.piece_catalog) {
      if (
        !object(piece) ||
        !id(piece.part_id) ||
        !parts.has(piece.part_id) ||
        catalog.has(piece.part_id) ||
        !text(piece.reference) ||
        !text(piece.display_name) ||
        ![
          "triangle",
          "rectangle",
          "convex_polygon",
          "concave_polygon",
          "multi_facet",
        ].includes(String(piece.geometry_class)) ||
        (piece.role != null && !text(piece.role))
      )
        return false;
      catalog.add(piece.part_id);
    }
    if (!list(plan.steps, 128) || !plan.steps.length) return false;
    const steps = new Set<string>();
    return plan.steps.every((step, index) => {
      if (
        !object(step) ||
        !id(step.step_id) ||
        steps.has(step.step_id) ||
        step.index !== index ||
        !["place", "join", "inspect"].includes(String(step.action)) ||
        !list(step.part_ids, 128) ||
        !step.part_ids.every((p) => typeof p === "string" && parts.has(p)) ||
        !text(step.instruction) ||
        typeof step.requires_external_support !== "boolean" ||
        !strings(step.unresolved_predicates) ||
        !strings(step.operation_ids) ||
        !list(step.depends_on_step_ids, 128) ||
        !step.depends_on_step_ids.every(
          (s) => typeof s === "string" && steps.has(s),
        ) ||
        !object(step.analysis)
      )
        return false;
      steps.add(step.step_id);
      const analysis = step.analysis;
      if (
        !object(analysis.snapshot) ||
        analysis.snapshot.project_id !== projectId ||
        analysis.snapshot.inventory_revision !== revisionId ||
        analysis.snapshot.plan_version_id !== versionId ||
        !list(analysis.present_part_ids, 128) ||
        !analysis.present_part_ids.every(
          (p) => typeof p === "string" && parts.has(p),
        ) ||
        !step.part_ids.every(
          (p) =>
            analysis.present_part_ids instanceof Array &&
            analysis.present_part_ids.includes(p),
        ) ||
        !list(analysis.facets, 128) ||
        !analysis.facets.length
      )
        return false;
      const seen = new Set<string>();
      return analysis.facets.every((facet) => {
        if (
          !object(facet) ||
          !id(facet.facet_id) ||
          seen.has(facet.facet_id) ||
          facets.get(facet.facet_id) !== facet.part_id ||
          !(analysis.present_part_ids instanceof Array) ||
          !analysis.present_part_ids.includes(facet.part_id) ||
          !vertices(facet.vertices) ||
          !point(facet.centroid)
        )
          return false;
        seen.add(facet.facet_id);
        return true;
      });
    });
  });
}
