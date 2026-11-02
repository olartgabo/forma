import type { ProofSnapshot } from "./generated/api-contracts";

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
    "Coverage: initial plans and user reports.",
    `Private photos excluded: ${snapshot.photos_omitted}.`,
    "Repair revisions, preservation diffs and evidence invalidation are not integrated.",
    "Expected stock is calculated and needs actual measurement/reconciliation before repair.",
    "Recorded timestamps are report ingestion times. Build duration, measured waste and salvage totals are unavailable.",
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
      `Version: ${plan.version_id}${snapshot.project.active_version_id === plan.version_id ? " (active)" : " (saved preview)"}`,
      `Inventory revision: ${version.inventory_revision_id}`,
      `Candidate: ${version.candidate_id}`,
      `Compiler: ${plan.compiler_version}`,
      `Physical outcome: ${proofStatus(progress.status)}`,
      `Confirmed operations: ${progress.completed_operation_ids.length} / ${plan.operations.length}`,
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
            `  ${item.id} | ${item.kind} | ${item.provenance} | ${item.verification_state}${item.kind === "photo" ? " | image excluded" : ""}`,
            `    ${item.description}`,
          ])
        : ["  No evidence recorded"]),
    );
    lines.push("Material receipts derived from reported operations:");
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
