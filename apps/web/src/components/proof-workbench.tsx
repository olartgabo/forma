import { useEffect, useRef, useState } from "react";
import { ApiError, loadProof } from "../lib/api";
import { proofStatus, proofText, proofUnknowns } from "../lib/proof-report";
import type { Project, ProofSnapshot } from "../lib/generated/api-contracts";

function message(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "Could not load the proof snapshot. Try again.";
}

export default function ProofWorkbench({
  token,
  project,
  revision,
  disabled,
}: {
  token: string;
  project: Project;
  revision: number;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<ProofSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const lifetime = useRef(new AbortController());
  const epoch = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const requestEpoch = ++epoch.current;
    if (!open) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void loadProof(token, project.id, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted && requestEpoch === epoch.current)
          setSnapshot(next);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted && requestEpoch === epoch.current) {
          setSnapshot(null);
          setError(message(failure));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && requestEpoch === epoch.current)
          setLoading(false);
      });
    return () => controller.abort();
  }, [
    open,
    token,
    project.id,
    project.revision_id,
    project.active_version_id,
    revision,
    attempt,
  ]);

  async function download(format: "json" | "txt") {
    if (disabled || loading || exporting) return;
    const signal = lifetime.current.signal;
    const requestEpoch = ++epoch.current;
    setExporting(true);
    setError("");
    try {
      const next = await loadProof(token, project.id, signal);
      if (signal.aborted) return;
      if (requestEpoch !== epoch.current) {
        setError(
          "The proof snapshot changed while preparing the download. Download again to use the latest report.",
        );
        return;
      }
      setSnapshot(next);
      const text =
        format === "json"
          ? JSON.stringify(next, null, 2) + "\n"
          : proofText(next);
      const url = URL.createObjectURL(
        new Blob([text], {
          type:
            format === "json" ? "application/json" : "text/plain;charset=utf-8",
        }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `${next.project.id}-proof.${format}`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (failure) {
      if (!signal.aborted && requestEpoch === epoch.current)
        setError(message(failure));
    } finally {
      if (!signal.aborted) setExporting(false);
    }
  }

  return (
    <details
      className="proof-workbench"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Proof — saved plans, reports and evidence</summary>
      <p>
        Review the recorded claims and their sources. Downloads include your
        goal and notes; private photos are excluded.
      </p>
      <div className="proof-actions">
        <button
          type="button"
          className="secondary"
          disabled={disabled || loading || exporting}
          onClick={() => setAttempt((value) => value + 1)}
        >
          Refresh proof snapshot
        </button>
        <button
          type="button"
          disabled={disabled || loading || exporting}
          onClick={() => void download("txt")}
        >
          Download text summary
        </button>
        <button
          type="button"
          disabled={disabled || loading || exporting}
          onClick={() => void download("json")}
        >
          Download JSON report
        </button>
      </div>
      <div aria-live="polite">
        {loading && <p>Loading saved proof…</p>}
        {exporting && <p>Preparing a fresh report…</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
      {snapshot && (
        <div className="proof-report" aria-busy={loading || exporting}>
          <h2>Saved proof snapshot</h2>
          <p>
            Generated{" "}
            <time dateTime={snapshot.generated_at}>
              {snapshot.generated_at}
            </time>
          </p>
          <p>
            <strong>Goal:</strong> {snapshot.project.goal}
          </p>
          <p>{snapshot.photos_omitted} private photos excluded.</p>
          <p className="scope-note">
            This report covers initial plans and user reports. Repair revisions,
            preservation diffs and evidence invalidation are not integrated.
            Recorded timestamps are ingestion times; build duration, measured
            waste and salvage totals remain unavailable.
          </p>
          {snapshot.versions.length === 0 && (
            <p>No compiled plan or physical result is recorded.</p>
          )}
          <h3>Unknown or unconfirmed starting inputs</h3>
          {proofUnknowns(snapshot).length ? (
            <ul>
              {proofUnknowns(snapshot).map((unknown) => (
                <li key={unknown}>{unknown}</li>
              ))}
            </ul>
          ) : (
            <p>None in the saved fields shown here.</p>
          )}
          {snapshot.versions.map(
            ({ plan, progress, inventory_revision_id }) => (
              <article className="proof-version" key={plan.version_id}>
                <h3>
                  {plan.version_id === snapshot.project.active_version_id
                    ? "Active plan"
                    : "Saved preview"}
                </h3>
                <p className="project-id">
                  {plan.version_id} · Inventory {inventory_revision_id}
                </p>
                <p>
                  <strong>{proofStatus(progress.status)}</strong>
                </p>
                <p>
                  {progress.completed_operation_ids.length} of{" "}
                  {plan.operations.length} operations confirmed by user reports.
                </p>
                <details>
                  <summary>Uncompleted operations and checks</summary>
                  <ul>
                    {plan.operations
                      .filter(
                        (op) =>
                          !progress.completed_operation_ids.includes(op.id),
                      )
                      .map((op) => (
                        <li key={op.id}>
                          {op.id} · {op.type.replaceAll("_", " ")}
                        </li>
                      ))}
                  </ul>
                  {progress.completed_operation_ids.length ===
                    plan.operations.length && (
                    <p>
                      All planned operations have user reports. Evidence
                      coverage limits still apply.
                    </p>
                  )}
                </details>
                {plan.operations
                  .filter((op) => op.type === "functional_test")
                  .map((op) => (
                    <section className="test-conditions" key={op.id}>
                      <h4>Defined functional test</h4>
                      <p>{op.args.procedure}</p>
                      <p>
                        {op.args.device_label} ·{" "}
                        {op.args.mass_g === null
                          ? "Unknown mass"
                          : `${op.args.mass_g} g`}{" "}
                        · {op.args.duration_seconds} seconds · {op.args.surface}
                      </p>
                      <ul>
                        {op.args.pass_criteria.map((criterion, index) => (
                          <li key={index}>{criterion}</li>
                        ))}
                      </ul>
                      {progress.events.some(
                        (event) =>
                          event.operation_id === op.id && event.kind === "test",
                      ) ? (
                        <ul>
                          {progress.events
                            .filter(
                              (event) =>
                                event.operation_id === op.id &&
                                event.kind === "test",
                            )
                            .map((event) => (
                              <li key={event.id}>
                                User-reported result: {event.test_result} ·{" "}
                                {event.recorded_at}
                              </li>
                            ))}
                        </ul>
                      ) : (
                        <p>Not attempted.</p>
                      )}
                    </section>
                  ))}
                <details>
                  <summary>
                    User report timeline ({progress.events.length})
                  </summary>
                  {progress.events.length ? (
                    <ol>
                      {progress.events.map((event) => (
                        <li key={event.id}>
                          <strong>{event.operation_id}</strong> ·{" "}
                          {event.kind.replaceAll("_", " ")} ·{" "}
                          {event.test_result ??
                            event.verification_state.replaceAll("_", " ")}
                          <p>{event.observation}</p>
                          <time dateTime={event.recorded_at}>
                            {event.recorded_at}
                          </time>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p>No physical reports.</p>
                  )}
                </details>
                <details>
                  <summary>
                    Evidence provenance ({progress.evidence.length})
                  </summary>
                  {progress.evidence.length ? (
                    <ul>
                      {progress.evidence.map((item) => (
                        <li key={item.id}>
                          <strong>{item.kind.replaceAll("_", " ")}</strong> ·{" "}
                          {item.provenance} ·{" "}
                          {item.verification_state.replaceAll("_", " ")}
                          <p>{item.description}</p>
                          {item.kind === "photo" && (
                            <p className="help">Private image excluded.</p>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>No evidence recorded.</p>
                  )}
                </details>
                <details>
                  <summary>
                    Material receipts ({progress.material_transactions.length})
                  </summary>
                  <p className="help">
                    Quantities derive from planned operations reported as
                    performed. Whole-region consumption is the source area
                    retired by a cut; measured waste totals remain unknown.
                  </p>
                  {progress.material_transactions.length ? (
                    <ul>
                      {progress.material_transactions.map((item) => (
                        <li key={item.id}>
                          {item.operation_id}: {item.kind} {item.quantity}{" "}
                          {item.unit} · {item.source_stock_id}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>No material receipts.</p>
                  )}
                </details>
                <details>
                  <summary>Expected stock (calculated)</summary>
                  <p className="help">
                    Measure and reconcile actual stock before repair.
                  </p>
                  <ul>
                    {progress.expected_remaining_stock.map((stock) => (
                      <li key={stock.id}>
                        {stock.id}:{" "}
                        {stock.kind === "tape" || stock.kind === "cord"
                          ? stock.remaining_length_mm.value === null
                            ? "Unknown length"
                            : `${stock.remaining_length_mm.value} mm (${stock.remaining_length_mm.source}; ${stock.remaining_length_mm.confirmed ? "confirmed input" : "unconfirmed"})`
                          : `${stock.usable_regions?.length ?? 0} usable regions`}
                      </li>
                    ))}
                  </ul>
                </details>
              </article>
            ),
          )}
        </div>
      )}
    </details>
  );
}
