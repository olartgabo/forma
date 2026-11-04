"use client";
import { useEffect, useRef, useState } from "react";
import { fetchPhoto } from "../lib/api";
import { loadPhotoPreview } from "../lib/photo-preview-loader";
import {
  LocalizationError,
  localizePhoto,
  validPhotoBox,
  validLocalizationRequest,
} from "../lib/photo-localization";
import type {
  Box,
  Media,
  Project,
  PhotoLocalizationRequest,
  PhotoLocalizationResult,
} from "../lib/generated/api-contracts";

import { receipts } from "./design-candidates/pending";
const localizationReceipts = receipts<PhotoLocalizationRequest>(
  "forma-photo-localization-v1:",
  validLocalizationRequest,
  "SAM request",
);

export default function PhotoLocalizationPanel(props: {
  token: string;
  project: Project;
  photos: Media[];
  disabled: boolean;
  inventoryStale: boolean;
}) {
  // Changing saved context destroys all local annotations and hides late responses.
  return (
    <PhotoSession
      key={`${props.token}:${props.project.id}:${props.project.revision_id}`}
      {...props}
    />
  );
}
function PhotoSession({
  token,
  project,
  photos,
  disabled,
  inventoryStale,
}: {
  token: string;
  project: Project;
  photos: Media[];
  disabled: boolean;
  inventoryStale: boolean;
}) {
  const [mediaId, setMediaId] = useState("");
  const [concept, setConcept] = useState("");
  const [consent, setConsent] = useState(false);
  const [url, setUrl] = useState("");
  const [previewError, setPreviewError] = useState(false);
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const [result, setResult] = useState<PhotoLocalizationResult | null>(null);
  const [selected, setSelected] = useState<Box | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [pending, setPending] = useState<PhotoLocalizationRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [terminal, setTerminal] = useState(false);
  const [receiptReady, setReceiptReady] = useState(false);
  const [receiptError, setReceiptError] = useState("");
  useEffect(() => {
    let live = true;
    localizationReceipts
      .pending(token, project.id)
      .then((body) => {
        if (!live) return;
        setPending(body);
        setReceiptReady(true);
        if (body) {
          setMediaId(body.media_id);
          setConcept(body.concept);
        }
      })
      .catch(() => {
        if (live)
          setReceiptError(
            "The retained SAM request could not be read. No new SAM request can be sent until browser recovery storage is repaired.",
          );
      });
    return () => {
      live = false;
    };
  }, [token, project.id]);
  const alive = useRef(true);
  const photo = photos.find((p) => p.id === mediaId);
  const blocked = disabled || inventoryStale;
  const eligible =
    photo &&
    ["image/png", "image/jpeg"].includes(photo.content_type) &&
    photo.byte_count <= 5_000_000;
  const conceptValid =
    /^[\p{L}\p{N}_ -]{1,80}$/u.test(concept) &&
    !!concept.trim() &&
    !concept.toLowerCase().includes(" and ");
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    setResult(null);
    setSelected(null);
    setReviewed(false);
    setConsent(false);
  }, [mediaId, concept, blocked]);
  useEffect(() => {
    setUrl("");
    setPreviewError(false);
    if (!photo) return;
    const controller = new AbortController();
    let dispose: (() => void) | undefined;
    void loadPhotoPreview(
      () => fetchPhoto(token, project.id, photo.id, controller.signal),
      controller.signal,
    )
      .then((preview) => {
        if (controller.signal.aborted) {
          preview.dispose();
          return;
        }
        dispose = preview.dispose;
        setUrl(preview.url);
      })
      .catch(() => {
        if (!controller.signal.aborted) setPreviewError(true);
      });
    return () => {
      controller.abort();
      dispose?.();
    };
  }, [token, project.id, photo, previewAttempt]);
  async function request() {
    if (
      (!pending && (!photo || blocked)) ||
      busy ||
      !receiptReady ||
      receiptError
    )
      return;
    const body = pending || {
      media_id: photo!.id,
      expected_revision_id: project.revision_id,
      concept,
      provider_transfer_consented: consent,
      idempotency_key: crypto.randomUUID(),
    };
    setPending(body);
    setBusy(true);
    setFailure("");
    setResult(null);
    setSelected(null);
    setReviewed(false);
    try {
      await localizationReceipts.retain(token, project.id, body);
      const requestPhoto = photos.find((p) => p.id === body.media_id);
      const next = await localizePhoto(token, project.id, requestPhoto, body);
      await localizationReceipts.clear(token, project.id, body);
      if (!alive.current) return;
      setResult(next);
      setPending(null);
      setConsent(false);
      setTerminal(false);
    } catch (error) {
      if (!alive.current) return;
      setFailure(
        error instanceof LocalizationError
          ? error.message
          : "Connection interrupted. Keep this request and check its receipt; do not start another SAM request.",
      );
      // Only explicit terminal/pre-dispatch errors permit a fresh request.
      setTerminal(
        error instanceof LocalizationError &&
          [
            "invalid_response",
            "stale_version",
            "not_found",
            "validation_error",
            "consent_required",
            "provider_not_configured",
          ].includes(error.code),
      );
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  const visible =
    photo && !blocked && selected && validPhotoBox(selected, photo)
      ? selected
      : null;
  return (
    <section
      className="workbench-section"
      aria-labelledby="photo-localization-title"
    >
      <h2 id="photo-localization-title">Find a material in your photo</h2>
      <p>
        SAM can suggest boxes around one material or object. Review a named
        photo region before identifying stock. Boxes are unverified annotations,
        not masks, 3D geometry, measurements or stock confirmation.
      </p>
      <label>
        Photo for localization
        <select
          value={mediaId}
          disabled={busy || !!pending}
          onChange={(e) => setMediaId(e.target.value)}
        >
          <option value="">Choose a saved photo</option>
          {photos.map((p) => (
            <option key={p.id} value={p.id}>
              {p.id} ({p.width_px} x {p.height_px} pixels)
            </option>
          ))}
        </select>
      </label>
      <label>
        Material or object name
        <input
          value={concept}
          maxLength={80}
          disabled={busy || !!pending}
          onChange={(e) => setConcept(e.target.value)}
          placeholder="cardboard sheet"
        />
      </label>
      <p>
        Name one concept per request. SAM accepts JPEG/PNG up to 5 MB. Manual
        boxes work without a provider.
      </p>
      <label>
        <input
          type="checkbox"
          checked={consent}
          disabled={busy || !!pending || blocked}
          onChange={(e) => setConsent(e.target.checked)}
        />
        Send this selected photo and name to Meta SAM for this request. Provider
        usage may be billed.
      </label>
      <button
        type="button"
        disabled={
          busy ||
          !receiptReady ||
          !!receiptError ||
          (!pending && (blocked || !eligible || !conceptValid || !consent))
        }
        onClick={() => void request()}
      >
        {busy
          ? "Finding regions..."
          : pending
            ? "Check same SAM request"
            : "Find this material in photo"}
      </button>
      {failure && <p role="alert">{failure}</p>}
      {receiptError && <p role="alert">{receiptError}</p>}
      {pending && terminal && (
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            if (!pending) return;
            try {
              await localizationReceipts.clear(token, project.id, pending);
            } catch {
              setReceiptError(
                "The SAM receipt could not be cleared; no new request was sent.",
              );
              return;
            }
            setPending(null);
            setTerminal(false);
            setConsent(false);
            setFailure("");
          }}
        >
          Prepare a new request
        </button>
      )}
      {blocked && (
        <p>
          Save or reload your current materials before reviewing photo regions.
        </p>
      )}
      {previewError && (
        <button type="button" onClick={() => setPreviewAttempt((n) => n + 1)}>
          Retry localization photo preview
        </button>
      )}
      {photo && url && (
        <svg
          role="img"
          aria-label="Source photo with selected material box"
          viewBox={`0 0 ${photo.width_px} ${photo.height_px}`}
          style={{
            width: "100%",
            maxWidth: 720,
            maxHeight: 480,
            display: "block",
          }}
        >
          <image href={url} width={photo.width_px} height={photo.height_px} />
          {visible && (
            <rect
              x={visible.x1}
              y={visible.y1}
              width={visible.x2 - visible.x1 + 1}
              height={visible.y2 - visible.y1 + 1}
              fill="none"
              stroke="#ff7300"
              strokeWidth="3"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>
      )}
      {result && result.revision_id !== project.revision_id && (
        <p>
          Recovered historical SAM response for an earlier inventory revision.
          Its boxes cannot be selected for the current inventory.
        </p>
      )}
      {result &&
        result.revision_id === project.revision_id &&
        !blocked &&
        photo && (
          <div>
            <p>
              {result.replayed ? "Recovered saved SAM response. " : ""}
              {result.boxes.length
                ? "Choose a suggested region:"
                : "SAM found no matching objects. Use a manual box."}{" "}
              {result.usage.model_calls} provider request(s); billing amount
              unknown.
            </p>
            {result.boxes.map((b, i) => (
              <button
                type="button"
                key={i}
                onClick={() => {
                  setSelected(b);
                  setReviewed(false);
                }}
              >
                Select {b.label} region {i + 1}
              </button>
            ))}
          </div>
        )}
      {photo && (
        <button
          type="button"
          disabled={blocked || !conceptValid}
          onClick={() => {
            setSelected({
              label: concept,
              source: "manual",
              width: photo.width_px,
              height: photo.height_px,
              x1: 0,
              y1: 0,
              x2: photo.width_px - 1,
              y2: photo.height_px - 1,
            });
            setReviewed(false);
          }}
        >
          Adjust a manual box
        </button>
      )}
      {visible && (
        <fieldset>
          <legend>Adjust {visible.label} in photo pixels</legend>
          <p>Origin is the upper-left pixel. Coordinates include both edges.</p>
          {(["x1", "y1", "x2", "y2"] as const).map((name) => (
            <label key={name}>
              {name}
              <input
                type="number"
                step="1"
                min="0"
                max={
                  (name.startsWith("x") ? visible.width : visible.height) - 1
                }
                value={visible[name]}
                onChange={(e) => {
                  const next = {
                    ...visible,
                    [name]: Number(e.target.value),
                    source: "manual" as const,
                  };
                  if (e.target.value !== "" && validPhotoBox(next, photo!))
                    setSelected(next);
                  setReviewed(false);
                }}
              />
            </label>
          ))}
          <label>
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
            />
            I reviewed this photo region and its label
          </label>
          {reviewed && (
            <p role="status">
              Local photo reference: {visible.label}; photo {mediaId}; pixels (
              {visible.x1}, {visible.y1}) to ({visible.x2}, {visible.y2}).{" "}
              {visible.source === "sam"
                ? "SAM suggestion reviewed"
                : "Manually marked"}
              . Unverified material identity. Nothing was saved to inventory;
              dimensions, thickness, density and condition still need separate
              confirmation.
            </p>
          )}
        </fieldset>
      )}
    </section>
  );
}
