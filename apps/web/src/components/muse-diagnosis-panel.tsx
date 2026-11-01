"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, loadPlan, requestDiagnosis } from "../lib/api";
import type {
  DiagnosisResult,
  Media,
  PlanVersion,
  Project,
} from "../lib/generated/api-contracts";

const MAX_PROVIDER_IMAGE_BYTES = 5_000_000;
const SUPPORTED_TYPES = ["image/jpeg", "image/png"];

function isEligible(photo: Media): boolean {
  return (
    SUPPORTED_TYPES.includes(photo.content_type) &&
    photo.byte_count > 0 &&
    photo.byte_count <= MAX_PROVIDER_IMAGE_BYTES
  );
}

function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "The request could not finish. Check the API connection and try again.";
}

export default function MuseDiagnosisPanel({
  token,
  project,
  photos,
  inventoryStale,
  disabled,
}: {
  token: string;
  project: Project;
  photos: Media[];
  inventoryStale: boolean;
  disabled: boolean;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [problem, setProblem] = useState("");
  const [consented, setConsented] = useState(false);
  const [operationId, setOperationId] = useState("");
  const [activePlan, setActivePlan] = useState<PlanVersion | null>(null);
  const [planError, setPlanError] = useState("");
  const [result, setResult] = useState<DiagnosisResult | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const epoch = useRef(0);

  const selected = photos.find((photo) => photo.id === selectedId) ?? null;
  const eligible = selected !== null && isEligible(selected);
  const photosKey = photos
    .map((photo) => `${photo.id}:${photo.content_type}:${photo.byte_count}`)
    .join(",");
  const hasActive = Boolean(project.active_version_id);
  const operations = activePlan?.plan.operations ?? [];

  useEffect(() => {
    if (!project.active_version_id) {
      setActivePlan(null);
      setOperationId("");
      setPlanError("");
      return;
    }
    const loadController = new AbortController();
    setPlanError("");
    void loadPlan(
      token,
      project.id,
      project.active_version_id,
      loadController.signal,
    )
      .then((next) => {
        if (loadController.signal.aborted) return;
        setActivePlan(next);
        setOperationId((current) =>
          next.plan.operations.some((operation) => operation.id === current)
            ? current
            : "",
        );
      })
      .catch((failure: unknown) => {
        if (!loadController.signal.aborted) {
          setActivePlan(null);
          setPlanError(errorMessage(failure));
        }
      });
    return () => loadController.abort();
  }, [token, project.id, project.active_version_id]);

  useEffect(() => {
    epoch.current += 1;
    controller.current?.abort();
    controller.current = null;
    setConsented(false);
    setResult(null);
    setError("");
    setNotice("");
    setBusy(false);
  }, [
    token,
    project.id,
    project.revision_id,
    project.goal,
    project.active_version_id,
    photosKey,
    selectedId,
    operationId,
    problem,
  ]);

  useEffect(() => {
    if (selectedId && !photos.some((photo) => photo.id === selectedId))
      setSelectedId("");
  }, [photos, selectedId]);

  useEffect(
    () => () => {
      epoch.current += 1;
      controller.current?.abort();
    },
    [],
  );

  function cancel() {
    epoch.current += 1;
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
    setError("");
    setNotice(
      "Cancelled. FORMA stopped waiting for Muse; Muse may already be processing the photo, so no result was shown.",
    );
  }

  async function ask() {
    if (
      !selected ||
      !eligible ||
      !consented ||
      !problem.trim() ||
      busy ||
      inventoryStale ||
      disabled ||
      (hasActive && (!activePlan || !operationId))
    )
      return;
    const consentedPayload = consented;
    const requestEpoch = ++epoch.current;
    const requestController = new AbortController();
    controller.current = requestController;
    // Consent covers this one request only: consume it on dispatch so any
    // later success, failure or cancellation requires a fresh opt-in. The
    // in-flight request keeps the payload captured above.
    setConsented(false);
    setBusy(true);
    setError("");
    setNotice("");
    setResult(null);
    try {
      const next = await requestDiagnosis(
        token,
        project.id,
        {
          media_id: selected.id,
          expected_revision_id: project.revision_id,
          reported_problem: problem.trim(),
          provider_transfer_consented: consentedPayload,
          ...(hasActive && project.active_version_id
            ? {
                expected_active_version_id: project.active_version_id,
                current_operation_id: operationId,
              }
            : {}),
        },
        requestController.signal,
      );
      if (requestController.signal.aborted || requestEpoch !== epoch.current)
        return;
      setResult(next);
    } catch (failure) {
      if (requestController.signal.aborted || requestEpoch !== epoch.current)
        return;
      if (failure instanceof ApiError && failure.code === "cancelled") {
        setNotice(
          "Cancelled. FORMA stopped waiting for Muse; Muse may already be processing the photo, so no result was shown.",
        );
        return;
      }
      setError(errorMessage(failure));
    } finally {
      if (!requestController.signal.aborted && requestEpoch === epoch.current) {
        controller.current = null;
        setBusy(false);
      }
    }
  }

  const actionDisabled =
    !selected ||
    !eligible ||
    !consented ||
    !problem.trim() ||
    busy ||
    inventoryStale ||
    disabled ||
    (hasActive && (!activePlan || !operationId));

  return (
    <section className="muse-panel" aria-labelledby="muse-diagnosis-title">
      <div className="section-title">
        <span aria-hidden="true">4</span>
        <h2 id="muse-diagnosis-title">Something went wrong</h2>
      </div>
      <p>
        Send one saved failure photo and what you noticed to Muse for a
        read-only diagnosis. Muse separates what is visible from possible causes
        and questions. This does not change your plan or materials, record
        damage, or start a repair.
      </p>
      <p className="help">
        Repair execution is not available yet. It stays unavailable until real
        build history and the repair replanner are connected; approved repairs
        will need separate review.
      </p>
      {photos.length === 0 ? (
        <p className="empty-note">
          Save a photo of the problem in this project first, then choose it
          here.
        </p>
      ) : (
        <>
          <label htmlFor="diagnosis-photo">Saved failure photo</label>
          <select
            id="diagnosis-photo"
            value={selectedId}
            disabled={busy}
            onChange={(event) => setSelectedId(event.target.value)}
          >
            <option value="">Choose a photo…</option>
            {photos.map((photo, index) => (
              <option
                key={photo.id}
                value={photo.id}
                disabled={!isEligible(photo)}
              >
                Photo {index + 1} — {photo.content_type},{" "}
                {photo.byte_count.toLocaleString()} bytes
                {isEligible(photo) ? "" : " (cannot be sent to Muse)"}
              </option>
            ))}
          </select>
          {selected && !eligible && (
            <p className="help" role="note">
              Muse can only read saved JPEG or PNG photos of 5,000,000 bytes or
              smaller. Save a smaller JPEG or PNG photo instead.
            </p>
          )}
          <label htmlFor="diagnosis-problem">What went wrong?</label>
          <textarea
            id="diagnosis-problem"
            rows={4}
            maxLength={1000}
            value={problem}
            disabled={busy}
            onChange={(event) => setProblem(event.target.value)}
            placeholder="For example: the slot tore when I inserted the tab"
          />
          <p className="help">
            This is your report, not something Muse has observed. Muse will keep
            it separate from what is visible in the photo.
          </p>
          {hasActive ? (
            <>
              <label htmlFor="diagnosis-operation">Current step</label>
              <select
                id="diagnosis-operation"
                value={operationId}
                disabled={busy || !activePlan}
                onChange={(event) => setOperationId(event.target.value)}
              >
                <option value="">Choose the current step…</option>
                {operations.map((operation, index) => (
                  <option key={operation.id} value={operation.id}>
                    Step {index + 1} — {operation.type} ({operation.id})
                  </option>
                ))}
              </select>
              {planError && (
                <p className="error" role="alert">
                  {planError}
                </p>
              )}
              {!activePlan && !planError && (
                <p className="help">Loading the active manual steps…</p>
              )}
            </>
          ) : (
            <p className="help">
              No active manual yet, so this is a photo-only diagnosis. Build
              progress stays unknown and Muse cannot name affected plan parts.
            </p>
          )}
          <label className="checkbox-label" htmlFor="diagnosis-consent">
            <input
              id="diagnosis-consent"
              type="checkbox"
              checked={consented}
              disabled={busy}
              onChange={(event) => setConsented(event.target.checked)}
            />
            Send the selected photo, my reported problem and this project&apos;s
            saved materials
            {hasActive ? " and active step" : ""} to Meta&apos;s Muse service
            for this one request. Do not send a photo you are not allowed to
            share.
          </label>
          {inventoryStale && (
            <p className="help">
              Save or reload the inventory first: Muse diagnosis is unavailable
              while saved materials are stale or have unsaved changes.
            </p>
          )}
          <div className="muse-actions">
            <button
              type="button"
              className="primary"
              disabled={actionDisabled}
              onClick={() => void ask()}
            >
              Ask Muse what went wrong
            </button>
            {busy && (
              <button type="button" className="secondary" onClick={cancel}>
                Cancel
              </button>
            )}
          </div>
          {busy && (
            <p className="help" aria-live="polite">
              Asking Muse… Cancelling stops FORMA waiting; Muse may already be
              processing the photo. There are no automatic retries.
            </p>
          )}
          {notice && (
            <p className="notice" aria-live="polite">
              {notice}
            </p>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {result && (
            <div className="muse-result">
              <h3>Visible observations</h3>
              {result.diagnosis.visible_observations.length === 0 ? (
                <p className="empty-note">
                  Muse reported no visible observations.
                </p>
              ) : (
                <ul>
                  {result.diagnosis.visible_observations.map((item, index) => (
                    <li key={`${index}-${item}`}>{item}</li>
                  ))}
                </ul>
              )}
              <h3>Possible causes (hypotheses)</h3>
              {result.diagnosis.hypotheses.length === 0 ? (
                <p className="empty-note">Muse offered no hypotheses.</p>
              ) : (
                <ul>
                  {result.diagnosis.hypotheses.map((item, index) => (
                    <li key={`${index}-${item}`}>{item}</li>
                  ))}
                </ul>
              )}
              <h3>Questions or measurements to check</h3>
              {result.diagnosis.questions_or_measurements.length === 0 ? (
                <p className="empty-note">
                  Muse asked for no further measurements.
                </p>
              ) : (
                <ul>
                  {result.diagnosis.questions_or_measurements.map(
                    (item, index) => (
                      <li key={`${index}-${item}`}>{item}</li>
                    ),
                  )}
                </ul>
              )}
              <p>
                Failure type:{" "}
                {result.diagnosis.failure_type.replaceAll("_", " ")}.
                {result.diagnosis.affected_ids.length > 0
                  ? ` Affected plan items: ${result.diagnosis.affected_ids.join(", ")}.`
                  : " No plan items were identified."}{" "}
                A photo does not confirm measurements or that a physical check
                passed; measure and check yourself.
              </p>
              <p className="help">
                Request diagnostics — status: {result.diagnostics.status};
                model: {result.diagnostics.model}; duration:{" "}
                {result.diagnostics.elapsed_ms} ms.
              </p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
