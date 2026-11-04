"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ApiError, loadPlan, requestDiagnosis } from "../lib/api";
import { createDiagnosisPlanLoader } from "../lib/diagnosis-plan-loader";
import {
  diagnosisHasNoPartTarget,
  handoffFromDiagnosis,
  type RepairHandoff,
} from "../lib/repair-handoff";
import { museDiagnosticsFromResult } from "../lib/provider-usage";
import {
  formatEnglishGroupedNumber,
  museFailureText,
  museNoticeText,
  museStoredFailure,
  resolveStoredFailureText,
  type MuseNoticeId,
  type MuseStoredFailure,
} from "../lib/muse-language";
import type { MuseAvailability } from "../lib/muse-provider";
import type { DiagnosisFocus } from "../lib/build-diagnosis";
import MuseRequestStatus from "./muse-request-status";
import { useMuseLanguage } from "./muse-language-provider";
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

function errorMessage(error: unknown, fallback?: string) {
  return error instanceof ApiError
    ? error.message
    : (fallback ??
        "The request could not finish. Check the API connection and try again.");
}

export default function MuseDiagnosisPanel({
  token,
  project,
  photos,
  inventoryStale,
  disabled,
  onRepairHandoff,
  prefill,
  museAvailability,
  onDiagnosisSaved,
  onDiagnosisOutcome,
}: {
  token: string;
  project: Project;
  photos: Media[];
  inventoryStale: boolean;
  disabled: boolean;
  onRepairHandoff?: (handoff: RepairHandoff, targetId: string) => void;
  prefill?: DiagnosisFocus | null;
  museAvailability?: MuseAvailability;
  onDiagnosisSaved?: () => void;
  onDiagnosisOutcome?: (outcome: "pending" | "saved" | "uncertain") => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [problem, setProblem] = useState("");
  const [consented, setConsented] = useState(false);
  const [operationId, setOperationId] = useState("");
  const [planLoader] = useState(() =>
    createDiagnosisPlanLoader<PlanVersion>({
      load: async (key, signal) => {
        const next = await loadPlan(
          key.token,
          key.projectId,
          key.activeVersionId,
          signal,
        );
        if (
          next.project_id !== key.projectId ||
          next.version_id !== key.activeVersionId
        )
          throw new ApiError(
            200,
            "invalid_response",
            "FORMA returned a manual that does not match this project or active version. Reload the project and try again.",
          );
        return next;
      },
      errorMessage,
    }),
  );
  const planState = useSyncExternalStore(
    planLoader.subscribe,
    planLoader.getState,
    planLoader.getState,
  );
  const [result, setResult] = useState<DiagnosisResult | null>(null);
  const [failure, setFailure] = useState<MuseStoredFailure | null>(null);
  const [cancelledNotice, setCancelledNotice] = useState<MuseNoticeId | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const { locale, copy } = useMuseLanguage();
  const controller = useRef<AbortController | null>(null);
  const epoch = useRef(0);
  const outcomeCallback = useRef(onDiagnosisOutcome);

  const selected = photos.find((photo) => photo.id === selectedId) ?? null;
  const eligible = selected !== null && isEligible(selected);
  const photosKey = photos
    .map((photo) => `${photo.id}:${photo.content_type}:${photo.byte_count}`)
    .join(",");
  const hasActive = Boolean(project.active_version_id);
  const planMatchesCurrent =
    hasActive &&
    planState.key !== null &&
    planState.key.token === token &&
    planState.key.projectId === project.id &&
    planState.key.activeVersionId === project.active_version_id;
  const activePlan = planMatchesCurrent ? planState.plan : null;
  const planError = planMatchesCurrent ? planState.error : "";
  const planLoading = hasActive && (!planMatchesCurrent || planState.loading);
  const operations = activePlan?.plan.operations ?? [];
  const operationValid = operations.some(
    (operation) => operation.id === operationId,
  );

  useEffect(() => {
    setOperationId("");
    if (!project.active_version_id) {
      planLoader.setKey(null);
      return;
    }
    planLoader.setKey({
      token,
      projectId: project.id,
      activeVersionId: project.active_version_id,
    });
  }, [planLoader, token, project.id, project.active_version_id]);

  useEffect(() => () => planLoader.dispose(), [planLoader]);

  useEffect(() => {
    epoch.current += 1;
    if (controller.current) outcomeCallback.current?.("uncertain");
    controller.current?.abort();
    controller.current = null;
    setConsented(false);
    setResult(null);
    setFailure(null);
    setCancelledNotice(null);
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

  const appliedPrefillNonce = useRef<string | null>(null);
  useEffect(() => {
    if (!prefill || appliedPrefillNonce.current === prefill.nonce) return;
    if (prefill.projectId !== project.id) return;
    if (prefill.versionId !== project.active_version_id) return;
    if (hasActive && !activePlan) return;
    appliedPrefillNonce.current = prefill.nonce;
    if (
      prefill.mediaId &&
      photos.some((photo) => photo.id === prefill.mediaId && isEligible(photo))
    )
      setSelectedId(prefill.mediaId);
    else setSelectedId("");
    if (operations.some((operation) => operation.id === prefill.operationId))
      setOperationId(prefill.operationId);
  }, [
    prefill,
    project.id,
    project.active_version_id,
    hasActive,
    activePlan,
    operations,
    photos,
  ]);

  useEffect(
    () => () => {
      epoch.current += 1;
      if (controller.current) outcomeCallback.current?.("uncertain");
      controller.current?.abort();
    },
    [],
  );

  function cancel() {
    epoch.current += 1;
    if (controller.current) outcomeCallback.current?.("uncertain");
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
    setFailure(null);
    setCancelledNotice("diagnosis-cancelled");
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
      museAvailability?.enabled === false ||
      (hasActive && (!activePlan || !operationValid))
    )
      return;
    const consentedPayload = consented;
    const requestEpoch = ++epoch.current;
    const requestController = new AbortController();
    controller.current = requestController;
    outcomeCallback.current = hasActive ? onDiagnosisOutcome : undefined;
    if (hasActive) outcomeCallback.current?.("pending");
    // Consent covers this one request only: consume it on dispatch so any
    // later success, failure or cancellation requires a fresh opt-in. The
    // in-flight request keeps the payload captured above.
    setConsented(false);
    setBusy(true);
    setFailure(null);
    setCancelledNotice(null);
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
      controller.current = null;
      if (hasActive) outcomeCallback.current?.("saved");
      onDiagnosisSaved?.();
    } catch (failure) {
      if (requestController.signal.aborted || requestEpoch !== epoch.current)
        return;
      if (hasActive) outcomeCallback.current?.("uncertain");
      if (failure instanceof ApiError && failure.code === "cancelled") {
        setCancelledNotice("diagnosis-cancelled");
        return;
      }
      setFailure(
        museStoredFailure({
          code: failure instanceof ApiError ? failure.code : undefined,
          apiMessage: failure instanceof ApiError ? failure.message : undefined,
          fallbackSection: "diagnosis",
        }),
      );
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
    museAvailability?.enabled === false ||
    (hasActive && (!activePlan || !operationValid));

  const repairHandoff =
    result && activePlan ? handoffFromDiagnosis(result, activePlan) : null;

  return (
    <section
      className="muse-panel"
      id="muse-diagnosis-panel"
      tabIndex={-1}
      aria-labelledby="muse-diagnosis-title"
      lang={locale}
    >
      <div className="section-title">
        <span aria-hidden="true">4</span>
        <h2 id="muse-diagnosis-title">{copy.diagnosis.title}</h2>
      </div>
      <p>{copy.diagnosis.intro}</p>
      <p className="help">{copy.diagnosis.unverified}</p>
      {photos.length === 0 ? (
        <p className="empty-note">{copy.diagnosis.saveFirst}</p>
      ) : (
        <>
          <label htmlFor="diagnosis-photo">{copy.diagnosis.savedPhoto}</label>
          <select
            id="diagnosis-photo"
            value={selectedId}
            disabled={busy}
            onChange={(event) => setSelectedId(event.target.value)}
          >
            <option value="">{copy.diagnosis.choosePhoto}</option>
            {photos.map((photo, index) => (
              <option
                key={photo.id}
                value={photo.id}
                disabled={!isEligible(photo)}
              >
                {copy.diagnosis.photo} {index + 1} — {photo.content_type},{" "}
                {formatEnglishGroupedNumber(photo.byte_count)}{" "}
                {copy.diagnosis.bytes}
                {isEligible(photo) ? "" : ` ${copy.diagnosis.cannotSend}`}
              </option>
            ))}
          </select>
          {selected && !eligible && (
            <p className="help" role="note">
              {copy.diagnosis.formatHelp}
            </p>
          )}
          {!selected && photos.some((photo) => !isEligible(photo)) && (
            <p className="help">{copy.diagnosis.formatHelp}</p>
          )}
          <label htmlFor="diagnosis-problem">
            {copy.diagnosis.problemLabel}
          </label>
          <textarea
            id="diagnosis-problem"
            rows={4}
            maxLength={1000}
            value={problem}
            disabled={busy}
            onChange={(event) => setProblem(event.target.value)}
            placeholder={copy.diagnosis.problemPlaceholder}
          />
          <p className="help">{copy.diagnosis.problemHelp}</p>
          {hasActive ? (
            <>
              <label htmlFor="diagnosis-operation">
                {copy.diagnosis.currentStep}
              </label>
              <select
                id="diagnosis-operation"
                value={operationId}
                disabled={busy || !activePlan}
                onChange={(event) => setOperationId(event.target.value)}
              >
                <option value="">{copy.diagnosis.chooseStep}</option>
                {operations.map((operation, index) => (
                  <option key={operation.id} value={operation.id}>
                    {copy.diagnosis.step} {index + 1} — {operation.type} (
                    {operation.id})
                  </option>
                ))}
              </select>
              {planError && (
                <>
                  <p className="error" role="alert">
                    {resolveStoredFailureText(planError, "diagnosis", locale)}
                  </p>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy || planLoading}
                    onClick={() => planLoader.retry()}
                  >
                    {copy.actions.retryLoadingManual}
                  </button>
                </>
              )}
              {!activePlan && !planError && (
                <p className="help">{copy.diagnosis.loadingSteps}</p>
              )}
            </>
          ) : (
            <p className="help">{copy.diagnosis.photoOnly}</p>
          )}
          {museAvailability?.enabled === false && (
            <p className="help" role="note">
              {locale === "es"
                ? copy.provider.notConfiguredReason
                : museAvailability.reason}
            </p>
          )}
          <label className="checkbox-label" htmlFor="diagnosis-consent">
            <input
              id="diagnosis-consent"
              type="checkbox"
              checked={consented}
              disabled={busy || museAvailability?.enabled === false}
              onChange={(event) => setConsented(event.target.checked)}
            />
            {hasActive ? copy.diagnosis.consentActive : copy.diagnosis.consent}
          </label>
          {inventoryStale && <p className="help">{copy.diagnosis.stale}</p>}
          <div className="muse-actions">
            <button
              type="button"
              className="primary"
              disabled={actionDisabled}
              onClick={() => void ask()}
            >
              {copy.diagnosis.ask}
            </button>
          </div>
          <MuseRequestStatus
            busy={busy}
            succeeded={result !== null}
            onCancel={cancel}
            cancelledMessage={museNoticeText(cancelledNotice, locale)}
            errorCode={failure?.code}
            errorMessage={
              failure ? museFailureText(failure, locale) : undefined
            }
            diagnostics={
              result ? museDiagnosticsFromResult(result.diagnostics) : null
            }
            locale={locale}
          />
          {result && (
            <div className="muse-result">
              <h3>{copy.diagnosis.visible}</h3>
              {result.diagnosis.visible_observations.length === 0 ? (
                <p className="empty-note">{copy.diagnosis.noVisible}</p>
              ) : (
                <ul>
                  {result.diagnosis.visible_observations.map((item, index) => (
                    <li key={`${index}-${item}`}>{item}</li>
                  ))}
                </ul>
              )}
              <h3>{copy.diagnosis.causes}</h3>
              {result.diagnosis.hypotheses.length === 0 ? (
                <p className="empty-note">{copy.diagnosis.noCauses}</p>
              ) : (
                <ul>
                  {result.diagnosis.hypotheses.map((item, index) => (
                    <li key={`${index}-${item}`}>{item}</li>
                  ))}
                </ul>
              )}
              <h3>{copy.diagnosis.questions}</h3>
              {result.diagnosis.questions_or_measurements.length === 0 ? (
                <p className="empty-note">{copy.diagnosis.noQuestions}</p>
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
                {copy.diagnosis.failureType}{" "}
                {result.diagnosis.failure_type.replaceAll("_", " ")}.
                {result.diagnosis.affected_ids.length > 0
                  ? ` ${copy.diagnosis.affected} ${result.diagnosis.affected_ids.join(", ")}.`
                  : ` ${copy.diagnosis.noAffected}`}{" "}
                {copy.diagnosis.measurementNote}
              </p>
              {activePlan && diagnosisHasNoPartTarget(result, activePlan) && (
                <p className="help" role="note">
                  {copy.diagnosis.noPartTarget}
                </p>
              )}
              {repairHandoff && onRepairHandoff && (
                <div className="muse-actions">
                  <p className="help">{copy.diagnosis.repairHelp}</p>
                  {repairHandoff.targetIds.map((targetId) => (
                    <button
                      key={targetId}
                      type="button"
                      className="secondary"
                      disabled={disabled}
                      onClick={() =>
                        onRepairHandoff(
                          { ...repairHandoff, nonce: crypto.randomUUID() },
                          targetId,
                        )
                      }
                    >
                      {copy.diagnosis.reviewRepair} {targetId}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
