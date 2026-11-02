import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  approveRepair,
  loadProgress,
  simulateRepairs,
} from "../lib/api";
import type { RepairPatch } from "../lib/generated/contracts";
import type {
  AdaptCommitRequest,
  AdaptPreview,
  AdaptPreviewSet,
  AdaptSimulateRequest,
  PlanVersion,
  ProgressSnapshot,
} from "../lib/generated/api-contracts";
import type { BuildPlan } from "../lib/generated/contracts";
import { operationTitles } from "../lib/operation-titles";
import Diagram from "./manual-diagram";

function message(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "Could not review this repair. Try again.";
}

type Draft = {
  kind: "replace_part" | "resize_part";
  targetId: string;
  stockId: string;
  width: string;
  height: string;
  rationale: string;
};

const emptyDraft: Draft = {
  kind: "replace_part",
  targetId: "",
  stockId: "",
  width: "",
  height: "",
  rationale: "",
};

function positive(value: string) {
  const number = Number(value);
  return value.trim() !== "" && Number.isFinite(number) && number > 0
    ? number
    : null;
}

function IdList({ label, ids }: { label: string; ids: readonly string[] }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{ids.length === 0 ? "None" : ids.join(", ")}</dd>
    </>
  );
}

function StepList({
  label,
  ids,
  plans,
}: {
  label: string;
  ids: readonly string[];
  plans: readonly BuildPlan[];
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd>
        {ids.length === 0 ? (
          "None"
        ) : (
          <ul>
            {ids.map((id) => {
              const type = plans
                .flatMap((plan) => plan.operations)
                .find((operation) => operation.id === id)?.type;
              return (
                <li key={id}>
                  {operationTitles[type ?? ""] ?? "Assembly step"}{" "}
                  <span className="help">{id}</span>
                </li>
              );
            })}
          </ul>
        )}
      </dd>
    </>
  );
}

function Preview({
  preview,
  base,
  selected,
  onSelect,
  disabled,
}: {
  preview: AdaptPreview;
  base: PlanVersion;
  selected: boolean;
  onSelect: () => void;
  disabled: boolean;
}) {
  const simulation = preview.simulation;
  const plans = preview.version
    ? [preview.version.plan, base.plan]
    : [base.plan];
  const panels = preview.version?.manual.panels ?? [];
  const diff = preview.panel_diff;
  const updated = diff
    ? [...diff.changed, ...diff.added].sort((a, b) => a - b)
    : [];
  return (
    <article className={`adapt-preview${selected ? " selected" : ""}`}>
      <h4>
        {preview.rank === null || preview.rank === undefined
          ? "Blocked candidate"
          : `Option ${preview.rank}`}{" "}
        · {preview.patch.kind.replaceAll("_", " ")} {preview.patch.target_id}
      </h4>
      <p>{preview.patch.rationale}</p>
      {(simulation.blockers?.length ?? 0) > 0 && (
        <ul className="error">
          {simulation.blockers?.map((blocker, index) => (
            <li key={index}>
              {blocker.message}
              {blocker.target_ids && blocker.target_ids.length > 0
                ? ` (${blocker.target_ids.join(", ")})`
                : ""}
            </li>
          ))}
        </ul>
      )}
      {(preview.render_blockers?.length ?? 0) > 0 && (
        <ul className="error">
          {preview.render_blockers?.map((blocker, index) => (
            <li key={index}>Manual: {blocker.message}</li>
          ))}
        </ul>
      )}
      {simulation.status === "feasible" && (
        <dl className="adapt-diff">
          <dt>Original version</dt>
          <dd>{base.version_id}</dd>
          <StepList
            label="Kept"
            ids={simulation.preserved_operation_ids ?? []}
            plans={plans}
          />
          <StepList
            label="To undo physically"
            ids={simulation.required_undo_operation_ids ?? []}
            plans={plans}
          />
          <StepList
            label="Redo"
            ids={simulation.redo_operation_ids ?? []}
            plans={plans}
          />
          <StepList
            label="New work"
            ids={simulation.newly_required_operation_ids ?? []}
            plans={plans}
          />
          <IdList label="Lost parts" ids={simulation.lost_part_ids ?? []} />
          <StepList
            label="Lost work"
            ids={simulation.lost_operation_ids ?? []}
            plans={plans}
          />
          <IdList
            label="Stock used for the repair"
            ids={simulation.additional_material_stock_ids ?? []}
          />
          <IdList
            label="Checks to repeat"
            ids={simulation.invalidated_checkpoint_ids ?? []}
          />
          <dt>Evidence that becomes historical</dt>
          <dd>{simulation.invalidated_evidence_ids?.length ?? 0} records</dd>
          {simulation.cost && (
            <>
              <dt>Known repair cost</dt>
              <dd>
                {simulation.cost.known_weighted_cost} (lost completed actions{" "}
                {simulation.cost.irreversible_completed_actions_lost}, undos{" "}
                {simulation.cost.required_physical_undos}, new irreversible
                actions {simulation.cost.new_irreversible_actions}). Time, waste
                and price are not estimated.
              </dd>
            </>
          )}
          {diff && (
            <>
              <dt>Updated panels</dt>
              <dd>
                {updated.length === 0
                  ? "None"
                  : `Steps ${updated.map((index) => index + 1).join(", ")}`}{" "}
                · {diff.unchanged.length} unchanged
              </dd>
            </>
          )}
        </dl>
      )}
      {updated.length > 0 && (
        <details>
          <summary>Show updated steps</summary>
          {updated.map((index) => (
            <figure key={index}>
              <figcaption>
                Step {index + 1}: {panels[index].instruction}
              </figcaption>
              <Diagram panel={panels[index]} />
            </figure>
          ))}
        </details>
      )}
      {preview.version && (
        <label className="checkbox-label">
          <input
            type="radio"
            name="adapt-choice"
            checked={selected}
            disabled={disabled}
            onChange={onSelect}
          />
          Choose this revision
        </label>
      )}
    </article>
  );
}

