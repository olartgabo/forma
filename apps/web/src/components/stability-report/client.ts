import type {
  StabilityAnalysisResponse,
  StabilityContext,
} from "../../lib/generated/api-contracts";
import type { StabilityReport } from "../../lib/generated/contracts";

export type ExpectedContext = {
  projectId: string;
  planVersionId: string;
  inventoryRevisionId: string;
};
export type AnalysisContext = StabilityContext;
export type AnalysisResponse = StabilityAnalysisResponse & {
  report: StabilityReport | null;
  blockers: readonly string[];
};
const statuses = new Set([
  "modeled_pass",
  "modeled_fail",
  "indeterminate",
  "needs_measurement",
  "unsupported",
  "not_applicable",
]);
const checks = new Set(["support", "tip", "slide", "joint", "deformation"]);
const computations = new Set([
  "complete",
  "invalid_input",
  "numerical_failure",
  "budget_exhausted",
  "not_run",
]);
function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}
function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
function point(value: unknown): value is { x: number; y: number; z: number } {
  return object(value) && finite(value.x) && finite(value.y) && finite(value.z);
}
function validGeometry(
  value: unknown,
  expected: ExpectedContext,
  cursor: string | null,
) {
  if (
    !object(value) ||
    value.project_id !== expected.projectId ||
    value.plan_version_id !== expected.planVersionId ||
    value.history_cursor !== cursor ||
    value.coordinate_frame !== "x_across_y_rearward_z_up_m" ||
    typeof value.producer_version !== "string" ||
    !value.producer_version ||
    typeof value.geometry_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.geometry_hash) ||
    !["planned_preview", "reported_assembled"].includes(String(value.stage)) ||
    value.state_basis !== "nominal" ||
    !strings(value.active_part_ids) ||
    !value.active_part_ids.length ||
    value.active_part_ids.length > 16 ||
    new Set(value.active_part_ids).size !== value.active_part_ids.length ||
    !strings(value.attached_joint_ids) ||
    !strings(value.nominal_joint_ids) ||
    !strings(value.completed_operation_ids) ||
    !strings(value.assumption_ids) ||
    !value.assumption_ids.length ||
    !strings(value.assumptions) ||
    !value.assumptions.length ||
    !Array.isArray(value.facets) ||
    !value.facets.length ||
    value.facets.length > 32 ||
    !Array.isArray(value.ground_polygon) ||
    value.ground_polygon.length !== 4 ||
    !value.ground_polygon.every(point)
  )
    return false;
  const attachedJoints = value.attached_joint_ids;
  const nominalJoints = value.nominal_joint_ids;
  if (
    attachedJoints.some((id) => !nominalJoints.includes(id)) ||
    (value.stage === "planned_preview" &&
      (value.attached_joint_ids.length ||
        value.completed_operation_ids.length)) ||
    (value.stage === "reported_assembled" &&
      (!value.completed_operation_ids.length ||
        nominalJoints.some((id) => !attachedJoints.includes(id))))
  )
    return false;
  const facetIds = new Set<string>();
  const parts = new Set(value.active_part_ids);
  const fractions = new Map<string, number>();
  for (const facet of value.facets) {
    if (
      !object(facet) ||
      typeof facet.facet_id !== "string" ||
      !facet.facet_id ||
      facetIds.has(facet.facet_id) ||
      typeof facet.part_id !== "string" ||
      !parts.has(facet.part_id) ||
      !Array.isArray(facet.vertices) ||
      facet.vertices.length !== 4 ||
      !facet.vertices.every(point) ||
      !point(facet.centroid) ||
      !finite(facet.area_fraction) ||
      facet.area_fraction <= 0 ||
      facet.area_fraction > 1
    )
      return false;
    // A canonical facet centroid must lie inside its vertices' coordinate bounds.
    // Otherwise even finite input could overflow the label projection at its
    // minimum diagram span (scale 240000), or put the label outside the facet.
    for (const axis of ["x", "y", "z"] as const) {
      const coordinates = facet.vertices.map((vertex) => vertex[axis]);
      if (
        facet.centroid[axis] < Math.min(...coordinates) ||
        facet.centroid[axis] > Math.max(...coordinates)
      )
        return false;
    }
    facetIds.add(facet.facet_id);
    fractions.set(
      facet.part_id,
      (fractions.get(facet.part_id) ?? 0) + facet.area_fraction,
    );
  }
  if (
    [...parts].some((part) => Math.abs((fractions.get(part) ?? 0) - 1) > 1e-9)
  )
    return false;
  // Keep finite server data from overflowing projection arithmetic in the browser.
  const points = value.facets.flatMap((facet) => [
    ...facet.vertices,
    facet.centroid,
  ]);
  for (const axis of ["x", "y", "z"]) {
    const coordinates = points.map((p) => p[axis]);
    const span = Math.max(...coordinates) - Math.min(...coordinates);
    if (!Number.isFinite(span) || span * 240 === Infinity) return false;
  }
  return true;
}
export function validateContext(
  value: unknown,
  expected: ExpectedContext,
): AnalysisContext {
  if (
    !object(value) ||
    value.project_id !== expected.projectId ||
    value.plan_version_id !== expected.planVersionId ||
    value.inventory_revision_id !== expected.inventoryRevisionId ||
    !(value.last_event_id === null || typeof value.last_event_id === "string")
  ) {
    throw new Error(
      "Analysis context changed. Reload the project and inventory before analyzing again.",
    );
  }
  return value as AnalysisContext;
}
export function validateAnalysis(
  value: unknown,
  expected: ExpectedContext,
  cursor: string | null,
): AnalysisResponse {
  const context = validateContext(value, expected);
  if (
    !object(value) ||
    context.last_event_id !== cursor ||
    ![
      "complete",
      "needs_geometry",
      "needs_measurement",
      "unsupported",
    ].includes(String(value.status)) ||
    !strings(value.blockers)
  )
    throw new Error(
      "The analysis response is invalid or stale. Reload before analyzing again.",
    );
  if (
    value.geometry_preview != null &&
    !validGeometry(value.geometry_preview, expected, cursor)
  )
    throw new Error(
      "The server returned an invalid or stale nominal geometry preview.",
    );
  if (value.report === null) {
    if (value.status === "complete")
      throw new Error("A complete analysis requires a report.");
    return value as AnalysisResponse;
  }
  const r = value.report;
  if (
    !object(r) ||
    !object(r.identity) ||
    r.identity.project_id !== expected.projectId ||
    r.identity.plan_version_id !== expected.planVersionId ||
    r.identity.inventory_revision !== expected.inventoryRevisionId ||
    r.identity.history_cursor !== cursor ||
    !statuses.has(String(r.status)) ||
    !["complete", "partial", "unsupported"].includes(String(r.coverage)) ||
    !strings(r.unresolved_predicates) ||
    !Array.isArray(r.results) ||
    !object(r.policy) ||
    !strings(r.policy.required_case_ids) ||
    !strings(r.policy.required_check_types) ||
    !r.policy.required_case_ids.length ||
    !r.policy.required_check_types.length
  )
    throw new Error("The server returned an invalid stability report.");
  const seen = new Set<string>();
  for (const c of r.results) {
    if (
      !object(c) ||
      typeof c.case_id !== "string" ||
      !checks.has(String(c.check_type)) ||
      !statuses.has(String(c.status)) ||
      !computations.has(String(c.computation)) ||
      typeof c.explanation !== "string" ||
      !strings(c.unresolved_predicates) ||
      !Array.isArray(c.quantities)
    )
      throw new Error("The server returned an invalid check result.");
    const key = `${c.case_id}/${c.check_type}`;
    if (seen.has(key))
      throw new Error("The server returned duplicate check results.");
    seen.add(key);
    if (
      (c.status === "modeled_pass" || c.status === "modeled_fail") &&
      c.computation !== "complete"
    )
      throw new Error("A calculation failed; its result cannot pass or fail.");
    if (
      c.status === "modeled_pass" &&
      (c.unresolved_predicates.length ||
        c.quantities.some((q) => !object(q) || q.kind === "unknown"))
    )
      throw new Error("An unresolved check cannot pass.");
  }
  const results = r.results;
  const requiredCases = r.policy.required_case_ids;
  const requiredTypes = r.policy.required_check_types;
  if (r.status === "modeled_pass") {
    if (
      r.coverage !== "complete" ||
      r.unresolved_predicates.length ||
      !r.results.length ||
      r.results.some(
        (c) => c.status !== "modeled_pass" && c.status !== "not_applicable",
      ) ||
      requiredCases.some((id) =>
        requiredTypes.some(
          (type) =>
            !results.some(
              (c) =>
                c.case_id === id &&
                c.check_type === type &&
                c.status === "modeled_pass",
            ),
        ),
      )
    )
      throw new Error(
        "The report cannot claim a modeled pass with unresolved required checks.",
      );
  }
  if (
    r.overlays !== undefined &&
    (!Array.isArray(r.overlays) ||
      r.overlays.some(
        (o) =>
          !object(o) ||
          typeof o.case_id !== "string" ||
          typeof o.orientation !== "string" ||
          !point(o.center_of_mass) ||
          !Array.isArray(o.support_polygon) ||
          o.support_polygon.length < 3 ||
          !o.support_polygon.every(point) ||
          !Array.isArray(o.critical_edge) ||
          o.critical_edge.length !== 2 ||
          !o.critical_edge.every(point) ||
          !finite(o.signed_margin_m) ||
          !finite(o.restoring_moment_n_m),
      ))
  )
    throw new Error("The server returned an invalid geometry overlay.");
  return value as AnalysisResponse;
}
export async function requestAnalysis(
  token: string,
  expected: ExpectedContext,
  signal: AbortSignal,
): Promise<AnalysisResponse> {
  const root = `/api/projects/${encodeURIComponent(expected.projectId)}/stability`;
  async function json(url: string, init: RequestInit = {}) {
    const response = await fetch(url, {
      ...init,
      signal,
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });
    if (!response.ok)
      throw new Error(
        response.status === 409
          ? "The project changed. Reload before analyzing again."
          : "Stability analysis is unavailable. Try again when ready.",
      );
    return response.json() as Promise<unknown>;
  }
  const context = validateContext(
    await json(
      `${root}/context?plan_version_id=${encodeURIComponent(expected.planVersionId)}`,
    ),
    expected,
  );
  return validateAnalysis(
    await json(`${root}/analyses`, {
      method: "POST",
      body: JSON.stringify({
        plan_version_id: expected.planVersionId,
        expected_inventory_revision_id: expected.inventoryRevisionId,
        expected_last_event_id: context.last_event_id,
      }),
    }),
    expected,
    context.last_event_id,
  );
}
