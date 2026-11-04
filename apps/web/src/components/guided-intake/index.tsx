"use client";
// Guided photo-first intake (#177): photograph, review named cards, save,
// then answer the one next measurement question that can change the result.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { requestIntakeObservation } from "../../lib/api";
import {
  localizationReceipts,
  localizePhoto,
  LocalizationError,
} from "../../lib/photo-localization";
import {
  EstimateRequestError,
  photoEstimates,
  REFERENCE_CARD_URL,
} from "../../lib/photo-estimates";
import type { MuseAvailability } from "../../lib/muse-provider";
import type {
  Media,
  PhotoEstimateRecord,
  PhotoEstimateRequest,
  PhotoLocalizationRequest,
  Project,
} from "../../lib/generated/api-contracts";
import type { OutlineInput, Stock } from "../../lib/generated/contracts";
import {
  answerBody,
  measurementApi,
  MeasurementRequestError,
  type Decision,
} from "../active-measurement/client";
import PhotoCanvas, { type Mode } from "./photo-canvas";
import {
  boxOutline,
  clearValue,
  defaultName,
  editablePoints,
  estimateSummary,
  latestRecord,
  nameFromId,
  newStock,
  polygonOutline,
  recordRuler,
  referenceInput,
  sizeFieldsFor,
  sizeState,
  stalePhotoValues,
  stockIdFor,
  suggestFromLabel,
  applyEstimate,
  type Box,
  type Point,
  type ReferenceDraft,
  type SizeField,
} from "./model";

type Card = {
  stock: Stock;
  name: string;
  mediaId: string | null;
  materialGuessed: boolean;
  box: Box | null;
  boxSource: "sam_box" | "manual_box";
  polygon: Point[] | null;
};

const FIELD_LABEL: Record<SizeField, string> = {
  width_mm: "Longer side",
  height_mm: "Shorter side",
};

function cardsFor(
  stocks: readonly Stock[],
  records: readonly PhotoEstimateRecord[],
): Card[] {
  return stocks.map((stock) => {
    const record = latestRecord(records, stock.id);
    const outline = record?.estimate.input.outline;
    return {
      stock,
      name: nameFromId(stock.id),
      mediaId: record?.estimate.input.media_id ?? stock.image_ids?.[0] ?? null,
      materialGuessed: false,
      box:
        outline && outline.source !== "user_polygon"
          ? {
              x1: outline.x1!,
              y1: outline.y1!,
              x2: outline.x2!,
              y2: outline.y2!,
            }
          : null,
      boxSource: outline?.source === "sam_box" ? "sam_box" : "manual_box",
      polygon:
        outline?.source === "user_polygon"
          ? (outline.polygon_px ?? []).map((p) => ({ ...p }))
          : null,
    };
  });
}

