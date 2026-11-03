import { useEffect, useRef, useState } from "react";
import { ApiError, loadProof } from "../lib/api";
import {
  proofStatus,
  evidenceLabel,
  proofText,
  recordedMaterial,
  proofUnknowns,
  proofVersionLabel,
  revisionDetails,
} from "../lib/proof-report";
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
  diagnosisPending = false,
  diagnosisUncertain = false,
}: {
  token: string;
  project: Project;
  revision: number;
  disabled: boolean;
  diagnosisPending?: boolean;
  diagnosisUncertain?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<ProofSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [asOfAcknowledged, setAsOfAcknowledged] = useState(false);
  const [reconciled, setReconciled] = useState(false);
  const manualRefresh = useRef(false);
  const lifetime = useRef(new AbortController());
  const epoch = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const requestEpoch = ++epoch.current;
    const requestedReconciliation = manualRefresh.current;
    manualRefresh.current = false;
    setAsOfAcknowledged(false);
    setReconciled(false);
    setSnapshot(null);
    if (diagnosisPending) {
      setLoading(false);
      return;
    }
    if (!open) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void loadProof(token, project.id, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted && requestEpoch === epoch.current) {
          setSnapshot(next);
          setReconciled(requestedReconciliation);
        }
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
    diagnosisPending,
    diagnosisUncertain,
  ]);

  async function download(format: "json" | "txt") {
    if (
      disabled ||
      loading ||
      exporting ||
      diagnosisPending ||
      (diagnosisUncertain && !asOfAcknowledged)
    )
      return;
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
          disabled={disabled || loading || exporting || diagnosisPending}
          onClick={() => {
            manualRefresh.current = true;
            setAttempt((value) => value + 1);
          }}
        >
          Refresh proof snapshot
        </button>
        <button
          type="button"
          disabled={
            disabled ||
            loading ||
            exporting ||
            diagnosisPending ||
            (diagnosisUncertain && !asOfAcknowledged)
          }
          onClick={() => void download("txt")}
        >
          Download text summary
        </button>
        <button
          type="button"
          disabled={
            disabled ||
            loading ||
            exporting ||
            diagnosisPending ||
            (diagnosisUncertain && !asOfAcknowledged)
          }
          onClick={() => void download("json")}
        >
          Download JSON report
        </button>
      </div>
      <div aria-live="polite">
        {diagnosisPending && (
          <p>
            Diagnosis is pending. Earlier proof snapshots and downloads are
            unavailable.
          </p>
        )}
        {diagnosisUncertain && (
          <p role="status">
            The diagnosis outcome is unknown. It may still save evidence later.
            Refresh to inspect current saved history; a snapshot does not
            establish that the request finished.
          </p>
        )}
        {loading && <p>Loading saved proof…</p>}
        {exporting && <p>Preparing a fresh report…</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
      {diagnosisUncertain && reconciled && snapshot && !diagnosisPending && (
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={asOfAcknowledged}
            onChange={(event) => setAsOfAcknowledged(event.target.checked)}
          />
          Use current saved snapshot for an as-of report despite the unknown
          diagnosis outcome. The download fetches fresh history dated by its
          generation time; the request may still save evidence later.
        </label>
      )}
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
            This report covers versioned plans, user reports, approved repairs
            and evidence invalidations. Historical outcomes describe their
            recorded version and do not verify a revised plan. Recorded
            timestamps are ingestion times; build duration is unavailable, and
            waste and salvage cover only what the builder recorded.
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
          {snapshot.versions.map((version) => {
            const { plan, progress, inventory_revision_id } = version;
            return (
              <article className="proof-version" key={plan.version_id}>
                <h3>{proofVersionLabel(version.state)}</h3>
                <p className="project-id">
                  {plan.version_id} · Inventory {inventory_revision_id}
                </p>
                <p>
                  <strong>{proofStatus(progress.status)}</strong>
                </p>
                <p>
                  {progress.completed_operation_ids.length} of{" "}
                  {plan.operations.length} operations completed, including{" "}
                  {progress.carried_operation_ids?.length ?? 0} carried from
                  earlier reports. This version has{" "}
                  {
                    progress.events.filter(
                      (event) => event.kind === "operation_confirmed",
                    ).length
                  }{" "}
                  new completion reports.
                </p>
                {version.state === "historical" && (
                  <p className="scope-note">
                    Historical reports remain unchanged. Check the invalidation
                    notices below before using evidence for a later version.
                  </p>
                )}
                {version.revision && (
                  <details>
                    <summary>Approved repair and required rechecks</summary>
                    <p>
                      Approval records the plan change. Physical undo, redo and
                      new work still require user reports.
                    </p>
                    <dl>
                      {revisionDetails(version).map(([label, value]) => (
                        <div key={label}>
                          <dt>{label}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))}
                    </dl>
                  </details>
                )}
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
                      All planned operations are completed or carried from
                      earlier reports. Evidence coverage limits still apply.
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
                          <strong>{evidenceLabel(item.kind)}</strong> ·{" "}
                          {item.provenance} ·{" "}
                          {item.verification_state.replaceAll("_", " ")}
                          <p>{item.description}</p>
                          <p className="help">
                            Checkpoints:{" "}
                            {item.checkpoint_ids?.join(", ") || "None"}
                          </p>
                          {version.invalidations
                            ?.filter(
                              (invalidation) =>
                                invalidation.evidence_id === item.id,
                            )
                            .map((invalidation) => (
                              <p key={invalidation.id} className="scope-note">
                                Invalidated for{" "}
                                {invalidation.invalidated_for_version_id} at{" "}
                                {invalidation.recorded_at}:{" "}
                                {invalidation.reason}
                              </p>
                            ))}
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
                    Consumption derives from planned operations reported as
                    performed; a cut retires its whole source region. Waste and
                    recovered material come from the builder&apos;s material
                    records.
                  </p>
                  <p>{recordedMaterial(progress)}</p>
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
            );
          })}
        </div>
      )}
    </details>
  );
}
