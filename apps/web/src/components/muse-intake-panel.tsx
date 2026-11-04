"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, requestIntakeObservation } from "../lib/api";
import { museDiagnosticsFromResult } from "../lib/provider-usage";
import {
  intakeFailureReason,
  intakeFailureSummary,
  type IntakeFailureDiagnostics,
} from "../lib/intake-failure";
import {
  formatEnglishGroupedNumber,
  museFailureText,
  museNoticeText,
  museStoredFailure,
  type MuseNoticeId,
  type MuseStoredFailure,
} from "../lib/muse-language";
import type { MuseAvailability } from "../lib/muse-provider";
import MuseRequestStatus from "./muse-request-status";
import { useMuseLanguage } from "./muse-language-provider";
import type {
  IntakeResult,
  Media,
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

function ineligibleReason(
  photo: Media,
  copy: ReturnType<typeof useMuseLanguage>["copy"],
): string {
  if (!SUPPORTED_TYPES.includes(photo.content_type))
    return copy.intake.ineligibleFormat;
  return copy.intake.ineligibleSize;
}

export default function MuseIntakePanel({
  token,
  project,
  photos,
  inventoryStale,
  disabled,
  museAvailability,
}: {
  token: string;
  project: Project;
  photos: Media[];
  inventoryStale: boolean;
  disabled: boolean;
  museAvailability?: MuseAvailability;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [consented, setConsented] = useState(false);
  const [result, setResult] = useState<IntakeResult | null>(null);
  const [failure, setFailure] = useState<MuseStoredFailure | null>(null);
  const [failureDiagnostics, setFailureDiagnostics] =
    useState<IntakeFailureDiagnostics | null>(null);
  const [cancelledNotice, setCancelledNotice] = useState<MuseNoticeId | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const { locale, copy } = useMuseLanguage();
  const controller = useRef<AbortController | null>(null);
  const epoch = useRef(0);

  const selected = photos.find((photo) => photo.id === selectedId) ?? null;
  const eligible = selected !== null && isEligible(selected);
  const photosKey = photos
    .map((photo) => `${photo.id}:${photo.content_type}:${photo.byte_count}`)
    .join(",");

  // Session, project, revision, goal, photo set or selection changes
  // invalidate any earlier observation, consent and in-flight request.
  useEffect(() => {
    epoch.current += 1;
    controller.current?.abort();
    controller.current = null;
    setConsented(false);
    setResult(null);
    setFailure(null);
    setFailureDiagnostics(null);
    setCancelledNotice(null);
    setBusy(false);
  }, [
    token,
    project.id,
    project.revision_id,
    project.goal,
    photosKey,
    selectedId,
  ]);

  // Clear a selection whose photo was deleted from the gallery.
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
    setFailure(null);
    setFailureDiagnostics(null);
    setCancelledNotice("intake-cancelled");
  }

  async function ask() {
    if (
      !selected ||
      !eligible ||
      !consented ||
      busy ||
      inventoryStale ||
      disabled ||
      museAvailability?.enabled === false
    )
      return;
    const requestEpoch = ++epoch.current;
    const requestController = new AbortController();
    controller.current = requestController;
    const mediaId = selected.id;
    const revisionId = project.revision_id;
    // Consent covers this one request only: consume it on dispatch so any
    // later success, failure or cancellation requires a fresh opt-in. The
    // in-flight request keeps the payload captured above.
    setConsented(false);
    setBusy(true);
    setFailure(null);
    setFailureDiagnostics(null);
    setCancelledNotice(null);
    setResult(null);
    try {
      const next = await requestIntakeObservation(
        token,
        project.id,
        mediaId,
        revisionId,
        requestController.signal,
      );
      if (requestController.signal.aborted || requestEpoch !== epoch.current)
        return;
      setResult(next);
    } catch (failure) {
      if (requestController.signal.aborted || requestEpoch !== epoch.current)
        return;
      if (failure instanceof ApiError && failure.code === "cancelled") {
        setCancelledNotice("intake-cancelled");
        return;
      }
      setFailure(
        museStoredFailure({
          code: failure instanceof ApiError ? failure.code : undefined,
          apiMessage: failure instanceof ApiError ? failure.message : undefined,
          fallbackSection: "intake",
        }),
      );
      setFailureDiagnostics(
        failure instanceof ApiError ? failure.intakeDiagnostics : null,
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
    busy ||
    inventoryStale ||
    disabled ||
    museAvailability?.enabled === false;

  return (
    <section
      className="muse-panel"
      aria-labelledby="muse-intake-title"
      lang={locale}
    >
      <div className="section-title">
        <span aria-hidden="true">3</span>
        <h2 id="muse-intake-title">{copy.intake.title}</h2>
      </div>
      <p>{copy.intake.intro}</p>
      {photos.length === 0 ? (
        <p className="empty-note">{copy.intake.saveFirst}</p>
      ) : (
        <>
          <label htmlFor="muse-photo">{copy.intake.savedPhoto}</label>
          <select
            id="muse-photo"
            value={selectedId}
            disabled={busy}
            onChange={(event) => setSelectedId(event.target.value)}
          >
            <option value="">{copy.intake.choosePhoto}</option>
            {photos.map((photo, index) => (
              <option
                key={photo.id}
                value={photo.id}
                disabled={!isEligible(photo)}
              >
                {copy.intake.photo} {index + 1} — {photo.content_type},{" "}
                {formatEnglishGroupedNumber(photo.byte_count)}{" "}
                {copy.intake.bytes}
                {isEligible(photo) ? "" : ` ${copy.intake.cannotSend}`}
              </option>
            ))}
          </select>
          {selected && !eligible && (
            <p className="help" role="note">
              {copy.intake.photoGuidance} {ineligibleReason(selected, copy)}
            </p>
          )}
          {!selected && photos.some((photo) => !isEligible(photo)) && (
            <p className="help">{copy.intake.formatHelp}</p>
          )}
          {museAvailability?.enabled === false && (
            <p className="help" role="note">
              {locale === "es"
                ? copy.provider.notConfiguredReason
                : museAvailability.reason}
            </p>
          )}
          <label className="checkbox-label" htmlFor="muse-consent">
            <input
              id="muse-consent"
              type="checkbox"
              checked={consented}
              disabled={busy || museAvailability?.enabled === false}
              onChange={(event) => setConsented(event.target.checked)}
            />
            {copy.intake.consent}
          </label>
          {inventoryStale && <p className="help">{copy.intake.stale}</p>}
          <div className="muse-actions">
            <button
              type="button"
              className="primary"
              disabled={actionDisabled}
              onClick={() => void ask()}
            >
              {copy.intake.ask}
            </button>
          </div>
          <MuseRequestStatus
            busy={busy}
            pendingMessage={copy.intake.pending}
            onCancel={cancel}
            cancelledMessage={museNoticeText(cancelledNotice, locale)}
            errorCode={failure?.code}
            errorMessage={
              failure
                ? failureDiagnostics
                  ? intakeFailureReason(failureDiagnostics, locale)
                  : museFailureText(failure, locale)
                : undefined
            }
            diagnostics={
              result
                ? museDiagnosticsFromResult(result.diagnostics)
                : intakeFailureSummary(failureDiagnostics)
            }
            locale={locale}
          />
          {result && (
            <div className="muse-result">
              <h3>{copy.intake.candidateLabels}</h3>
              {result.observation.labels.length === 0 ? (
                <p className="empty-note">{copy.intake.noLabels}</p>
              ) : (
                <ul>
                  {result.observation.labels.map((label, index) => (
                    <li key={`${index}-${label}`}>{label}</li>
                  ))}
                </ul>
              )}
              <h3>{copy.intake.questions}</h3>
              {result.observation.questions.length === 0 ? (
                <p className="empty-note">{copy.intake.noQuestions}</p>
              ) : (
                <ul>
                  {result.observation.questions.map((question, index) => (
                    <li key={`${index}-${question}`}>{question}</li>
                  ))}
                </ul>
              )}
              <p>
                {copy.intake.measurementSource}{" "}
                {result.observation.measurement_source}.{" "}
                {copy.intake.measurementNote}
              </p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
