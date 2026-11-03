import type { ProofSnapshot } from "./generated/api-contracts";

type ProofVersion = ProofSnapshot["versions"][number];
type ProofProgress = ProofVersion["progress"];

// Names what kind of claim each evidence record is, so a reader can tell a
// hand measurement from a user report or an unverified model reading.
export function evidenceLabel(kind: string): string {
  return (
    {
      measurement: "manually measured",
      user_report: "user report",
      photo: "photo",
      physical_test: "physical test",
      model_interpretation: "Muse observations and hypotheses (unverified)",
    }[kind] ?? kind.replaceAll("_", " ")
  );
}

// Totals of discarded and recovered material the builder recorded.
export function recordedMaterial(progress: ProofProgress): string {
  const total = (kind: string, unit: string) =>
    progress.material_transactions
      .filter((item) => item.kind === kind && item.unit === unit)
      .reduce((sum, item) => sum + item.quantity, 0);
  const sheetWaste = total("waste", "mm2");
  const connectorWaste = total("waste", "mm");
  const salvage = total("salvage", "mm2");
  if (sheetWaste === 0 && connectorWaste === 0 && salvage === 0)
    return "No discarded or recovered material recorded.";
  return `Recorded waste: ${sheetWaste} mm2 of sheet, ${connectorWaste} mm of connector; recovered: ${salvage} mm2.`;
}

export function proofVersionLabel(state: ProofVersion["state"]): string {
  return {
    active: "Active plan",
    historical: "Historical plan",
    preview: "Saved preview",
  }[state];
}

export function revisionDetails(version: ProofVersion): [string, string][] {
  const revision = version.revision;
  if (!revision) return [];
  const simulation = revision.simulation;
  const ids = (values: readonly string[] | undefined) =>
    values?.length ? values.join(", ") : "None";
  return [
    ["Revised from", revision.base_version_id],
    ["Approved", revision.approved_at],
    ["Reason", revision.patch.rationale],
    ["Kept work", ids(simulation.preserved_operation_ids)],
    ["Physical undo required", ids(simulation.required_undo_operation_ids)],
    ["Redo", ids(simulation.redo_operation_ids)],
    ["New work", ids(simulation.newly_required_operation_ids)],
    ["Changed parts", ids(simulation.changed_part_ids)],
    ["Lost parts", ids(simulation.lost_part_ids)],
    ["Lost work", ids(simulation.lost_operation_ids)],
    ["Lost regions", ids(simulation.lost_region_ids)],
    [
      "Additional material stock",
      ids(simulation.additional_material_stock_ids),
    ],
    ["New stock required", ids(simulation.required_new_stock_ids)],
    ["Checks to repeat", ids(simulation.invalidated_checkpoint_ids)],
    ["Unknown physical checks", ids(simulation.unknown_physical_checks)],
    [
      "Planned material changes (not physical receipts)",
      simulation.proposed_material_deltas?.length
        ? simulation.proposed_material_deltas
            .map(
              (item) =>
                `${item.kind}: ${item.quantity} ${item.unit} from ${item.stock_id}${item.source_region_id ? ` / ${item.source_region_id}` : ""}`,
            )
            .join("; ")
        : "None",
    ],
  ];
}

export function proofUnknowns(snapshot: ProofSnapshot): string[] {
  const unknowns: string[] = [];
  for (const stock of snapshot.project.stocks ?? []) {
    const fields =
      stock.kind === "tape"
        ? ["remaining_length_mm" as const, "width_mm" as const]
        : stock.kind === "cord"
          ? ["remaining_length_mm" as const]
          : [
              "width_mm" as const,
              "height_mm" as const,
              "thickness_mm" as const,
            ];
    for (const field of fields)
      if (stock[field].value === null || !stock[field].confirmed)
        unknowns.push(
          `${stock.id}: ${field.replaceAll("_", " ")} ${stock[field].value === null ? "unknown" : "unconfirmed"}`,
        );
    if (stock.condition === "uncertain")
      unknowns.push(`${stock.id}: material condition uncertain`);
    if (
      stock.kind === "sheet" &&
      !stock.usable_regions?.length &&
      !snapshot.project.active_version_id
    )
      unknowns.push(`${stock.id}: usable starting regions not recorded`);
  }
  const requirements = snapshot.project.requirements;
  if (!requirements)
    unknowns.push("Device and space requirements not recorded");
  else
    for (const field of [
      "device_mass_g",
      "support_angle_deg",
      "max_footprint_width_mm",
      "max_footprint_height_mm",
    ] as const) {
      const value = requirements.constraints[field];
      if (value.value === null || !value.confirmed)
        unknowns.push(
          `${field.replaceAll("_", " ")}: ${value.value === null ? "unknown" : "unconfirmed"}`,
        );
    }
  return unknowns;
}

export function proofStatus(
  status: ProofSnapshot["versions"][number]["progress"]["status"],
): string {
  return {
    not_started: "No physical work reported",
    building: "Build in progress; user reports recorded",
    needs_review: "Failed check; diagnosis or revision required",
    passed: "Defined functional test passed; user reported",
  }[status];
}

