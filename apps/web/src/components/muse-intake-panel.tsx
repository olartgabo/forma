"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, requestIntakeObservation } from "../lib/api";
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

function ineligibleReason(photo: Media): string {
  if (!SUPPORTED_TYPES.includes(photo.content_type))
    return "Stored as a format Muse cannot read here. Save a JPEG or PNG photo instead.";
  return "Larger than 5,000,000 bytes. Save a smaller JPEG or PNG photo instead.";
}

function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "The request could not finish. Check the API connection and try again.";
}

export default function MuseIntakePanel({
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
  const [consented, setConsented] = useState(false);
  const [result, setResult] = useState<IntakeResult | null>(null);
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

  // Session, project, revision, goal, photo set or selection changes
  // invalidate any earlier observation, consent and in-flight request.
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
      busy ||
      inventoryStale ||
      disabled
    )
      return;
    const requestEpoch = ++epoch.current;
    const requestController = new AbortController();
    controller.current = requestController;
    const mediaId = selected.id;
    const revisionId = project.revision_id;
    setBusy(true);
    setError("");
    setNotice("");
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
    !selected || !eligible || !consented || busy || inventoryStale || disabled;

  return (
    <section className="muse-panel" aria-labelledby="muse-intake-title">
      <div className="section-title">
        <span aria-hidden="true">3</span>
        <h2 id="muse-intake-title">Ask Muse about this photo</h2>
      </div>
      <p>
        Muse can suggest candidate material labels and questions from one saved
        photo. Suggestions are proposals only: they do not fill in inventory
        values, confirm measurements, create stock or show that a physical check
        passed.
      </p>
      {photos.length === 0 ? (
        <p className="empty-note">
          Save a photo in this project first, then choose it here.
        </p>
      ) : (
        <>
          <label htmlFor="muse-photo">Saved photo</label>
          <select
            id="muse-photo"
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
              Photo guidance: {ineligibleReason(selected)}
            </p>
          )}
          {!selected && photos.some((photo) => !isEligible(photo)) && (
            <p className="help">
              Muse can only read saved JPEG or PNG photos of 5,000,000 bytes or
              smaller. Photos in other formats or larger than that cannot be
              selected; save a JPEG or PNG photo instead.
            </p>
          )}
          <label className="checkbox-label" htmlFor="muse-consent">
            <input
              id="muse-consent"
              type="checkbox"
              checked={consented}
              disabled={busy}
              onChange={(event) => setConsented(event.target.checked)}
            />
            Send the selected photo and this project&apos;s saved goal to
            Meta&apos;s Muse service for this one request. Do not send a photo
            you are not allowed to share.
          </label>
          {inventoryStale && (
            <p className="help">
              Save or reload the inventory first: the saved inventory is stale
              or has unsaved changes, so Muse is unavailable until it matches
              the server.
            </p>
          )}
          <div className="muse-actions">
            <button
              type="button"
              className="primary"
              disabled={actionDisabled}
              onClick={() => void ask()}
            >
              Ask Muse about this photo
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
              <h3>Candidate labels</h3>
              {result.observation.labels.length === 0 ? (
                <p className="empty-note">Muse returned no candidate labels.</p>
              ) : (
                <ul>
                  {result.observation.labels.map((label, index) => (
                    <li key={`${index}-${label}`}>{label}</li>
                  ))}
                </ul>
              )}
              <h3>Questions to check</h3>
              {result.observation.questions.length === 0 ? (
                <p className="empty-note">Muse returned no questions.</p>
              ) : (
                <ul>
                  {result.observation.questions.map((question, index) => (
                    <li key={`${index}-${question}`}>{question}</li>
                  ))}
                </ul>
              )}
              <p>
                Measurement source: {result.observation.measurement_source}. A
                photo does not confirm measurements; measure and confirm values
                yourself before using them.
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
