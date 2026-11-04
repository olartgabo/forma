import type { AssemblyViewResponse } from "../../lib/generated/contracts";
import {
  validateAnalysis,
  validateContext,
  type ExpectedContext,
} from "../stability-report/client";

function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
export function validateView(
  value: unknown,
  expected: ExpectedContext,
  cursor: string | null,
): AssemblyViewResponse {
  const context = validateContext(value, expected);
  if (
    !object(value) ||
    context.last_event_id !== cursor ||
    !["ready", "unsupported"].includes(String(value.status)) ||
    typeof value.evidence_revision !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.evidence_revision) ||
    value.overlay_coverage !== "unavailable" ||
    !Array.isArray(value.blockers) ||
    !value.blockers.every((item) => typeof item === "string") ||
    !Array.isArray(value.operation_parts) ||
    value.operation_parts.length > 64 ||
    (value.status === "ready") !== (value.geometry != null)
  )
    throw new Error(
      "The assembly view is invalid or stale. Reload the project.",
    );
  if (value.geometry != null) {
    validateAnalysis(
      {
        ...value,
        status: "needs_measurement",
        geometry_preview: value.geometry,
        report: null,
      },
      expected,
      cursor,
    );
  }
  const geometry = value.geometry as AssemblyViewResponse["geometry"];
  const ids = new Set<string>();
  for (const link of value.operation_parts) {
    if (
      !object(link) ||
      typeof link.operation_id !== "string" ||
      !link.operation_id ||
      ids.has(link.operation_id) ||
      !Array.isArray(link.part_ids) ||
      link.part_ids.length > 16 ||
      !link.part_ids.every(
        (id) =>
          typeof id === "string" && geometry?.active_part_ids.includes(id),
      )
    )
      throw new Error("The assembly contains invalid manual links.");
    ids.add(link.operation_id);
  }
  return value as AssemblyViewResponse;
}

export async function requestView(
  token: string,
  expected: ExpectedContext,
  signal: AbortSignal,
) {
  const root = `/api/projects/${encodeURIComponent(expected.projectId)}`;
  async function json(url: string): Promise<unknown> {
    const response = await fetch(url, {
      signal,
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok)
      throw new Error(
        response.status === 409
          ? "The project changed. Reload it before opening the assembly."
          : "The assembly view is unavailable. Use the SVG manual and recorded history.",
      );
    return response.json();
  }
  const context = validateContext(
    await json(
      `${root}/stability/context?plan_version_id=${encodeURIComponent(expected.planVersionId)}`,
    ),
    expected,
  );
  const params = new URLSearchParams({
    plan_version_id: expected.planVersionId,
    expected_inventory_revision_id: expected.inventoryRevisionId,
    expected_last_event_id: context.last_event_id ?? "",
  });
  return validateView(
    await json(`${root}/assembly-view?${params}`),
    expected,
    context.last_event_id,
  );
}