export function proofText(snapshot: ProofSnapshot): string {
  const lines = [
    "FORMA Proof",
    "",
    `Goal: ${snapshot.project.goal}`,
    `Snapshot generated: ${snapshot.generated_at}`,
    `Active version: ${snapshot.project.active_version_id ?? "None"}`,
    "Coverage: versioned plans, user reports and approved repair revisions.",
    `Private photos excluded: ${snapshot.photos_omitted}.`,
    "Historical outcomes describe their recorded version; invalidated evidence does not verify the revised plan.",
    "Expected stock is calculated and needs actual measurement/reconciliation before repair.",
    "Recorded timestamps are report ingestion times. Build duration is unavailable; waste and salvage cover only what the builder recorded.",
  ];
  if (snapshot.versions.length === 0)
    lines.push("", "No compiled plan or physical result is recorded.");
  lines.push("Unknown or unconfirmed starting inputs:");
  const unknowns = proofUnknowns(snapshot);
  lines.push(
    ...(unknowns.length
      ? unknowns.map((value) => `  ${value}`)
      : ["  None in the saved fields shown here"]),
  );
  for (const version of snapshot.versions) {
    const { plan, progress } = version;
    lines.push(
      "",
      `Version: ${plan.version_id} (${proofVersionLabel(version.state)})`,
      `Inventory revision: ${version.inventory_revision_id}`,
      `Candidate: ${version.candidate_id}`,
      `Compiler: ${plan.compiler_version}`,
      `Physical outcome: ${proofStatus(progress.status)}`,
      `Completed operations: ${progress.completed_operation_ids.length} / ${plan.operations.length}`,
      `Carried from earlier reports: ${progress.carried_operation_ids?.length ?? 0}`,
      `New completion reports in this version: ${progress.events.filter((event) => event.kind === "operation_confirmed").length}`,
      recordedMaterial(progress),
      ...revisionDetails(version).map(([label, value]) => `${label}: ${value}`),
      "Uncompleted operations:",
    );
    const unfinished = plan.operations.filter(
      (op) => !progress.completed_operation_ids.includes(op.id),
    );
    lines.push(
      ...(unfinished.length
        ? unfinished.map((op) => `  ${op.id} (${op.type})`)
        : ["  None"]),
    );
    for (const op of plan.operations)
      if (op.type === "functional_test") {
        lines.push(
          "Defined functional test:",
          `  Operation: ${op.id}`,
          `  Procedure: ${op.args.procedure}`,
          `  Device: ${op.args.device_label}`,
          `  Mass: ${op.args.mass_g === null ? "Unknown" : `${op.args.mass_g} g`}`,
          `  Duration: ${op.args.duration_seconds} seconds`,
          `  Surface: ${op.args.surface}`,
          ...op.args.pass_criteria.map(
            (criterion) => `  Criterion: ${criterion}`,
          ),
        );
        const tests = progress.events.filter(
          (event) => event.operation_id === op.id && event.kind === "test",
        );
        lines.push(
          ...(tests.length
            ? tests.map(
                (event) =>
                  `  User-reported result: ${event.test_result}; recorded ${event.recorded_at}`,
              )
            : ["  Result: not attempted"]),
        );
      }
    lines.push("User report timeline:");
    lines.push(
      ...(progress.events.length
        ? progress.events.flatMap((event) => [
            `  ${event.recorded_at} | ${event.operation_id ?? "Project"} | ${event.kind} | ${event.test_result ?? event.verification_state}`,
            `    ${event.observation}`,
          ])
        : ["  No reports"]),
    );
    lines.push("Evidence provenance:");
    lines.push(
      ...(progress.evidence.length
        ? progress.evidence.flatMap((item) => [
            `  ${item.id} | ${evidenceLabel(item.kind)} | ${item.provenance} | ${item.verification_state}${item.kind === "photo" ? " | image excluded" : ""}`,
            `    ${item.description}`,
            `    Checkpoints: ${item.checkpoint_ids?.join(", ") || "None"}`,
            ...(version.invalidations ?? [])
              .filter((invalidation) => invalidation.evidence_id === item.id)
              .map(
                (invalidation) =>
                  `    Invalidated for ${invalidation.invalidated_for_version_id} at ${invalidation.recorded_at}: ${invalidation.reason}`,
              ),
          ])
        : ["  No evidence recorded"]),
    );
    lines.push(
      "Material receipts from reported operations and material records:",
    );
    lines.push(
      ...(progress.material_transactions.length
        ? progress.material_transactions.map(
            (item) =>
              `  ${item.operation_id} | ${item.kind} | ${item.quantity} ${item.unit} | ${item.source_stock_id}${item.source_region_id ? ` / ${item.source_region_id}` : ""}`,
          )
        : ["  No material receipts"]),
    );
    lines.push("Expected stock (calculated):");
    lines.push(
      ...progress.expected_remaining_stock.map(
        (stock) =>
          `  ${stock.id}: ${
            stock.kind === "tape" || stock.kind === "cord"
              ? stock.remaining_length_mm.value === null
                ? "Unknown length"
                : `${stock.remaining_length_mm.value} mm; ${stock.remaining_length_mm.source}; ${stock.remaining_length_mm.confirmed ? "confirmed input" : "unconfirmed"}`
              : `${stock.usable_regions?.length ?? 0} usable regions`
          }`,
      ),
    );
  }
  return lines.join("\n") + "\n";
}
