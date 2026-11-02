import type { BuildRequirements } from "./generated/api-contracts";
import type { Constraints, Measurement } from "./generated/contracts";

export const constraintFields: {
  field:
    | "device_mass_g"
    | "support_angle_deg"
    | "max_footprint_width_mm"
    | "max_footprint_height_mm";
  label: string;
  unit: Measurement["unit"];
}[] = [
  { field: "device_mass_g", label: "Device mass", unit: "g" },
  {
    field: "support_angle_deg",
    label: "Viewing angle from the desk",
    unit: "deg",
  },
  { field: "max_footprint_width_mm", label: "Maximum stand width", unit: "mm" },
  {
    field: "max_footprint_height_mm",
    label: "Maximum stand depth",
    unit: "mm",
  },
];

export function emptyRequirements(): BuildRequirements {
  const unknown = (unit: Measurement["unit"]): Measurement => ({
    value: null,
    unit,
    source: "unknown",
    confirmed: false,
  });
  return {
    tools: [],
    device_description: null,
    constraints: {
      device_mass_g: unknown("g"),
      support_angle_deg: unknown("deg"),
      max_footprint_width_mm: unknown("mm"),
      max_footprint_height_mm: unknown("mm"),
      allowed_profile_ids: [],
      allow_purchases: false,
    },
  };
}

export function requirementsError(value: BuildRequirements): string | null {
  const tools = value.tools ?? [];
  if (tools.length > 32 || tools.some((tool) => !tool || tool.length > 80))
    return "Enter up to 32 tools, one per line, with at most 80 characters each.";
  if (
    new Set(tools.map((tool) => tool.toLocaleLowerCase("en-US"))).size !==
    tools.length
  )
    return "List each available tool once.";
  for (const { field, label } of constraintFields) {
    const measurement = value.constraints[field];
    if (measurement.value === null) continue;
    if (
      !Number.isFinite(measurement.value) ||
      measurement.value <= 0 ||
      (field === "support_angle_deg" && measurement.value >= 90)
    )
      return `${label} must be ${field === "support_angle_deg" ? "between 0 and 90 degrees" : "greater than zero"}, or left blank.`;
    if (!measurement.confirmed)
      return `Confirm ${label.toLowerCase()} or leave it blank.`;
  }
  return null;
}

export function editConstraint(
  constraints: Constraints,
  field: (typeof constraintFields)[number]["field"],
  raw: string,
): Constraints {
  return {
    ...constraints,
    [field]: {
      value: raw === "" ? null : Number(raw),
      unit: constraints[field].unit,
      source: raw === "" ? "unknown" : "user_ruler",
      confirmed: false,
    },
  };
}
