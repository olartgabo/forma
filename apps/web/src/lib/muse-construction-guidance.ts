import type {
  ConstructionPlan,
  ConstructionStep,
  Stock,
} from "./generated/contracts";

// Display saved provenance only; readiness remains the server engine's decision.
export function materialMeasurementChecklist(stock: Stock) {
  const fields =
    stock.kind === "tape" || stock.kind === "cord"
      ? (["remaining_length_mm"] as const)
      : (["width_mm", "height_mm", "thickness_mm"] as const);
  const labels = {
    width_mm: "Width",
    height_mm: "Height",
    thickness_mm: "Thickness",
    remaining_length_mm: "Remaining length",
  };
  return fields.map((field) => {
    const measurement = stock[field];
    const status =
      measurement.value === null
        ? "missing"
        : !measurement.confirmed
          ? "unconfirmed"
          : "confirmed";
    return {
      field,
      label: labels[field],
      value: measurement.value,
      unit: measurement.unit,
      source: measurement.source,
      status,
    };
  });
}

export function constructionStepTitle(
  plan: ConstructionPlan,
  step: ConstructionStep,
) {
  const names = step.part_ids.map(
    (id) =>
      plan.piece_catalog.find((p) => p.part_id === id)?.display_name ?? id,
  );
  const action = { place: "Place", join: "Join", inspect: "Inspect" }[
    step.action
  ];
  return `${action} ${names.join(" + ") || step.joint_id || "proposed assembly"}`;
}

export function constructionPiecePresence(
  plan: ConstructionPlan,
  step: ConstructionStep,
  partId: string,
) {
  if (step.part_ids.includes(partId)) return "Focus of this step";
  if (step.analysis.facets.some((facet) => facet.part_id === partId))
    return "Present in this step";
  const later = plan.steps
    .slice(plan.steps.indexOf(step) + 1)
    .some((s) => s.part_ids.includes(partId));
  return later ? "Used in a later step" : "Not shown in this step";
}
