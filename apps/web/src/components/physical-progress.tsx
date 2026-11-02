import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, loadProgress, recordProgress } from "../lib/api";
import type {
  Media,
  PlanVersion,
  ProgressSnapshot,
  ProgressUpdate,
} from "../lib/generated/api-contracts";

function message(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "Could not save this report. Try again.";
}

export default function PhysicalProgress({
  token,
  projectId,
  version,
  operationId,
  photos,
  disabled,
  onLockChange,
  onReloadProject,
}: {
  token: string;
  projectId: string;
  version: PlanVersion;
  operationId: string;
  photos: readonly Media[];
  disabled: boolean;
  onLockChange: (locked: boolean) => void;
  onReloadProject: () => void;
}) {
  const [progress, setProgress] = useState<ProgressSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [readFailed, setReadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [stale, setStale] = useState(false);
  const [checks, setChecks] = useState<readonly string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<"passed" | "failed" | "">("");
  const [observation, setObservation] = useState("");
  const [photoIds, setPhotoIds] = useState<readonly string[]>([]);
  const [pending, setPending] = useState<ProgressUpdate | null>(null);
  const [saving, setSaving] = useState(false);
  const controller = useRef(new AbortController());
  const operation = version.plan.operations.find(
    (item) => item.id === operationId,
  );
  const checkOperation =
    operation?.type === "inspect" || operation?.type === "functional_test";
  const completed =
    progress?.completed_operation_ids.includes(operationId) ?? false;
  const missingPredecessors =
    operation?.depends_on?.filter(
      (id) => !progress?.completed_operation_ids.includes(id),
    ) ?? [];
  const requiredChecks = operation
    ? [
        ...(operation.preconditions.safe_tools_confirmed
          ? [
              "Check the required measurements and safe tools before performing this operation.",
            ]
          : []),
        ...(operation.preconditions.human_checks ?? []),
        ...((operation.preconditions.accessible_part_ids?.length ?? 0) > 0
          ? [
              `Confirm access to ${operation.preconditions.accessible_part_ids?.join(", ")}.`,
            ]
          : []),
        ...((operation.preconditions.required_joint_ids?.length ?? 0) > 0
          ? [
              `Confirm these joints are attached: ${operation.preconditions.required_joint_ids?.join(", ")}.`,
            ]
          : []),
        ...((operation.preconditions.confirmed_measurement_ids?.length ?? 0) > 0
          ? [
              `Check required measurements: ${operation.preconditions.confirmed_measurement_ids?.join(", ")}.`,
            ]
          : []),
        ...version.plan.checkpoints
          .filter((checkpoint) => checkpoint.after_operation_id === operationId)
          .map((checkpoint) => checkpoint.description),
      ]
    : [];
  const ready =
    progress !== null &&
    !loading &&
    !readFailed &&
    !stale &&
    !completed &&
    missingPredecessors.length === 0 &&
    progress.status !== "needs_review" &&
    progress.status !== "passed";
  const locked = disabled || saving || pending !== null;

  useEffect(() => {
    const lifetime = new AbortController();
    controller.current = lifetime;
    return () => lifetime.abort();
  }, []);

  useEffect(() => {
    const read = new AbortController();
    setLoading(true);
    setReadFailed(false);
    setError("");
    void loadProgress(token, projectId, version.version_id, read.signal)
      .then((next) => {
        if (read.signal.aborted) return;
        setProgress(next);
        setStale(false);
      })
      .catch((failure: unknown) => {
        if (!read.signal.aborted) {
          setError(message(failure));
          setReadFailed(true);
          setProgress(null);
        }
      })
      .finally(() => {
        if (!read.signal.aborted) setLoading(false);
      });
    return () => read.abort();
  }, [token, projectId, version.version_id, attempt]);

  useEffect(() => {
    setChecks([]);
    setConfirmed(false);
    setResult("");
    setObservation("");
    setPhotoIds([]);
    setNotice("");
  }, [operationId, attempt]);

  async function save(request: ProgressUpdate) {
    if (saving || disabled) return;
    const signal = controller.current.signal;
    setPending(request);
    setSaving(true);
    onLockChange(true);
    setError("");
    setNotice("");
    let reportKnown = false;
    try {
      const response = await recordProgress(token, projectId, request, signal);
      if (signal.aborted) return;
      reportKnown = true;
      setPending(null);
      setChecks([]);
      setConfirmed(false);
      setResult("");
      setObservation("");
      setPhotoIds([]);
      const latest = response.replayed
        ? await loadProgress(token, projectId, version.version_id, signal)
        : response.progress;
      if (signal.aborted) return;
      setProgress(latest);
      setReadFailed(false);
      setNotice(
        latest.status === "needs_review"
          ? "Failed check saved. Stop and review the build before continuing."
          : "Your physical report was saved.",
      );
    } catch (failure) {
      if (signal.aborted) return;
      setError(message(failure));
      if (reportKnown) {
        setReadFailed(true);
        setProgress(null);
        setNotice(
          "Your report was saved. Refresh physical reports to load the current history before continuing.",
        );
      } else if (
        failure instanceof ApiError &&
        failure.status >= 400 &&
        failure.status < 500
      ) {
        setPending(null);
        onLockChange(false);
        setStale(failure.status === 409);
      }
    } finally {
      if (!signal.aborted) {
        setSaving(false);
        if (reportKnown) onLockChange(false);
      }
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !ready ||
      locked ||
      !confirmed ||
      !observation.trim() ||
      requiredChecks.some((_, index) => !checks.includes(String(index))) ||
      (checkOperation && !result)
    )
      return;
    const reportedResult = checkOperation ? result : "completed";
    if (!reportedResult) return;
    void save({
      expected_version_id: version.version_id,
      expected_last_event_id: progress?.last_event_id ?? null,
      idempotency_key: crypto.randomUUID(),
      operation_id: operationId,
      result: reportedResult,
      observation: observation.trim(),
      user_confirmed: true,
      checks_confirmed: true,
      photo_ids: [...photoIds],
    });
  }

  return (
    <section
      className="physical-progress"
      aria-labelledby="progress-title"
      aria-busy={loading || saving}
    >
      <h3 id="progress-title">Record what actually happened</h3>
      <p className="help">
        Report only work you performed and checks you observed. Browsing
        instructions records no completion.
      </p>
      <div aria-live="polite">
        {loading && <p>Loading physical reports…</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {notice && <p className="notice">{notice}</p>}
        {progress?.status === "not_started" && (
          <p>No physical work recorded.</p>
        )}
        {progress?.status === "building" && (
          <p>
            {progress.completed_operation_ids.length} of{" "}
            {version.plan.operations.length} operations confirmed by you.
          </p>
        )}
        {progress?.status === "needs_review" && (
          <p className="error">
            A check failed. Further confirmations are paused until diagnosis or
            an approved revision resolves it. The failed report remains in
            history.
          </p>
        )}
        {progress?.status === "passed" && (
          <p className="notice">
            Defined functional test passed — user reported. See the recorded
            procedure and conditions.
          </p>
        )}
      </div>
      <button
        type="button"
        className="secondary"
        disabled={locked || loading}
        onClick={() => {
          if (stale) onReloadProject();
          setAttempt((value) => value + 1);
        }}
      >
        {stale
          ? "Reload project and physical reports"
          : "Refresh physical reports"}
      </button>
      {completed && (
        <p>
          This operation is already confirmed. Its report remains in history.
        </p>
      )}
      {progress && missingPredecessors.length > 0 && (
        <p>
          Confirm these prerequisite operations first:{" "}
          {missingPredecessors.join(", ")}.
        </p>
      )}
      {operation?.type === "functional_test" && (
        <div className="test-conditions">
          <h4>Defined test conditions</h4>
          <p>{operation.args.procedure}</p>
          <dl>
            <dt>Device</dt>
            <dd>{operation.args.device_label}</dd>
            <dt>Mass</dt>
            <dd>
              {operation.args.mass_g === null
                ? "Unknown"
                : `${operation.args.mass_g} g`}
            </dd>
            <dt>Duration</dt>
            <dd>{operation.args.duration_seconds} seconds</dd>
            <dt>Surface</dt>
            <dd>{operation.args.surface}</dd>
          </dl>
          <ul>
            {operation.args.pass_criteria.map((criterion, index) => (
              <li key={index}>{criterion}</li>
            ))}
          </ul>
        </div>
      )}
      {ready && (
        <form onSubmit={submit}>
          <fieldset disabled={locked}>
            {requiredChecks.length > 0 && (
              <fieldset className="physical-checks">
                <legend>Checks I performed for this operation</legend>
                {requiredChecks.map((check, index) => (
                  <label className="checkbox-label" key={index}>
                    <input
                      type="checkbox"
                      checked={checks.includes(String(index))}
                      onChange={(event) =>
                        setChecks((current) =>
                          event.target.checked
                            ? [...current, String(index)]
                            : current.filter((id) => id !== String(index)),
                        )
                      }
                    />
                    {check}
                  </label>
                ))}
              </fieldset>
            )}
            {checkOperation && (
              <fieldset className="physical-result">
                <legend>What was the result?</legend>
                <label className="checkbox-label">
                  <input
                    type="radio"
                    name="physical-result"
                    value="passed"
                    checked={result === "passed"}
                    onChange={() => setResult("passed")}
                    required
                  />
                  Passed the displayed checks
                </label>
                <label className="checkbox-label">
                  <input
                    type="radio"
                    name="physical-result"
                    value="failed"
                    checked={result === "failed"}
                    onChange={() => setResult("failed")}
                    required
                  />
                  Failed a displayed check
                </label>
              </fieldset>
            )}
            <label htmlFor="physical-observation">
              What did you do or observe?
            </label>
            <textarea
              id="physical-observation"
              rows={3}
              maxLength={2000}
              required
              value={observation}
              onChange={(event) => setObservation(event.target.value)}
            />
            {photos.length > 0 && (
              <fieldset className="photo-links">
                <legend>Optional photos of this result</legend>
                {photos.map((photo, index) => (
                  <label className="checkbox-label" key={photo.id}>
                    <input
                      type="checkbox"
                      checked={photoIds.includes(photo.id)}
                      disabled={
                        !photoIds.includes(photo.id) && photoIds.length >= 8
                      }
                      onChange={(event) =>
                        setPhotoIds((current) =>
                          event.target.checked
                            ? [...current, photo.id]
                            : current.filter((id) => id !== photo.id),
                        )
                      }
                    />
                    Photo {index + 1}
                  </label>
                ))}
                <p className="help">
                  Select up to eight photos. Photos linked to reports remain
                  part of the project history.
                </p>
              </fieldset>
            )}
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              I performed this operation or check and am reporting its actual
              result.
            </label>
            <button
              type="submit"
              className="primary"
              disabled={
                !confirmed ||
                !observation.trim() ||
                requiredChecks.some(
                  (_, index) => !checks.includes(String(index)),
                ) ||
                (checkOperation && !result)
              }
            >
              Save physical report
            </button>
          </fieldset>
        </form>
      )}
      {pending && !saving && (
        <aside className="retry-panel">
          <h4>Check the unfinished report</h4>
          <p>
            The connection ended before the result was known. Retry this exact
            report to check whether it was saved.
          </p>
          <button
            type="button"
            disabled={disabled}
            onClick={() => void save(pending)}
          >
            Retry physical report
          </button>
        </aside>
      )}
      {progress && (
        <>
          <details className="progress-materials">
            <summary>Expected stock after confirmed work</summary>
            <p className="help">
              Calculated from the plan and your reports. Measure and reconcile
              actual remaining material before planning a repair.
            </p>
            <ul>
              {progress.expected_remaining_stock.map((stock) => (
                <li key={stock.id}>
                  {stock.id}:{" "}
                  {stock.kind === "tape" || stock.kind === "cord"
                    ? stock.remaining_length_mm.value === null
                      ? "Unknown length"
                      : `${stock.remaining_length_mm.value} mm calculated remaining`
                    : `${stock.usable_regions?.length ?? 0} usable regions remaining`}
                </li>
              ))}
            </ul>
          </details>
          <details className="progress-history">
            <summary>
              Physical report history ({progress.events.length})
            </summary>
            {progress.events.length === 0 ? (
              <p>No physical reports yet.</p>
            ) : (
              <ol>
                {progress.events.map((event) => (
                  <li key={event.id}>
                    <strong>{event.operation_id}</strong> ·{" "}
                    {event.kind.replaceAll("_", " ")} ·{" "}
                    {event.test_result ??
                      event.verification_state.replaceAll("_", " ")}
                    <p>{event.observation}</p>
                    <span className="help">
                      Recorded{" "}
                      <time dateTime={event.recorded_at}>
                        {event.recorded_at}
                      </time>{" "}
                      · user reported
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </details>
        </>
      )}
    </section>
  );
}
