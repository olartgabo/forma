import type {
  StabilityMeasurementRequest,
  StabilityMeasurementResponse,
} from "../../lib/generated/api-contracts";
import type {
  MeasuredBody,
  StabilityMeasurements,
} from "../../lib/generated/contracts";
import type { AnalysisContext, ExpectedContext } from "./client";

function validateContext(
  value: unknown,
  expected: ExpectedContext,
): AnalysisContext {
  if (
    !value ||
    typeof value !== "object" ||
    !("project_id" in value) ||
    value.project_id !== expected.projectId ||
    !("plan_version_id" in value) ||
    value.plan_version_id !== expected.planVersionId ||
    !("inventory_revision_id" in value) ||
    value.inventory_revision_id !== expected.inventoryRevisionId ||
    !("last_event_id" in value) ||
    !(value.last_event_id === null || typeof value.last_event_id === "string")
  )
    throw new Error("Measurement context changed. Reload before saving.");
  return value as AnalysisContext;
}

export class MeasurementSaveError extends Error {
  readonly uncertain: boolean;
  constructor(message: string, uncertain: boolean) {
    super(message);
    this.uncertain = uncertain;
  }
}

function value(data: FormData, name: string) {
  const raw = data.get(name);
  if (typeof raw !== "string" || !raw.trim())
    throw new Error(`Enter ${name.replaceAll("_", " ")}.`);
  return raw.trim();
}
function measured(data: FormData, name: string, scale = 0.001) {
  const raw = value(data, name);
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(raw))
    throw new Error(`Enter a number for ${name.replaceAll("_", " ")}.`);
  const result = Number(raw) * scale;
  if (!Number.isFinite(result))
    throw new Error("Measurements must be finite numbers.");
  return result;
}
function body(data: FormData, prefix: string): MeasuredBody {
  const result = {
    mass_kg: measured(data, `${prefix}_mass_g`),
    center_of_mass_m: {
      x: measured(data, `${prefix}_x_mm`),
      y: measured(data, `${prefix}_y_mm`),
      z: measured(data, `${prefix}_z_mm`),
    },
    mass_resolution_kg: measured(data, `${prefix}_mass_resolution_g`),
    position_resolution_m: measured(data, `${prefix}_position_resolution_mm`),
    method: value(data, `${prefix}_method`),
  };
  if (
    result.mass_kg <= 0 ||
    result.mass_resolution_kg <= 0 ||
    result.mass_resolution_kg >= result.mass_kg ||
    result.position_resolution_m <= 0 ||
    result.center_of_mass_m.z < 0
  )
    throw new Error(
      `${prefix}: use positive mass and resolutions, mass resolution smaller than mass, and nonnegative height.`,
    );
  return result;
}
export const confirmations = [
  [
    "stand_includes_all_parts_and_connectors",
    "The stand mass includes every panel, tape joint and other connector.",
  ],
  [
    "actual_contacts_confirmed",
    "I measured the actual supporting rectangle; I did not copy the nominal outline.",
  ],
  [
    "horizontal_surface_confirmed",
    "I checked that the supporting surface is horizontal.",
  ],
  [
    "rigid_assembly_assumed",
    "For this calculation I assume the connected assembly is rigid.",
  ],
  [
    "stationary_device_assumed",
    "For each measured pose I assume the device remains stationary relative to the stand.",
  ],
  [
    "gravity_only_assumed",
    "I am evaluating gravity only, with no push, impact or other applied load.",
  ],
] as const;
export function measurementsFromForm(data: FormData): StabilityMeasurements {
  for (const [name] of confirmations)
    if (data.get(name) !== "on")
      throw new Error(
        "Review and explicitly confirm each observation and assumption.",
      );
  if (data.get("user_confirmed") !== "on")
    throw new Error(
      "Confirm that these are your measurements, not example values.",
    );
  const support = {
    x_min_m: measured(data, "contact_x_min_mm"),
    x_max_m: measured(data, "contact_x_max_mm"),
    y_min_m: measured(data, "contact_y_min_mm"),
    y_max_m: measured(data, "contact_y_max_mm"),
    resolution_m: measured(data, "contact_resolution_mm"),
    method: value(data, "contact_method"),
  };
  const span = Math.min(
    support.x_max_m - support.x_min_m,
    support.y_max_m - support.y_min_m,
  );
  if (span <= 0 || support.resolution_m <= 0 || support.resolution_m >= span)
    throw new Error(
      "Contact minimums must be below maximums, with positive resolution smaller than both spans.",
    );
  const margin = measured(data, "required_margin_mm");
  if (margin < 0) throw new Error("Required margin cannot be negative.");
  return {
    stand: body(data, "stand"),
    cases: (["portrait", "landscape"] as const).map((orientation) => ({
      orientation,
      device: body(data, orientation),
      pose_description: value(data, `${orientation}_pose`),
    })),
    support,
    required_margin_m: margin,
    stand_includes_all_parts_and_connectors: true,
    actual_contacts_confirmed: true,
    horizontal_surface_confirmed: true,
    rigid_assembly_assumed: true,
    stationary_device_assumed: true,
    gravity_only_assumed: true,
  };
}
export async function measurementContext(
  token: string,
  expected: ExpectedContext,
  signal: AbortSignal,
): Promise<AnalysisContext> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(expected.projectId)}/stability/context?plan_version_id=${encodeURIComponent(expected.planVersionId)}`,
    {
      signal,
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    },
  );
  if (!response.ok)
    throw new Error(
      "Could not load the current measurement context. Reload and try again.",
    );
  return validateContext(await response.json(), expected);
}
export async function saveMeasurements(
  token: string,
  expected: ExpectedContext,
  payload: StabilityMeasurementRequest,
  signal: AbortSignal,
): Promise<StabilityMeasurementResponse> {
  let response: Response;
  try {
    response = await fetch(
      `/api/projects/${encodeURIComponent(expected.projectId)}/stability/measurements`,
      {
        method: "POST",
        body: JSON.stringify(payload),
        signal,
        cache: "no-store",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      },
    );
  } catch {
    throw new MeasurementSaveError(
      "The save outcome is unknown. Retry the same save to resolve it before editing.",
      true,
    );
  }
  if (!response.ok) {
    let stale = false;
    if (response.status === 409) {
      try {
        stale = (await response.json()).code === "stale_version";
      } catch {
        /* Unverified errors do not resolve an earlier write. */
      }
    }
    const definitive =
      stale || response.status === 400 || response.status === 422;
    throw new MeasurementSaveError(
      definitive
        ? stale
          ? "The project changed. Reload the measurement context and review the values before saving again."
          : "Measurements were rejected. Check the values and assembly reports, then reload the measurement context."
        : "The save outcome is unknown. Reconnect with the same owner if needed, then retry the retained save before editing.",
      !definitive,
    );
  }
  try {
    const result = await response.json();
    validateContext(result, expected);
    if (
      typeof result.last_event_id !== "string" ||
      !result.last_event_id ||
      typeof result.measurement_id !== "string" ||
      !result.measurement_id ||
      typeof result.evidence_id !== "string" ||
      !result.evidence_id ||
      typeof result.replayed !== "boolean"
    )
      throw new Error();
    return result as StabilityMeasurementResponse;
  } catch {
    throw new MeasurementSaveError(
      "The save response could not be verified. Retry the same save before editing.",
      true,
    );
  }
}
