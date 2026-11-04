import type { SavedProjectSummary } from "./generated/api-contracts";
import type { EnginePreviewGeometry } from "./engine-model-projection";

export type ProjectGeometry = EnginePreviewGeometry;
export type ProjectThumbnailData = ProjectGeometry | { readonly svg: string };

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function validFacets(value: unknown): value is ProjectGeometry["facets"] {
  let vertices = 0;
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.length <= 128 &&
    value.every(
      (facet) =>
        record(facet) &&
        typeof facet.facet_id === "string" &&
        typeof facet.part_id === "string" &&
        Array.isArray(facet.vertices) &&
        facet.vertices.length >= 3 &&
        facet.vertices.length <= 256 &&
        (vertices += facet.vertices.length) <= 8192 &&
        facet.vertices.every(
          (point: unknown) =>
            record(point) &&
            [point.x, point.y, point.z].every(
              (n) => typeof n === "number" && Number.isFinite(n),
            ),
        ),
    )
  );
}

async function savedManual(
  token: string,
  project: SavedProjectSummary,
  versionId: string,
  signal: AbortSignal,
): Promise<ProjectThumbnailData | null> {
  const base = `/api/projects/${encodeURIComponent(project.id)}`;
  const saved = await fetch(
    `${base}/versions/${encodeURIComponent(versionId)}`,
    {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal,
    },
  );
  if (!saved.ok) return null;
  const version: unknown = await saved.json();
  if (
    !record(version) ||
    version.project_id !== project.id ||
    version.version_id !== versionId ||
    version.inventory_revision_id !== project.revision_id ||
    !record(version.plan) ||
    version.plan.project_id !== project.id ||
    version.plan.version_id !== versionId ||
    !record(version.manual) ||
    version.manual.project_id !== project.id ||
    version.manual.version_id !== versionId ||
    !Array.isArray(version.manual.panels) ||
    version.manual.panels.length > 128
  )
    return null;
  const panel: unknown = version.manual.panels.at(-1);
  return record(panel) &&
    typeof panel.svg === "string" &&
    panel.svg.length > 0 &&
    panel.svg.length <= 2_000_000
    ? { svg: panel.svg }
    : null;
}

export async function loadProjectGeometry(
  token: string,
  project: SavedProjectSummary,
  signal: AbortSignal,
): Promise<ProjectThumbnailData | null> {
  const base = `/api/projects/${encodeURIComponent(project.id)}`;
  const path = project.active_version_id
    ? `${base}/versions/${encodeURIComponent(project.active_version_id)}/geometry`
    : `${base}/construction/preview`;
  const response = await fetch(
    `${path}?expected_inventory_revision_id=${encodeURIComponent(project.revision_id)}`,
    {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal,
    },
  );
  if (response.status === 422 && project.active_version_id) {
    // Only an explicitly unsupported current design may use its frozen manual.
    // Authentication, stale reads and missing versions never trigger fallback.
    return savedManual(token, project, project.active_version_id, signal);
  }
  if (response.status === 404 && !project.active_version_id) {
    const saved = await fetch(`${base}/plans`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal,
    });
    if (!saved.ok) return null;
    const list: unknown = await saved.json();
    if (!record(list) || !Array.isArray(list.plans) || list.plans.length > 128)
      return null;
    const plans = list.plans.filter(
      (p: unknown): p is Record<string, unknown> =>
        record(p) &&
        p.project_id === project.id &&
        p.inventory_revision_id === project.revision_id &&
        typeof p.version_id === "string" &&
        typeof p.created_at === "string" &&
        Number.isFinite(Date.parse(p.created_at)),
    );
    plans.sort(
      (a, b) =>
        Date.parse(String(b.created_at)) - Date.parse(String(a.created_at)),
    );
    return plans.length
      ? savedManual(token, project, String(plans[0].version_id), signal)
      : null;
  }
  if (!response.ok) return null;
  const value: unknown = await response.json();
  if (!record(value) || value.project_id !== project.id) return null;
  if (project.active_version_id) {
    if (
      value.plan_version_id !== project.active_version_id ||
      value.stage !== "planned_preview" ||
      !validFacets(value.facets)
    )
      return null;
    return { facets: value.facets };
  }
  if (
    value.inventory_revision_id !== project.revision_id ||
    !Array.isArray(value.candidates) ||
    value.candidates.length > 2
  )
    return null;
  const candidate: unknown = value.candidates.find(
    (item: unknown) =>
      record(item) &&
      (item.status === "proposed" || item.status === "needs_measurement") &&
      record(item.construction),
  );
  const construction = record(candidate) ? candidate.construction : null;
  if (
    !record(construction) ||
    typeof construction.target_hash !== "string" ||
    !/^[a-f0-9]{64}$/.test(construction.target_hash) ||
    !Array.isArray(construction.steps) ||
    construction.steps.length < 1 ||
    construction.steps.length > 64
  )
    return null;
  const last: unknown = construction.steps.at(-1);
  const analysis = record(last) ? last.analysis : null;
  const facets = record(analysis) ? analysis.facets : null;
  return validFacets(facets) ? { facets } : null;
}
