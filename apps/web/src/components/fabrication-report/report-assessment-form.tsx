import { useState } from "react";
import type {
  FabricationAssessment,
  FabricationReport,
} from "../../lib/generated/api-contracts";

export default function ReportAssessmentForm({
  report,
  onAssess,
}: {
  report: FabricationReport;
  onAssess: (body: FabricationAssessment) => void;
}) {
  const [lengths, setLengths] = useState<Record<string, string>>({});
  const [lengthsConfirmed, setLengthsConfirmed] = useState(false);
  const [tools, setTools] = useState("");
  const [toolsConfirmed, setToolsConfirmed] = useState(false);
  const ids = report.required_connector_measurement_ids ?? [];
  const missingTools = report.operations.some(
    (operation) =>
      operation.status !== "completed" &&
      operation.tools.some((tool) => tool.status !== "declared"),
  );
  const names = tools
    .split("\n")
    .map((tool) => tool.trim())
    .filter(Boolean);
  const validTools =
    names.length <= 32 &&
    names.every((tool) => tool.length <= 80) &&
    new Set(names.map((tool) => tool.toLowerCase())).size === names.length;
  const validLengths = ids.every(
    (id) =>
      lengths[id]?.trim() !== "" &&
      lengths[id] !== undefined &&
      Number.isFinite(Number(lengths[id])) &&
      Number(lengths[id]) >= 0,
  );
  const ready =
    (ids.length > 0 || names.length > 0) &&
    validLengths &&
    (ids.length === 0 || lengthsConfirmed) &&
    validTools &&
    (names.length === 0 || toolsConfirmed);
  if (ids.length === 0 && !missingTools) return null;

  return (
    <form
      className="fabrication-assessment"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready) return;
        onAssess({
          expected_inventory_revision_id: report.snapshot.inventory_revision_id,
          expected_last_event_id: report.snapshot.last_event_id,
          ...(ids.length > 0
            ? {
                connector_measurements: ids.map((stock_id) => ({
                  stock_id,
                  remaining_length_mm: Number(lengths[stock_id]),
                })),
                remaining_confirmed: true,
              }
            : {}),
          ...(names.length > 0
            ? { additional_tools: names, tools_confirmed: true }
            : {}),
        });
      }}
    >
      <h5>Confirm inputs for this report</h5>
      <p className="help">
        These inputs apply only to this report and saved history. They do not
        edit inventory, record physical evidence or approve work.
      </p>
      {ids.map((id) => (
        <label key={id}>
          Measured remaining {id} (mm)
          <input
            type="number"
            min="0"
            step="any"
            inputMode="decimal"
            value={lengths[id] ?? ""}
            onChange={(event) => {
              setLengths({ ...lengths, [id]: event.target.value });
              setLengthsConfirmed(false);
            }}
          />
        </label>
      ))}
      {ids.length > 0 && (
        <>
          <p className="help">
            A calculated balance is unconfirmed. If your measurement differs,
            record material loss or reconcile the build before continuing.
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={lengthsConfirmed}
              onChange={(event) => setLengthsConfirmed(event.target.checked)}
            />
            I measured these remaining lengths myself for this report.
          </label>
        </>
      )}
      {missingTools && (
        <>
          <label>
            Additional available tools, one per line
            <textarea
              rows={3}
              maxLength={2591}
              value={tools}
              onChange={(event) => {
                setTools(event.target.value);
                setToolsConfirmed(false);
              }}
            />
          </label>
          <p className="help">
            Name actual tools you have, such as scissors. Availability alone
            does not establish suitability or safe handling.
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={toolsConfirmed}
              onChange={(event) => setToolsConfirmed(event.target.checked)}
            />
            I checked these tools are available for this report.
          </label>
        </>
      )}
      <button type="submit" disabled={!ready}>
        Assess with my confirmed inputs
      </button>
    </form>
  );
}