export default function GuidedIntake({
  token,
  project,
  photos,
  disabled,
  inventoryStale,
  museAvailability,
  onSave,
  onProject,
}: {
  token: string;
  project: Project;
  photos: Media[];
  disabled: boolean;
  inventoryStale: boolean;
  museAvailability?: MuseAvailability;
  onSave: (stocks: Stock[]) => void;
  onProject: (project: Project) => void;
}) {
  const api = useMemo(
    () => photoEstimates(token, project.id),
    [token, project.id],
  );
  const [records, setRecords] = useState<PhotoEstimateRecord[]>([]);
  const [cards, setCards] = useState<Card[]>(() =>
    cardsFor(project.stocks ?? [], []),
  );
  const [photoId, setPhotoId] = useState("");
  const [reference, setReference] = useState<Record<string, ReferenceDraft>>(
    {},
  );
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [museConsent, setMuseConsent] = useState(false);
  const [samConsent, setSamConsent] = useState(false);
  const [retry, setRetry] = useState<PhotoEstimateRequest | null>(null);
  const [samPending, setSamPending] = useState<PhotoLocalizationRequest | null>(
    null,
  );
  const [drawing, setDrawing] = useState<{
    card: string;
    what: "box" | "reference";
  } | null>(null);
  const [adjusting, setAdjusting] = useState<string | null>(null);
  const [ruler, setRuler] = useState<
    Record<string, Partial<Record<SizeField, string>>>
  >({});
  const [focus, setFocus] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // Saved state wins on every new inventory revision; history stays in records.
  const reload = useCallback(async () => {
    try {
      const list = await api.list();
      if (!alive.current) return;
      setRecords(list);
      setCards(cardsFor(project.stocks ?? [], list));
    } catch (failure) {
      if (alive.current) setError((failure as Error).message);
    }
  }, [api, project.stocks]);
  useEffect(() => {
    void reload();
  }, [reload, project.revision_id]);
  useEffect(() => {
    void localizationReceipts
      .pending(token, project.id)
      .then((body) => alive.current && setSamPending(body))
      .catch(() => alive.current && setSamPending(null));
  }, [token, project.id]);
  useEffect(() => {
    if (!photoId && photos.length) setPhotoId(photos[photos.length - 1].id);
    if (photoId && !photos.some((p) => p.id === photoId))
      setPhotoId(photos[0]?.id ?? "");
  }, [photos, photoId]);

  const photo = photos.find((p) => p.id === photoId);
  const draft: ReferenceDraft = reference[photoId] ?? {
    kind: "forma_card",
    lineA: "",
    lineB: "",
  };
  const locked = disabled || busy !== "" || Boolean(project.active_version_id);
  const savedJson = JSON.stringify(project.stocks ?? []);
  const unsaved = JSON.stringify(cards.map((c) => c.stock)) !== savedJson;
  const museReady = museAvailability?.enabled !== false;

  function patch(
    id: string,
    change: Partial<Card> | ((card: Card) => Partial<Card>),
  ) {
    setCards((current) =>
      current.map((card) =>
        card.stock.id === id
          ? {
              ...card,
              ...(typeof change === "function" ? change(card) : change),
            }
          : card,
      ),
    );
    setNotice("");
  }
  function addCard(label: string | null, mediaId: string | null) {
    setCards((current) => {
      const suggestion = label
        ? suggestFromLabel(label)
        : {
            kind: "sheet" as const,
            material: "cardboard" as const,
            materialGuessed: true,
          };
      const name = defaultName(
        suggestion,
        current.map((c) => c.name),
      );
      const id = stockIdFor(name, crypto.randomUUID());
      return [
        ...current,
        {
          stock: newStock(id, suggestion, mediaId),
          name,
          mediaId,
          materialGuessed: suggestion.materialGuessed,
          box: null,
          boxSource: "manual_box",
          polygon: null,
        },
      ];
    });
  }
  function rename(card: Card, name: string) {
    // The ID carries the name; a renamed material is a new identity, so its
    // estimates no longer apply until it is measured again.
    const id = stockIdFor(name || "Material", crypto.randomUUID());
    patch(card.stock.id, {
      name,
      stock: {
        ...card.stock,
        id,
        width_mm:
          card.stock.width_mm.source === "photo_estimate"
            ? { value: null, unit: "mm", source: "unknown", confirmed: false }
            : card.stock.width_mm,
        height_mm:
          card.stock.height_mm.source === "photo_estimate"
            ? { value: null, unit: "mm", source: "unknown", confirmed: false }
            : card.stock.height_mm,
      },
    });
  }

  async function suggest() {
    if (!photo || !museConsent || locked) return;
    setBusy("muse");
    setError("");
    try {
      const result = await requestIntakeObservation(
        token,
        project.id,
        photo.id,
        project.revision_id,
      );
      if (!alive.current) return;
      const labels = result.observation.labels.filter((label) => label.trim());
      for (const label of labels) addCard(label, photo.id);
      setNotice(
        labels.length
          ? `Muse suggested ${labels.length} material${labels.length === 1 ? "" : "s"}. Correct anything that is wrong; names and types are only suggestions.`
          : "Muse did not name any material. Add materials by hand.",
      );
    } catch (failure) {
      if (alive.current) setError((failure as Error).message);
    } finally {
      if (alive.current) {
        setBusy("");
        setMuseConsent(false);
      }
    }
  }

  async function locate(card: Card, body?: PhotoLocalizationRequest) {
    const target = photos.find(
      (p) => p.id === (body?.media_id ?? card.mediaId ?? photoId),
    );
    if (locked || !target) return;
    const request: PhotoLocalizationRequest = body ?? {
      media_id: target.id,
      expected_revision_id: project.revision_id,
      idempotency_key: crypto.randomUUID(),
      concept:
        card.name
          .replace(/[^\p{L}\p{N}_ -]/gu, " ")
          .replace(/ and /gi, " ")
          .trim()
          .slice(0, 80) || "material",
      provider_transfer_consented: true,
    };
    setBusy("sam:" + card.stock.id);
    setError("");
    try {
      await localizationReceipts.retain(token, project.id, request);
      setSamPending(request);
      const result = await localizePhoto(token, project.id, target, request);
      await localizationReceipts.clear(token, project.id, request);
      if (!alive.current) return;
      setSamPending(null);
      const best = [...result.boxes].sort(
        (a, b) => (b.x2 - b.x1) * (b.y2 - b.y1) - (a.x2 - a.x1) * (a.y2 - a.y1),
      )[0];
      if (!best) {
        setNotice(
          "SAM found nothing for this name. Draw a box around the material instead.",
        );
        return;
      }
      patch(card.stock.id, (c) => ({
        box: { x1: best.x1, y1: best.y1, x2: best.x2, y2: best.y2 },
        boxSource: "sam_box",
        polygon: null,
        mediaId: request.media_id,
        stock: c.stock.image_ids?.includes(request.media_id)
          ? c.stock
          : {
              ...c.stock,
              image_ids: [...(c.stock.image_ids ?? []), request.media_id],
            },
      }));
      setNotice(
        result.boxes.length > 1
          ? `SAM found ${result.boxes.length} matches; the largest is shown. Draw a box if it picked the wrong one.`
          : "SAM marked the material. Check the box, then measure.",
      );
    } catch (failure) {
      if (!alive.current) return;
      const definite =
        failure instanceof LocalizationError &&
        failure.status >= 400 &&
        failure.status < 500 &&
        failure.code !== "generation_in_progress" &&
        failure.code !== "generation_outcome_unknown";
      if (definite) {
        await localizationReceipts
          .clear(token, project.id, request)
          .catch(() => undefined);
        setSamPending(null);
      }
      setError((failure as Error).message);
    } finally {
      if (alive.current) {
        setBusy("");
        setSamConsent(false);
      }
    }
  }

  async function measure(
    card: Card,
    outlineOverride?: OutlineInput,
    exact?: PhotoEstimateRequest,
  ) {
    if (locked) return;
    setError("");
    let body: PhotoEstimateRequest;
    try {
      if (exact) body = exact;
      else {
        const mediaId = card.mediaId ?? photoId;
        const outline =
          outlineOverride ??
          (card.polygon
            ? polygonOutline(card.polygon)
            : card.box
              ? boxOutline(card.box, card.boxSource)
              : null);
        if (!outline)
          throw new Error(
            "Mark the material first: let SAM find it or draw a box.",
          );
        body = {
          media_id: mediaId,
          expected_revision_id: project.revision_id,
          idempotency_key: crypto.randomUUID(),
          stock_id: card.stock.id,
          stock_kind: card.stock.kind,
          stock_material: card.stock.material,
          reference: referenceInput(reference[mediaId] ?? draft),
          outline,
          capture: { shape: "flat", same_surface_as_reference: true },
        };
      }
    } catch (failure) {
      setError((failure as Error).message);
      return;
    }
    setBusy("measure:" + card.stock.id);
    setRetry(null);
    try {
      const record = await api.create(body);
      if (!alive.current) return;
      const list = await api.list();
      if (!alive.current) return;
      setRecords(list);
      patch(card.stock.id, (c) => ({
        stock: c.stock.image_ids?.includes(body.media_id)
          ? c.stock
          : {
              ...c.stock,
              image_ids: [...(c.stock.image_ids ?? []), body.media_id],
            },
      }));
      setNotice(
        record.estimate.outcome === "estimate"
          ? `Photo estimate ready for ${card.name}. It stays an estimate until you measure with a ruler.`
          : (record.estimate.request ?? "The photo could not support a size."),
      );
    } catch (failure) {
      if (!alive.current) return;
      if (failure instanceof EstimateRequestError && failure.retryExact)
        setRetry(body);
      setError((failure as Error).message);
    } finally {
      if (alive.current) setBusy("");
    }
  }

  // Next consequential question from #149, only on saved, unchanged inventory.
  const [decision, setDecision] = useState<Decision | null>(null);
  const [decisionError, setDecisionError] = useState("");
  const [answer, setAnswer] = useState("");
  const [asked, setAsked] = useState(0);
  const measurement = useMemo(
    () => measurementApi(token, project.id),
    [token, project.id],
  );
  const ready =
    project.inventory_confirmed &&
    !unsaved &&
    !inventoryStale &&
    !project.active_version_id;
  useEffect(() => {
    setDecision(null);
    setDecisionError("");
    if (!ready) return;
    const controller = new AbortController();
    measurement
      .decide(
        {
          expected_inventory_revision_id: project.revision_id,
          expected_active_version_id: project.active_version_id ?? null,
        },
        controller.signal,
      )
      .then((value) => {
        if (controller.signal.aborted) return;
        setDecision(value);
        setFocus(value.question?.target.stock_id ?? null);
      })
      .catch((failure) => {
        if (!controller.signal.aborted)
          setDecisionError(
            failure instanceof MeasurementRequestError
              ? failure.message
              : "The next question could not be loaded.",
          );
      });
    return () => controller.abort();
  }, [
    ready,
    measurement,
    project.revision_id,
    project.active_version_id,
    asked,
  ]);

  async function answerQuestion(value: number | null) {
    const question = decision?.question;
    if (!question || locked) return;
    setBusy("answer");
    setDecisionError("");
    try {
      if (value === null) {
        await measurement.unavailable(
          {
            expected_inventory_revision_id: project.revision_id,
            expected_active_version_id: project.active_version_id ?? null,
            expected_last_event_id: null,
            question_id: question.question_id,
            target_key: question.target.key,
            idempotency_key: crypto.randomUUID(),
            user_confirmed: true,
          },
          new AbortController().signal,
        );
        if (!alive.current) return;
        setNotice("Noted as unknown. FORMA will not ask for it again.");
        setAsked((value) => value + 1);
      } else {
        const body = answerBody(project, question, value, crypto.randomUUID());
        const result = await measurement.saveInventory(
          body,
          new AbortController().signal,
        );
        if (!alive.current) return;
        setAnswer("");
        onProject(result.project);
        setNotice("Measurement saved. Checking whether anything else matters…");
      }
    } catch (failure) {
      if (alive.current) setDecisionError((failure as Error).message);
    } finally {
      if (alive.current) setBusy("");
    }
  }

  const question = decision?.question ?? null;
  const questionCard = question?.target.stock_id
    ? cards.find((c) => c.stock.id === question.target.stock_id)
    : null;

  return (
    <section className="guided-intake" aria-labelledby="guided-title">
      <div className="section-title">
        <span aria-hidden="true">2</span>
        <h2 id="guided-title">Review your materials</h2>
      </div>
      <div className="status-area" aria-live="polite">
        {notice && <p className="notice">{notice}</p>}
        {error && (
          <div className="error" role="alert">
            <p>{error}</p>
            {retry && (
              <button
                type="button"
                className="secondary"
                disabled={locked}
                onClick={() => {
                  const card = cards.find((c) => c.stock.id === retry.stock_id);
                  if (card) void measure(card, undefined, retry);
                }}
              >
                Try the same measurement again
              </button>
            )}
          </div>
        )}
      </div>

      <details className="guided-reference">
        <summary>
          Size reference for this photo:{" "}
          {draft.kind === "forma_card"
            ? draft.lineA
              ? `FORMA card (line A ${draft.lineA} mm)`
              : "FORMA card — check its printed size"
            : draft.kind === "aruco_marker"
              ? "printed marker"
              : "rectangle you measured"}
        </summary>
        <p>
          Lay the reference flat next to your materials and keep everything in
          one photo, taken from above.{" "}
          <a href={REFERENCE_CARD_URL} target="_blank" rel="noopener">
            Print the FORMA reference card
          </a>{" "}
          at 100 % (Actual size), then measure its printed lines with a ruler.
          Printer scaling would otherwise change every size.
        </p>
        <fieldset disabled={locked}>
          <label>
            Reference
            <select
              value={draft.kind}
              onChange={(event) => {
                const kind = event.target.value as ReferenceDraft["kind"];
                setReference((r) => ({
                  ...r,
                  [photoId]:
                    kind === "forma_card"
                      ? { kind, lineA: "", lineB: "" }
                      : kind === "aruco_marker"
                        ? { kind, side: "", markerId: "" }
                        : { kind, width: "", height: "", corners: [] },
                }));
              }}
            >
              <option value="forma_card">FORMA card</option>
              <option value="aruco_marker">Single ArUco marker (4×4)</option>
              <option value="rectangle">A rectangle I measured</option>
            </select>
          </label>
          {draft.kind === "forma_card" && (
            <div className="field-row">
              <label>
                Line A, measured (mm)
                <input
                  inputMode="decimal"
                  value={draft.lineA}
                  placeholder="about 150"
                  onChange={(e) =>
                    setReference((r) => ({
                      ...r,
                      [photoId]: { ...draft, lineA: e.target.value },
                    }))
                  }
                />
              </label>
              <label>
                Line B, measured (mm, optional)
                <input
                  inputMode="decimal"
                  value={draft.lineB}
                  placeholder="about 100"
                  onChange={(e) =>
                    setReference((r) => ({
                      ...r,
                      [photoId]: { ...draft, lineB: e.target.value },
                    }))
                  }
                />
              </label>
            </div>
          )}
          {draft.kind === "aruco_marker" && (
            <div className="field-row">
              <label>
                Marker side, measured (mm)
                <input
                  inputMode="decimal"
                  value={draft.side}
                  onChange={(e) =>
                    setReference((r) => ({
                      ...r,
                      [photoId]: { ...draft, side: e.target.value },
                    }))
                  }
                />
              </label>
              <label>
                Marker ID
                <input
                  inputMode="numeric"
                  value={draft.markerId}
                  onChange={(e) =>
                    setReference((r) => ({
                      ...r,
                      [photoId]: { ...draft, markerId: e.target.value },
                    }))
                  }
                />
              </label>
            </div>
          )}
          {draft.kind === "rectangle" && (
            <>
              <div className="field-row">
                <label>
                  Width, first edge (mm)
                  <input
                    inputMode="decimal"
                    value={draft.width}
                    onChange={(e) =>
                      setReference((r) => ({
                        ...r,
                        [photoId]: { ...draft, width: e.target.value },
                      }))
                    }
                  />
                </label>
                <label>
                  Height (mm)
                  <input
                    inputMode="decimal"
                    value={draft.height}
                    onChange={(e) =>
                      setReference((r) => ({
                        ...r,
                        [photoId]: { ...draft, height: e.target.value },
                      }))
                    }
                  />
                </label>
              </div>
              <p className="help">
                {draft.corners.length}/4 corners placed. Tap the corners in
                order around the rectangle, starting at one end of the width. A
                single rectangle cannot show how accurate its own fit is.
              </p>
              <div className="button-row">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setDrawing({ card: "", what: "reference" })}
                >
                  Place corners on the photo
                </button>
                <button
                  type="button"
                  className="quiet"
                  onClick={() =>
                    setReference((r) => ({
                      ...r,
                      [photoId]: { ...draft, corners: [] },
                    }))
                  }
                >
                  Clear corners
                </button>
              </div>
            </>
          )}
        </fieldset>
        {photo && draft.kind === "rectangle" && (
          <PhotoCanvas
            token={token}
            projectId={project.id}
            photo={photo}
            label="Photo with the reference corners"
            reference={draft.corners}
            editable="reference"
            onMove={(index, point) =>
              setReference((r) => ({
                ...r,
                [photoId]: {
                  ...draft,
                  corners: draft.corners.map((p, i) =>
                    i === index ? point : p,
                  ),
                },
              }))
            }
            mode={
              drawing?.what === "reference" && draft.corners.length < 4
                ? {
                    kind: "add-points",
                    limit: 4,
                    onAdd: (point) =>
                      setReference((r) => ({
                        ...r,
                        [photoId]: {
                          ...draft,
                          corners: [...draft.corners, point].slice(0, 4),
                        },
                      })),
                  }
                : { kind: "view" }
            }
          />
        )}
      </details>

      {photos.length > 1 && (
        <label className="guided-photo-choice">
          Photo to work on
          <select
            value={photoId}
            onChange={(event) => setPhotoId(event.target.value)}
          >
            {photos.map((p, i) => (
              <option key={p.id} value={p.id}>
                Photo {i + 1}
              </option>
            ))}
          </select>
        </label>
      )}

      {cards.length === 0 && (
        <div className="guided-start">
          {photo && museReady ? (
            <>
              <p>
                FORMA can suggest the materials it sees. You correct anything
                that is wrong.
              </p>
              <label className="consent">
                <input
                  type="checkbox"
                  checked={museConsent}
                  disabled={locked}
                  onChange={(e) => setMuseConsent(e.target.checked)}
                />
                Send this photo to Meta Muse for suggestions (this request only)
              </label>
              <button
                type="button"
                className="primary"
                disabled={locked || !museConsent}
                onClick={() => void suggest()}
              >
                {busy === "muse"
                  ? "Asking Muse…"
                  : "Suggest materials from this photo"}
              </button>
            </>
          ) : (
            <p>
              {photo
                ? "Muse is unavailable. Add your materials by hand."
                : "Add a photo of your materials first, or add them by hand."}
            </p>
          )}
          <button
            type="button"
            className={photo && museReady ? "quiet" : "secondary"}
            disabled={locked}
            onClick={() => addCard(null, photo?.id ?? null)}
          >
            Add a material by hand
          </button>
        </div>
      )}

      {samPending && (
        <aside className="retry-panel">
          <p>
            An earlier SAM request has not finished. Check it before sending
            another.
          </p>
          <button
            type="button"
            className="secondary"
            disabled={locked}
            onClick={() => {
              const card = cards[0];
              if (card) void locate(card, samPending);
            }}
          >
            Check the earlier SAM request
          </button>
        </aside>
      )}

      <ol className="material-cards">
        {cards.map((card) => {
          const record = latestRecord(records, card.stock.id);
          const current = record?.status === "current" ? record : null;
          const summary = current ? estimateSummary(current.estimate) : null;
          const fields = sizeFieldsFor(card.stock.kind);
          const stale = stalePhotoValues(card.stock, records);
          const cardPhoto = photos.find(
            (p) => p.id === (card.mediaId ?? photoId),
          );
          const outlinePoints =
            adjusting === card.stock.id && card.polygon
              ? card.polygon
              : (current?.estimate.outline_px?.map((p) => ({ ...p })) ??
                card.polygon ??
                undefined);
          const highlighted = focus === card.stock.id;
          return (
            <li
              key={card.stock.id}
              className={
                highlighted ? "material-card highlighted" : "material-card"
              }
              id={`card-${card.stock.id}`}
            >
              <div className="material-card-head">
                <label className="material-name">
                  <span className="visually-hidden">Name</span>
                  <input
                    value={card.name}
                    disabled={locked}
                    onChange={(e) => rename(card, e.target.value)}
                    aria-label="Material name"
                  />
                </label>
                <button
                  type="button"
                  className="quiet danger"
                  disabled={locked}
                  onClick={() =>
                    setCards((cs) =>
                      cs.filter((c) => c.stock.id !== card.stock.id),
                    )
                  }
                >
                  Remove
                </button>
              </div>
              <div className="field-row">
                <label>
                  Type
                  <select
                    value={card.stock.kind}
                    disabled={locked}
                    onChange={(e) =>
                      patch(card.stock.id, (c) => ({
                        stock: {
                          ...c.stock,
                          kind: e.target.value as Stock["kind"],
                        },
                      }))
                    }
                  >
                    <option value="sheet">Sheet</option>
                    <option value="strip">Strip</option>
                    <option value="tape">Tape</option>
                    <option value="cord">Cord</option>
                  </select>
                </label>
                <label>
                  Material
                  <select
                    value={card.stock.material}
                    disabled={locked}
                    onChange={(e) =>
                      patch(card.stock.id, (c) => ({
                        materialGuessed: false,
                        stock: {
                          ...c.stock,
                          material: e.target.value as Stock["material"],
                        },
                      }))
                    }
                  >
                    <option value="cardboard">Cardboard</option>
                    <option value="paperboard">Paperboard</option>
                    <option value="other_supported">Other</option>
                  </select>
                </label>
              </div>
              {card.materialGuessed && (
                <p className="help">
                  Material type is a guess. Change it if it is wrong.
                </p>
              )}
              {cardPhoto && (
                <PhotoCanvas
                  token={token}
                  projectId={project.id}
                  photo={cardPhoto}
                  label={`Photo of ${card.name}`}
                  box={card.polygon ? null : card.box}
                  outline={outlinePoints}
                  reference={current?.estimate.reference_corners_px?.map(
                    (p) => ({ ...p }),
                  )}
                  editable={adjusting === card.stock.id ? "outline" : null}
                  onMove={(index, point) =>
                    patch(card.stock.id, (c) => ({
                      polygon: (c.polygon ?? []).map((p, i) =>
                        i === index ? point : p,
                      ),
                    }))
                  }
                  mode={
                    drawing?.card === card.stock.id && drawing.what === "box"
                      ? {
                          kind: "box",
                          onBox: (box) => {
                            patch(card.stock.id, {
                              box,
                              boxSource: "manual_box",
                              polygon: null,
                              mediaId: cardPhoto?.id ?? null,
                            });
                            setDrawing(null);
                          },
                        }
                      : ({ kind: "view" } as Mode)
                  }
                />
              )}
              {fields.length > 0 && cardPhoto && (
                <div className="button-row">
                  {museReady && (
                    <>
                      <label className="consent">
                        <input
                          type="checkbox"
                          checked={samConsent}
                          disabled={locked}
                          onChange={(e) => setSamConsent(e.target.checked)}
                        />
                        Send this photo and name to Meta SAM
                      </label>
                      <button
                        type="button"
                        className="secondary"
                        disabled={locked || !samConsent || !!samPending}
                        onClick={() => void locate(card)}
                      >
                        {busy === "sam:" + card.stock.id
                          ? "Finding…"
                          : "Find it in the photo"}
                      </button>
                    </>
                  )}
                  <button
                    type="button"
                    className="secondary"
                    disabled={locked}
                    onClick={() =>
                      setDrawing({ card: card.stock.id, what: "box" })
                    }
                  >
                    {drawing?.card === card.stock.id
                      ? "Drag across the material…"
                      : "Draw a box"}
                  </button>
                  <button
                    type="button"
                    className="primary"
                    disabled={locked || (!card.box && !card.polygon)}
                    onClick={() => void measure(card)}
                  >
                    {busy === "measure:" + card.stock.id
                      ? "Measuring…"
                      : "Measure from photo"}
                  </button>
                </div>
              )}
              {fields.length === 0 && (
                <p className="help">
                  {card.stock.kind === "tape"
                    ? "Tape width and remaining length cannot be read from a photo."
                    : "Cord length cannot be read from a photo."}{" "}
                  FORMA asks for them only if they matter.
                </p>
              )}
              {record && record.status === "stale" && (
                <p className="warning">
                  Earlier estimate is out of date:{" "}
                  {record.stale_reasons?.join(" ")} Measure again.
                </p>
              )}
              {stale.length > 0 && (
                <p className="warning">
                  The saved photo estimate no longer matches a current
                  measurement. Measure again or enter a ruler value.
                </p>
              )}
              {current && (
                <div className="estimate-result">
                  {summary ? (
                    <p>
                      <strong>Photo estimate:</strong> {summary}
                    </p>
                  ) : (
                    <p className="warning">{current.estimate.request}</p>
                  )}
                  {current.estimate.outcome === "enclosing_only" && (
                    <p className="help">{current.estimate.request}</p>
                  )}
                  <details>
                    <summary>Details</summary>
                    <dl className="estimate-details">
                      {(current.estimate.dimensions ?? []).map((d) => (
                        <div key={d.name}>
                          <dt>{d.definition}</dt>
                          <dd>
                            {d.display_value} {d.unit === "mm2" ? "mm²" : "mm"}{" "}
                            (sensitivity range {Math.round(d.sensitivity_low)}–
                            {Math.round(d.sensitivity_high)})
                          </dd>
                        </div>
                      ))}
                    </dl>
                    {current.estimate.uncertainty && (
                      <p className="help">
                        {current.estimate.uncertainty.statement}
                      </p>
                    )}
                    {current.estimate.uncertainty?.holdout_max_error_mm !=
                      null && (
                      <p className="help">
                        Independent card-marker check: worst error{" "}
                        {current.estimate.uncertainty.holdout_max_error_mm.toFixed(
                          1,
                        )}{" "}
                        mm over {current.estimate.uncertainty.holdout_checks}{" "}
                        markers.
                      </p>
                    )}
                    <ul>
                      {(current.estimate.diagnostics ?? [])
                        .filter((d) => d.severity !== "info")
                        .map((d, i) => (
                          <li key={i}>{d.message}</li>
                        ))}
                    </ul>
                    <p className="help">
                      Assumptions:{" "}
                      {(current.estimate.assumptions ?? []).join(" ")}
                    </p>
                    <p className="help">
                      Internal ID {card.stock.id}; method{" "}
                      {current.estimate.method_version}; lens{" "}
                      {current.estimate.calibration_status}.
                    </p>
                  </details>
                  <div className="button-row">
                    {(current.estimate.outline_px?.length ?? 0) > 2 &&
                      adjusting !== card.stock.id && (
                        <button
                          type="button"
                          className="quiet"
                          disabled={locked}
                          onClick={() => {
                            patch(card.stock.id, {
                              polygon: editablePoints(
                                current.estimate.outline_px!.map((p) => ({
                                  ...p,
                                })),
                              ),
                            });
                            setAdjusting(card.stock.id);
                          }}
                        >
                          Adjust outline
                        </button>
                      )}
                    {adjusting === card.stock.id && card.polygon && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={locked}
                        onClick={() => {
                          setAdjusting(null);
                          void measure(card, polygonOutline(card.polygon!));
                        }}
                      >
                        Measure the adjusted outline
                      </button>
                    )}
                  </div>
                </div>
              )}
              {fields.length > 0 && (
                <div className="size-actions">
                  {fields.map((field) => {
                    const state = sizeState(card.stock[field]);
                    return (
                      <p key={field} className="size-line">
                        {FIELD_LABEL[field]}:{" "}
                        {state.state === "unknown"
                          ? "unknown"
                          : state.state === "photo"
                            ? `${state.value} mm (photo estimate)`
                            : state.state === "measured"
                              ? `${state.value} mm (measured)`
                              : `${state.value ?? "?"} mm (${state.source})`}
                      </p>
                    );
                  })}
                  <div className="button-row">
                    {summary &&
                      current?.estimate.outcome === "estimate" &&
                      fields.some(
                        (field) =>
                          card.stock[field].source !== "photo_estimate" ||
                          stale.includes(field),
                      ) && (
                        <button
                          type="button"
                          className="secondary"
                          disabled={locked}
                          onClick={() => {
                            try {
                              patch(card.stock.id, (c) => ({
                                stock: applyEstimate(c.stock, current),
                              }));
                            } catch (failure) {
                              setError((failure as Error).message);
                            }
                          }}
                        >
                          Use photo estimate for exploring
                        </button>
                      )}
                    <button
                      type="button"
                      className="quiet"
                      disabled={locked}
                      onClick={() =>
                        patch(card.stock.id, (c) => ({
                          stock: fields.reduce(
                            (s, f) => clearValue(s, f),
                            c.stock,
                          ),
                        }))
                      }
                    >
                      I don&apos;t know
                    </button>
                  </div>
                  <details className="ruler-entry">
                    <summary>I measured it with a ruler</summary>
                    <div className="field-row">
                      {fields.map((field) => (
                        <label key={field}>
                          {FIELD_LABEL[field]} (mm)
                          <input
                            inputMode="decimal"
                            value={ruler[card.stock.id]?.[field] ?? ""}
                            onChange={(e) =>
                              setRuler((r) => ({
                                ...r,
                                [card.stock.id]: {
                                  ...r[card.stock.id],
                                  [field]: e.target.value,
                                },
                              }))
                            }
                          />
                        </label>
                      ))}
                    </div>
                    <button
                      type="button"
                      className="secondary"
                      disabled={locked}
                      onClick={() => {
                        try {
                          let next = card.stock;
                          for (const field of fields) {
                            const raw = ruler[card.stock.id]?.[field]?.trim();
                            if (raw)
                              next = recordRuler(
                                next,
                                field,
                                Number(raw.replace(",", ".")),
                              );
                          }
                          patch(card.stock.id, { stock: next });
                        } catch (failure) {
                          setError((failure as Error).message);
                        }
                      }}
                    >
                      Record ruler measurement
                    </button>
                  </details>
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {cards.length > 0 && (
        <div className="guided-save">
          <button
            type="button"
            className="quiet"
            disabled={locked}
            onClick={() => addCard(null, photo?.id ?? null)}
          >
            Add another material
          </button>
          <button
            type="button"
            className="primary"
            disabled={locked || inventoryStale || !unsaved}
            onClick={() => onSave(cards.map((c) => c.stock))}
          >
            Save materials
          </button>
          <span className="help">
            {unsaved
              ? "Unsaved changes. Unknown sizes stay unknown; photo estimates stay estimates."
              : project.inventory_confirmed
                ? "Materials saved."
                : ""}
          </span>
        </div>
      )}

      {ready && (
        <section
          className="next-question"
          aria-labelledby="next-question-title"
        >
          <h3 id="next-question-title">Next useful question</h3>
          {decisionError && <p className="error">{decisionError}</p>}
          {!decision && !decisionError && (
            <p className="help">Checking which measurement matters…</p>
          )}
          {decision && !question && (
            <>
              <p>
                {decision.outcome === "none_needed"
                  ? "No more measurements are needed right now."
                  : decision.reasons[0]}
              </p>
              <p className="help">Review the checked design proposals below.</p>
            </>
          )}
          {question && (
            <div className="question-card">
              <p>
                <strong>{question.target.label}</strong>
                {questionCard ? ` — ${questionCard.name}` : ""}
              </p>
              <p>{question.why}</p>
              <p className="help">
                How: {question.method} {question.where}
              </p>
              {question.current?.value != null && (
                <p className="help">
                  Saved now: {question.current.value} {question.unit}
                  {question.current.source === "photo_estimate"
                    ? " (photo estimate — not enough to decide)"
                    : question.current.confirmed
                      ? ""
                      : " (estimate)"}
                </p>
              )}
              {question.capture !== "stability_measurements" &&
              question.unit !== "batch" &&
              question.target.property !== "usable_region" ? (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    const value = Number(answer.replace(",", "."));
                    if (Number.isFinite(value) && value > 0)
                      void answerQuestion(value);
                    else
                      setDecisionError(
                        "Enter a measured value greater than zero.",
                      );
                  }}
                >
                  <label>
                    Measured value ({question.unit})
                    <input
                      inputMode="decimal"
                      value={answer}
                      onChange={(e) => setAnswer(e.target.value)}
                      disabled={locked}
                    />
                  </label>
                  <div className="button-row">
                    <button
                      type="submit"
                      className="primary"
                      disabled={locked || !answer.trim()}
                    >
                      Save measurement
                    </button>
                    <button
                      type="button"
                      className="quiet"
                      disabled={locked}
                      onClick={() => void answerQuestion(null)}
                    >
                      I don&apos;t know
                    </button>
                  </div>
                </form>
              ) : (
                <p className="help">
                  Answer this in the build requirements under Details.
                </p>
              )}
              {(decision?.pending_questions ?? 0) > 0 && (
                <p className="help">
                  {decision?.pending_questions} more may follow, only if they
                  still matter.
                </p>
              )}
            </div>
          )}
        </section>
      )}
    </section>
  );
}