export default function AdaptWorkbench({
  token,
  projectId,
  version,
  disabled,
  onApproved,
  onLockChange,
}: {
  token: string;
  projectId: string;
  version: PlanVersion;
  disabled: boolean;
  onApproved: () => void;
  onLockChange: (locked: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [progress, setProgress] = useState<ProgressSnapshot | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [candidates, setCandidates] = useState<readonly RepairPatch[]>([]);
  const [lengths, setLengths] = useState<Record<string, string>>({});
  const [remainingConfirmed, setRemainingConfirmed] = useState(false);
  const [previews, setPreviews] = useState<AdaptPreviewSet | null>(null);
  const [choice, setChoice] = useState("");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [pendingSimulation, setPendingSimulation] =
    useState<AdaptSimulateRequest | null>(null);
  const [pendingApproval, setPendingApproval] =
    useState<AdaptCommitRequest | null>(null);
  const lifetime = useRef(new AbortController());
  const plan = version.plan;
  const spent =
    progress?.expected_remaining_stock.filter(
      (stock) =>
        (stock.kind === "tape" || stock.kind === "cord") &&
        stock.remaining_length_mm.source === "calculated" &&
        !stock.remaining_length_mm.confirmed,
    ) ?? [];
  const sheets =
    progress?.expected_remaining_stock.filter(
      (stock) =>
        stock.kind === "sheet" && (stock.usable_regions?.length ?? 0) > 0,
    ) ?? [];
  const locked = disabled || busy;

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, []);

  useEffect(() => {
    // A different active version invalidates every draft and preview.
    setProgress(null);
    setCandidates([]);
    setPreviews(null);
    setChoice("");
    setApproved(false);
    setLengths({});
    setRemainingConfirmed(false);
    setPendingSimulation(null);
    setPendingApproval(null);
    setStale(false);
  }, [version.version_id]);

  async function refresh() {
    const signal = lifetime.current.signal;
    setBusy(true);
    setError("");
    try {
      const next = await loadProgress(
        token,
        projectId,
        version.version_id,
        signal,
      );
      if (signal.aborted) return;
      setProgress(next);
      setPreviews(null);
      setChoice("");
      setApproved(false);
      setStale(false);
    } catch (failure) {
      if (!signal.aborted) setError(message(failure));
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  }

  function addCandidate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.targetId || !draft.rationale.trim() || candidates.length >= 3)
      return;
    const width = positive(draft.width);
    const height = positive(draft.height);
    if (draft.kind === "replace_part" && !draft.stockId) return;
    if (draft.kind === "resize_part" && width === null && height === null)
      return;
    setCandidates((current) => [
      ...current,
      {
        id: `repair-${crypto.randomUUID()}`,
        base_version_id: version.version_id,
        kind: draft.kind,
        target_id: draft.targetId,
        replacement_stock_id:
          draft.kind === "replace_part" ? draft.stockId : null,
        replacement_profile_id: null,
        width_mm: draft.kind === "resize_part" ? width : null,
        height_mm: draft.kind === "resize_part" ? height : null,
        angle_deg: null,
        rationale: draft.rationale.trim(),
      },
    ]);
    setDraft(emptyDraft);
    setPreviews(null);
  }

  async function simulate(request: AdaptSimulateRequest) {
    const signal = lifetime.current.signal;
    setPendingSimulation(request);
    setBusy(true);
    onLockChange(true);
    setError("");
    try {
      const result = await simulateRepairs(token, projectId, request, signal);
      if (signal.aborted) return;
      setPendingSimulation(null);
      setPreviews(result);
      setChoice(result.previews.find((item) => item.version)?.preview_id ?? "");
      setApproved(false);
    } catch (failure) {
      if (signal.aborted) return;
      setError(message(failure));
      if (failure instanceof ApiError && failure.status >= 400) {
        setPendingSimulation(null);
        setStale(failure.status === 409);
      }
    } finally {
      if (!signal.aborted) {
        setBusy(false);
        onLockChange(false);
      }
    }
  }

  async function approve(request: AdaptCommitRequest) {
    const signal = lifetime.current.signal;
    setPendingApproval(request);
    setBusy(true);
    onLockChange(true);
    setError("");
    try {
      await approveRepair(token, projectId, request, signal);
      if (signal.aborted) return;
      setPendingApproval(null);
      onLockChange(false);
      onApproved();
    } catch (failure) {
      if (signal.aborted) return;
      setError(message(failure));
      if (failure instanceof ApiError && failure.status >= 400) {
        setPendingApproval(null);
        setStale(failure.status === 409);
      }
    } finally {
      if (!signal.aborted) {
        setBusy(false);
        onLockChange(false);
      }
    }
  }

  function submitSimulation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!progress || candidates.length === 0 || !remainingConfirmed || locked)
      return;
    const measurements = spent.map((stock) => ({
      stock_id: stock.id,
      remaining_length_mm: Number(lengths[stock.id]),
    }));
    if (
      measurements.some(
        (item, index) =>
          !Number.isFinite(item.remaining_length_mm) ||
          item.remaining_length_mm < 0 ||
          (lengths[spent[index].id] ?? "").trim() === "",
      )
    )
      return;
    void simulate({
      expected_version_id: version.version_id,
      expected_last_event_id: progress.last_event_id ?? null,
      idempotency_key: crypto.randomUUID(),
      candidates: [...candidates],
      connector_measurements: measurements,
      remaining_confirmed: true,
    });
  }

  const chosen = previews?.previews.find((item) => item.preview_id === choice);

  return (
    <section className="adapt-workbench" aria-labelledby="adapt-title">
      <h3 id="adapt-title">Adapt the plan</h3>
      <p className="help">
        Use this after a failed check, a damaged part or a wrong measurement.
        FORMA simulates each repair against your recorded work and remaining
        stock. Nothing changes until you approve one revision.
      </p>
      {!open ? (
        <button
          type="button"
          className="secondary"
          disabled={locked}
          onClick={() => {
            setOpen(true);
            void refresh();
          }}
        >
          Review a repair
        </button>
      ) : (
        <>
          <div aria-live="polite">
            {busy && <p>Working…</p>}
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
          </div>
          <button
            type="button"
            className="secondary"
            disabled={locked}
            onClick={() => {
              if (stale) onApproved();
              void refresh();
            }}
          >
            {stale ? "Reload project and history" : "Reload recorded work"}
          </button>
          {progress && (
            <>
              <p>
                {progress.completed_operation_ids.length} of{" "}
                {plan.operations.length} operations recorded as done.
                {progress.failed_operation_ids.length > 0 &&
                  ` Failed checks: ${progress.failed_operation_ids.join(", ")}.`}
              </p>
              <form className="adapt-candidate" onSubmit={addCandidate}>
                <fieldset disabled={locked || candidates.length >= 3}>
                  <legend>
                    Add a repair candidate ({candidates.length}/3)
                  </legend>
                  <label>
                    Repair
                    <select
                      value={draft.kind}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          kind: event.target.value as Draft["kind"],
                        })
                      }
                    >
                      <option value="replace_part">
                        Replace a part from remaining stock
                      </option>
                      <option value="resize_part">Resize a future part</option>
                    </select>
                  </label>
                  <label>
                    Part
                    <select
                      value={draft.targetId}
                      onChange={(event) =>
                        setDraft({ ...draft, targetId: event.target.value })
                      }
                    >
                      <option value="">Choose a part</option>
                      {plan.parts.map((part) => (
                        <option key={part.id} value={part.id}>
                          {part.id} ({part.geometry.width.toFixed(1)} ×{" "}
                          {part.geometry.height.toFixed(1)} mm)
                        </option>
                      ))}
                    </select>
                  </label>
                  {draft.kind === "replace_part" ? (
                    <label>
                      Replacement stock
                      <select
                        value={draft.stockId}
                        onChange={(event) =>
                          setDraft({ ...draft, stockId: event.target.value })
                        }
                      >
                        <option value="">Choose remaining stock</option>
                        {sheets.map((stock) => (
                          <option key={stock.id} value={stock.id}>
                            {stock.id} ({stock.usable_regions?.length} usable
                            regions)
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : (
                    <>
                      <label>
                        New width (mm)
                        <input
                          inputMode="decimal"
                          value={draft.width}
                          onChange={(event) =>
                            setDraft({ ...draft, width: event.target.value })
                          }
                        />
                      </label>
                      <label>
                        New height (mm)
                        <input
                          inputMode="decimal"
                          value={draft.height}
                          onChange={(event) =>
                            setDraft({ ...draft, height: event.target.value })
                          }
                        />
                      </label>
                    </>
                  )}
                  <label>
                    What went wrong
                    <textarea
                      maxLength={2000}
                      value={draft.rationale}
                      onChange={(event) =>
                        setDraft({ ...draft, rationale: event.target.value })
                      }
                    />
                  </label>
                  <button type="submit" className="secondary">
                    Add candidate
                  </button>
                </fieldset>
              </form>
              {candidates.length > 0 && (
                <ol className="adapt-candidates">
                  {candidates.map((candidate) => (
                    <li key={candidate.id}>
                      {candidate.kind.replaceAll("_", " ")}{" "}
                      {candidate.target_id}
                      {candidate.replacement_stock_id
                        ? ` from ${candidate.replacement_stock_id}`
                        : ""}{" "}
                      <button
                        type="button"
                        className="quiet"
                        disabled={locked}
                        onClick={() => {
                          setCandidates((current) =>
                            current.filter((item) => item.id !== candidate.id),
                          );
                          setPreviews(null);
                        }}
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ol>
              )}
              <form onSubmit={submitSimulation}>
                <fieldset disabled={locked}>
                  <legend>Confirm what is left</legend>
                  {spent.map((stock) => (
                    <label key={stock.id}>
                      Measured remaining {stock.kind} on {stock.id} (calculated{" "}
                      {stock.remaining_length_mm.value} mm)
                      <input
                        inputMode="decimal"
                        required
                        value={lengths[stock.id] ?? ""}
                        onChange={(event) =>
                          setLengths({
                            ...lengths,
                            [stock.id]: event.target.value,
                          })
                        }
                      />
                    </label>
                  ))}
                  <ul>
                    {progress.expected_remaining_stock
                      .filter((stock) => stock.kind === "sheet")
                      .map((stock) => (
                        <li key={stock.id}>
                          {stock.id}: {stock.usable_regions?.length ?? 0} usable
                          regions expected
                        </li>
                      ))}
                  </ul>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={remainingConfirmed}
                      onChange={(event) =>
                        setRemainingConfirmed(event.target.checked)
                      }
                    />
                    I checked the remaining materials and measured the
                    connectors above.
                  </label>
                  <button
                    type="submit"
                    className="primary"
                    disabled={candidates.length === 0 || !remainingConfirmed}
                  >
                    Simulate repairs
                  </button>
                </fieldset>
              </form>
            </>
          )}
          {pendingSimulation && !busy && (
            <aside className="retry-panel">
              <p>
                The connection ended before the simulation finished. Retrying
                the same request returns the saved result if there is one.
              </p>
              <button
                type="button"
                disabled={disabled}
                onClick={() => void simulate(pendingSimulation)}
              >
                Retry simulation
              </button>
            </aside>
          )}
          {previews && (
            <div className="adapt-previews">
              <h4>Repair options</h4>
              {previews.previews.map((preview) => (
                <Preview
                  key={preview.preview_id}
                  preview={preview}
                  base={version}
                  selected={preview.preview_id === choice}
                  disabled={locked}
                  onSelect={() => {
                    setChoice(preview.preview_id);
                    setApproved(false);
                  }}
                />
              ))}
              {chosen?.version && (
                <div className="plan-approval">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={approved}
                      disabled={locked}
                      onChange={(event) => setApproved(event.target.checked)}
                    />
                    I approve this revision. Recorded work stays in history; the
                    listed checks must be repeated.
                  </label>
                  <button
                    type="button"
                    className="primary"
                    disabled={!approved || locked || pendingApproval !== null}
                    onClick={() =>
                      void approve({
                        expected_version_id: version.version_id,
                        expected_last_event_id:
                          previews.base_last_event_id ?? null,
                        preview_id: chosen.preview_id,
                        idempotency_key: crypto.randomUUID(),
                        user_approved: true,
                      })
                    }
                  >
                    Activate revision
                  </button>
                </div>
              )}
              {previews.previews.every((preview) => !preview.version) && (
                <p>
                  No candidate passed the checks. Change the candidates, measure
                  again, or record what is missing.
                </p>
              )}
            </div>
          )}
          {pendingApproval && !busy && (
            <aside className="retry-panel">
              <p>
                The connection ended before approval was confirmed. Retry the
                same approval to check whether the revision is active.
              </p>
              <button
                type="button"
                disabled={disabled}
                onClick={() => void approve(pendingApproval)}
              >
                Retry approval
              </button>
            </aside>
          )}
        </>
      )}
    </section>
  );
}
