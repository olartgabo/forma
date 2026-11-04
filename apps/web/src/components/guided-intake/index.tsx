"use client";
// Guided photo-first intake (#177): photograph, review named cards, save,
// then answer the one next measurement question that can change the result.
// Stock values live in the workbench's rows (one draft shared with Details);
// this component keeps only display state such as names, boxes and outlines.
import { useEffect, useMemo, useRef, useState } from "react";
import { loadProject, requestIntakeObservation } from "../../lib/api";
import {
  localizationReceipts,
  localizePhoto,
  LocalizationError,
  suggestOutline,
  validLocalizationRequest,
} from "../../lib/photo-localization";
import {
  EstimateRequestError,
  photoEstimates,
  REFERENCE_CARD_URL,
} from "../../lib/photo-estimates";
import type { MuseAvailability } from "../../lib/muse-provider";
import type {
  InventoryUpdate,
  Media,
  PhotoEstimateRecord,
  PhotoEstimateRequest,
  PhotoLocalizationRequest,
  Project,
  UnavailableRequest,
} from "../../lib/generated/api-contracts";
import type {
  OutlineInput,
  RecognizedItem,
  Stock,
} from "../../lib/generated/contracts";
import type { RecognizedItemsUpdate } from "../../lib/generated/api-contracts";
import {
  ItemsRequestError,
  recognizedItems,
  validProposals,
} from "../../lib/recognized-items";
import IdentifiedItems from "./identified-items";
import MaterialBoard from "../material-board";
import {
  identityLabel,
  intakeNotice,
  keepValidLink,
  linkFits,
  linkStock,
  mergeProposals,
  normalise,
  pickSamBox,
  support,
} from "./recognized";
import {
  answerBody,
  answerReceipts,
  measurementApi,
  MeasurementRequestError,
  unavailableReceipts,
  type Decision,
} from "../active-measurement/client";
// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { receipts } from "../design-candidates/pending.ts";
import PhotoCanvas, { type Mode } from "./photo-canvas";
import {
  boxOutline,
  clearValue,
  defaultName,
  editablePoints,
  estimateSummary,
  latestRecord,
  displayName,
  newStock,
  polygonOutline,
  recordRuler,
  referenceInput,
  sizeFieldsFor,
  sizeState,
  stalePhotoValues,
  renameStock,
  replaceStock,
  stockIdFor,
  suggestFromLabel,
  applyEstimate,
  usableSamBoxes,
  type Box,
  type Point,
  type ReferenceDraft,
  type SizeField,
} from "./model";

type Extra = {
  mediaId: string | null;
  materialGuessed: boolean;
  box: Box | null;
  boxSource: "sam_box" | "manual_box" | "outline_suggestion";
  polygon: Point[] | null;
};
type Card = Extra & { stock: Stock; name: string };

// Which material a retained SAM request was for, so a recovered result can
// only attach to that material.
type SamTarget = { request: PhotoLocalizationRequest; stock_id: string };
const samTargets = receipts<SamTarget>(
  "forma-guided-sam-target-v1:",
  (v: unknown): v is SamTarget =>
    !!v &&
    typeof v === "object" &&
    typeof (v as SamTarget).stock_id === "string" &&
    validLocalizationRequest((v as SamTarget).request),
  "SAM material",
);

const FIELD_LABEL: Record<SizeField, string> = {
  width_mm: "Longer side",
  height_mm: "Shorter side",
};

function extraFor(
  stock: Stock,
  records: readonly PhotoEstimateRecord[],
): Extra {
  const record = latestRecord(records, stock.id);
  const outline = record?.estimate.input.outline;
  return {
    mediaId: record?.estimate.input.media_id ?? stock.image_ids?.[0] ?? null,
    materialGuessed: false,
    box:
      outline && outline.source !== "user_polygon"
        ? { x1: outline.x1!, y1: outline.y1!, x2: outline.x2!, y2: outline.y2! }
        : null,
    boxSource:
      outline?.source === "sam_box" || outline?.source === "outline_suggestion"
        ? outline.source
        : "manual_box",
    polygon:
      outline?.source === "user_polygon"
        ? (outline.polygon_px ?? []).map((p) => ({ ...p }))
        : null,
  };
}

export default function GuidedIntake({
  token,
  project,
  photos,
  stocks,
  dirty,
  disabled,
  inventoryStale,
  museAvailability,
  tools = [],
  designBusy = false,
  designReady = false,
  onStocks,
  onBusy,
  onSave,
  onProject,
}: {
  token: string;
  project: Project;
  photos: Media[];
  // The shared unsaved draft (the workbench rows) and whether it differs
  // from the saved inventory.
  stocks: readonly Stock[];
  dirty: boolean;
  disabled: boolean;
  inventoryStale: boolean;
  museAvailability?: MuseAvailability;
  tools?: readonly string[];
  designBusy?: boolean;
  designReady?: boolean;
  // Applied to the latest shared draft, never to a stale snapshot.
  onStocks: (update: (current: readonly Stock[]) => Stock[]) => void;
  // True while a guided request runs; the workbench locks Details meanwhile.
  onBusy: (busy: boolean) => void;
  // `after` runs only when this exact inventory save succeeds.
  onSave: (after?: () => void) => void;
  onProject: (project: Project) => void;
}) {
  const api = useMemo(
    () => photoEstimates(token, project.id),
    [token, project.id],
  );
  const [records, setRecords] = useState<PhotoEstimateRecord[]>([]);
  // Identified-item cards: saved separately from stock, never confirming it.
  const itemsApi = useMemo(
    () => recognizedItems(token, project.id),
    [token, project.id],
  );
  const [items, setItems] = useState<RecognizedItem[]>([]);
  const [itemsRevision, setItemsRevision] = useState<string | null>(null);
  const [itemsState, setItemsState] = useState<"loading" | "ready" | "failed">(
    "loading",
  );
  const [itemsDirty, setItemsDirty] = useState(false);
  const [itemProblems, setItemProblems] = useState<Record<string, string[]>>(
    {},
  );
  // A save whose answer was lost: retried with the same body and key before
  // any later edits are sent, so its receipt is never orphaned.
  const pendingItems = useRef<RecognizedItemsUpdate | null>(null);
  // Bumped by the workbench when the inventory save the cards wait for lands.
  const [itemsSaveTick, setItemsSaveTick] = useState(0);
  const [extras, setExtras] = useState<Record<string, Extra>>({});
  const [nameDrafts, setNameDrafts] = useState<Record<string, string>>({});
  const [photoId, setPhotoId] = useState("");
  const [reference, setReference] = useState<Record<string, ReferenceDraft>>(
    {},
  );
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // Materials SAM found no usable region for: the photo, reference and
  // material are kept, and the card offers a drawn box or a suggestion.
  const [samMissed, setSamMissed] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [museConsent, setMuseConsent] = useState(false);
  const [samConsent, setSamConsent] = useState(false);
  const [captureConfirmed, setCaptureConfirmed] = useState<
    Record<string, boolean>
  >({});
  const [retry, setRetry] = useState<PhotoEstimateRequest | null>(null);
  const [samPending, setSamPending] = useState<PhotoLocalizationRequest | null>(
    null,
  );
  const [samTarget, setSamTarget] = useState<string | null>(null);
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

  useEffect(() => {
    const controller = new AbortController();
    itemsApi
      .read(controller.signal)
      .then((saved) => {
        if (controller.signal.aborted) return;
        setItems([...saved.items]);
        setItemsRevision(saved.revision);
        setItemProblems(problemMap(saved.problems ?? []));
        setItemsState("ready");
      })
      .catch((failure) => {
        if (controller.signal.aborted) return;
        setItemsState("failed");
        setError(
          `${(failure as Error).message} Item cards are unavailable until the project is reloaded; materials can still be edited.`,
        );
      });
    return () => controller.abort();
  }, [itemsApi]);

  function changeItems(
    update: (current: RecognizedItem[]) => RecognizedItem[],
  ) {
    setItems(update);
    setItemsDirty(true);
  }
  function changeItem(
    id: string,
    update: (item: RecognizedItem) => RecognizedItem,
  ) {
    const before = items.find((i) => i.id === id);
    if (!before) return;
    let next = keepValidLink(update(before), stocks);
    const linked = next.stock_id;
    if (
      linked &&
      !linkFits(next, stocks) &&
      !(project.stocks ?? []).some((s) => s.id === linked)
    ) {
      // Generated for this item and never saved: it goes with the link.
      onStocks((current) => current.filter((s) => s.id !== linked));
      next = { ...next, stock_id: null };
    }
    // A saved material keeps its link; the mismatch is shown on both cards and
    // reported by the server until the user removes it or changes it back.
    changeItems((current) => current.map((i) => (i.id === id ? next : i)));
  }
  async function saveItems() {
    if (itemsState !== "ready") {
      setError(
        "Saved item cards could not be loaded, so they were not saved. Reload the project and try again.",
      );
      return;
    }
    const draft = items.map((item) =>
      keepValidLink(item, project.stocks ?? []),
    );
    setBusy("items");
    try {
      let revision = itemsRevision;
      let saved = null;
      let sent: readonly RecognizedItem[] | null = null;
      if (pendingItems.current) {
        saved = await itemsApi.save(pendingItems.current);
        sent = pendingItems.current.items ?? [];
        pendingItems.current = null;
        revision = saved.revision;
        // Keep the recovered revision even if the next save fails.
        if (alive.current) {
          setItemsRevision(saved.revision);
          setItemProblems(problemMap(saved.problems ?? []));
        }
      }
      if (!sent || JSON.stringify(sent) !== JSON.stringify(draft)) {
        const body: RecognizedItemsUpdate = {
          expected_revision: revision,
          idempotency_key: crypto.randomUUID(),
          items: draft,
        };
        pendingItems.current = body;
        saved = await itemsApi.save(body);
        pendingItems.current = null;
      }
      if (!alive.current || !saved) return;
      setItems([...saved.items]);
      setItemsRevision(saved.revision);
      setItemProblems(problemMap(saved.problems ?? []));
      setItemsDirty(false);
      if (
        typeof saved.inventory_revision_id === "string" &&
        saved.inventory_revision_id !== project.revision_id
      ) {
        // Confirmation changed under a new inventory revision.
        const fresh = await loadProject(token, project.id);
        if (alive.current) onProject(fresh);
        if (alive.current && !saved.inventory_confirmed)
          setNotice(
            "An item now contradicts a saved material, so the materials are no longer confirmed for design. Reconcile it on the material card.",
          );
      }
    } catch (failure) {
      if (!(failure as ItemsRequestError).retryExact)
        pendingItems.current = null;
      if (alive.current) setError((failure as Error).message);
    } finally {
      if (alive.current) setBusy("");
    }
  }
  // Item cards are saved only after the exact inventory save they wait for.
  useEffect(() => {
    if (itemsSaveTick) void saveItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemsSaveTick]);
  function useAsMaterial(item: RecognizedItem) {
    const s = support(item.identity);
    if (s.state !== "available") return;
    const id = stockIdFor(item.name, crypto.randomUUID());
    const stock = newStock(
      id,
      { kind: s.kind, material: s.material, materialGuessed: false },
      item.media_id ?? null,
      item.name,
    );
    setExtras((current) => ({
      ...current,
      [id]: {
        mediaId: item.media_id ?? null,
        materialGuessed: false,
        box: null,
        boxSource: "manual_box",
        polygon: null,
      },
    }));
    onStocks((current) => [...current, stock]);
    changeItems((current) =>
      current.map((i) => (i.id === item.id ? linkStock(i, stock) : i)),
    );
  }

  // Estimate history for this project only; a late answer for an earlier
  // project or revision is discarded. The parent also keys this component by
  // project, so switching projects starts a fresh instance.
  const [listAttempt, setListAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api
      .list(controller.signal)
      .then((list) => {
        if (!controller.signal.aborted) setRecords(list);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError((failure as Error).message);
      });
    return () => controller.abort();
  }, [api, project.revision_id, listAttempt]);
  useEffect(() => {
    let live = true;
    Promise.all([
      localizationReceipts.pending(token, project.id),
      samTargets.pending(token, project.id),
    ])
      .then(([body, target]) => {
        if (!live) return;
        setSamPending(body);
        setSamTarget(
          body &&
            target &&
            target.request.idempotency_key === body.idempotency_key
            ? target.stock_id
            : null,
        );
      })
      .catch(() => live && setSamPending(null));
    return () => {
      live = false;
    };
  }, [token, project.id]);
  useEffect(() => {
    if (!photoId && photos.length) setPhotoId(photos[photos.length - 1].id);
    if (photoId && !photos.some((p) => p.id === photoId))
      setPhotoId(photos[0]?.id ?? "");
  }, [photos, photoId]);

  const cards: Card[] = stocks.map((stock) => ({
    ...extraFor(stock, records),
    ...extras[stock.id],
    stock,
    name: displayName(stock),
  }));
  const photo = photos.find((p) => p.id === photoId);
  const draft: ReferenceDraft = reference[photoId] ?? {
    kind: "forma_card",
    lineA: "",
    lineB: "",
  };
  const locked = disabled || busy !== "" || Boolean(project.active_version_id);
  const museReady = museAvailability?.enabled !== false;
  useEffect(() => {
    onBusy(busy !== "");
  }, [busy, onBusy]);
  useEffect(() => () => onBusy(false), [onBusy]);

  function patch(
    id: string,
    change: Partial<Card> | ((card: Card) => Partial<Card>),
  ) {
    const card = cards.find((c) => c.stock.id === id);
    if (!card) return;
    const next = {
      ...card,
      ...(typeof change === "function" ? change(card) : change),
    };
    const { stock, name: _name, ...extra } = next;
    setExtras((current) => {
      const copy = { ...current };
      delete copy[id];
      copy[stock.id] = extra;
      return copy;
    });
    if (stock !== card.stock)
      onStocks((current) => current.map((s) => (s.id === id ? stock : s)));
    setNotice("");
  }
  function addCard(labels: (string | null)[], mediaId: string | null) {
    const taken = cards.map((c) => c.name);
    const added: Stock[] = [];
    const newExtras: Record<string, Extra> = {};
    for (const label of labels) {
      const suggestion = label
        ? suggestFromLabel(label)
        : {
            kind: "sheet" as const,
            material: "cardboard" as const,
            materialGuessed: true,
          };
      const name = defaultName(suggestion, taken);
      taken.push(name);
      const id = stockIdFor(name, crypto.randomUUID());
      added.push(newStock(id, suggestion, mediaId, name));
      newExtras[id] = {
        mediaId,
        materialGuessed: suggestion.materialGuessed,
        box: null,
        boxSource: "manual_box",
        polygon: null,
      };
    }
    setExtras((current) => ({ ...current, ...newExtras }));
    onStocks((current) => [...current, ...added]);
  }
  function remove(card: Card) {
    onStocks((current) => current.filter((s) => s.id !== card.stock.id));
    if (items.some((i) => i.stock_id === card.stock.id))
      changeItems((current) =>
        current.map((i) =>
          i.stock_id === card.stock.id ? { ...i, stock_id: null } : i,
        ),
      );
  }
  function commitName(card: Card) {
    const name = nameDrafts[card.stock.id];
    setNameDrafts((drafts) => {
      const copy = { ...drafts };
      delete copy[card.stock.id];
      return copy;
    });
    if (name === undefined || name.trim() === card.name) return;
    // Renaming keeps the stable ID, photo links and estimates.
    patch(card.stock.id, (c) => ({ stock: renameStock(c.stock, name) }));
  }
  function replacePiece(card: Card) {
    // A different physical piece: new ID, photo values and links dropped.
    const stock = replaceStock(card.stock, crypto.randomUUID());
    patch(card.stock.id, {
      stock,
      mediaId: null,
      box: null,
      boxSource: "manual_box",
      polygon: null,
    });
    setNotice(
      `${card.name} is now a different piece. Take a photo or measure it again.`,
    );
  }

  async function suggest() {
    if (!photo || !museConsent || locked || itemsState !== "ready") return;
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
      setNotice(
        intakeNotice(
          result.observation,
          validProposals(result.observation.items),
          (proposals) => {
            const merged = mergeProposals(items, proposals, photo.id, (name) =>
              stockIdFor(name, crypto.randomUUID()),
            );
            changeItems(() => merged.items);
            for (const item of merged.items.slice(items.length))
              if (support(item.identity).state === "available")
                useAsMaterial(item);
            return merged;
          },
        ),
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

  async function locate(card: Card | null, body?: PhotoLocalizationRequest) {
    const target = photos.find(
      (p) => p.id === (body?.media_id ?? card?.mediaId ?? photoId),
    );
    if (locked || !target || (!card && !body)) return;
    const request: PhotoLocalizationRequest = body ?? {
      media_id: target.id,
      expected_revision_id: project.revision_id,
      idempotency_key: crypto.randomUUID(),
      concept:
        card!.name
          .replace(/[^\p{L}\p{N}_ -]/gu, " ")
          .replace(/ and /gi, " ")
          .trim()
          .slice(0, 80) || "material",
      provider_transfer_consented: true,
    };
    setBusy("sam:" + (card?.stock.id ?? ""));
    setError("");
    try {
      if (!body) {
        await samTargets.retain(token, project.id, {
          request,
          stock_id: card!.stock.id,
        });
        await localizationReceipts.retain(token, project.id, request);
        setSamTarget(card!.stock.id);
      }
      setSamPending(request);
      const result = await localizePhoto(token, project.id, target, request);
      await localizationReceipts.clear(token, project.id, request);
      await samTargets.discard(token, project.id).catch(() => undefined);
      if (!alive.current) return;
      setSamPending(null);
      setSamTarget(null);
      // A card from a Muse item takes the SAM box that overlaps its own
      // approximate box, so several similar objects stay separate.
      const item = card
        ? items.find(
            (i) =>
              i.stock_id === card.stock.id && i.media_id === request.media_id,
          )
        : undefined;
      if (!card) {
        setNotice(
          "The earlier SAM request finished, but the material it was for is no longer here. Draw a box instead.",
        );
        return;
      }
      // Never the whole photo or the reference. Where the reference is must
      // be known before a SAM box is selected automatically.
      let corners = referenceCorners(request.media_id);
      if (!corners.length && result.boxes.length) {
        const located = await locateReference(target, card);
        if (!alive.current) return;
        if (!located) {
          setSamMissed((m) => ({
            ...m,
            [card.stock.id]:
              `SAM marked ${result.boxes.length} region${result.boxes.length === 1 ? "" : "s"} for \u201c${request.concept}\u201d, but the reference in this photo could not be located, so none was selected in case it is the reference.`,
          }));
          return;
        }
        corners = located;
      }
      const { usable, rejected } = usableSamBoxes(
        result.boxes,
        result.width_px,
        result.height_px,
        corners,
      );
      const scaled = usable.map((b) =>
        normalise(b, result.width_px, result.height_px),
      );
      const picked = item?.box ? pickSamBox(item, scaled) : null;
      const best = picked
        ? usable[scaled.indexOf(picked)]
        : item?.box
          ? undefined
          : [...usable].sort(
              (a, b) =>
                (b.x2 - b.x1) * (b.y2 - b.y1) - (a.x2 - a.x1) * (a.y2 - a.y1),
            )[0];
      if (!best) {
        setSamMissed((m) => ({
          ...m,
          [card.stock.id]: !result.boxes.length
            ? `SAM returned no region for \u201c${request.concept}\u201d in this photo.`
            : rejected === result.boxes.length
              ? `SAM only marked the whole photo or the reference for \u201c${request.concept}\u201d, so nothing was selected.`
              : `SAM's regions for \u201c${request.concept}\u201d do not overlap where Muse placed this item, so nothing was selected.`,
        }));
        return;
      }
      setSamMissed((m) => {
        const copy = { ...m };
        delete copy[card.stock.id];
        return copy;
      });
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
        usable.length > 1
          ? `SAM found ${usable.length} matches; ${picked ? "the one where Muse placed this item" : "the largest"} is shown. Draw a box if it picked the wrong one.`
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
        await samTargets.discard(token, project.id).catch(() => undefined);
        setSamPending(null);
        setSamTarget(null);
      }
      setError((failure as Error).message);
    } finally {
      if (alive.current) {
        setBusy("");
        setSamConsent(false);
      }
    }
  }

  // The reference set up for this photo only; never another photo's draft.
  function photoReference(mediaId: string): ReferenceDraft {
    const own = reference[mediaId] ?? (mediaId === photoId ? draft : null);
    if (!own)
      throw new Error(
        "Set up the reference for this photo first: select the photo and describe its reference.",
      );
    return own;
  }

  // Where the whole reference is, found locally (no provider call), or null
  // when it cannot be located.
  async function locateReference(target: Media, card: Card) {
    try {
      const found = await suggestOutline(token, project.id, target, {
        media_id: target.id,
        expected_revision_id: project.revision_id,
        stock_kind: card.stock.kind,
        reference: referenceInput(photoReference(target.id)),
      });
      return found.reference_corners_px.length >= 4
        ? found.reference_corners_px
        : null;
    } catch {
      return null;
    }
  }

  // Where the reference is in a photo: drawn corners, or the corners the
  // estimator found in an earlier estimate of the same photo.
  function referenceCorners(mediaId: string): Point[] {
    const drawn = reference[mediaId];
    if (drawn?.kind === "rectangle") return drawn.corners;
    // Only complete geometry for the same reference type: all sixteen card
    // corners, or four for a single marker. A partly found card is unknown.
    const kind = (reference[mediaId] ?? (mediaId === photoId ? draft : null))
      ?.kind;
    const earlier = records.find(
      (r) =>
        r.estimate.input.media_id === mediaId &&
        r.estimate.input.reference.kind === kind &&
        (r.estimate.reference_corners_px?.length ?? 0) ===
          (kind === "forma_card" ? 16 : 4),
    );
    return (earlier?.estimate.reference_corners_px ?? []).map((p) => ({
      ...p,
    }));
  }

  async function suggestRegion(card: Card) {
    const target = photos.find((p) => p.id === (card.mediaId ?? photoId));
    if (locked || !target) return;
    let referenceBody;
    try {
      referenceBody = referenceInput(photoReference(target.id));
    } catch (failure) {
      setError((failure as Error).message);
      return;
    }
    setBusy("outline:" + card.stock.id);
    setError("");
    try {
      const found = await suggestOutline(token, project.id, target, {
        media_id: target.id,
        expected_revision_id: project.revision_id,
        stock_kind: card.stock.kind,
        reference: referenceBody,
      });
      if (!alive.current) return;
      if (found.box) {
        patch(card.stock.id, (c) => ({
          box: found.box,
          boxSource: "outline_suggestion",
          polygon: null,
          mediaId: target.id,
          stock: c.stock.image_ids?.includes(target.id)
            ? c.stock
            : {
                ...c.stock,
                image_ids: [...(c.stock.image_ids ?? []), target.id],
              },
        }));
        setSamMissed((m) => {
          const copy = { ...m };
          delete copy[card.stock.id];
          return copy;
        });
      }
      setNotice(found.message);
    } catch (failure) {
      if (alive.current) setError((failure as Error).message);
    } finally {
      if (alive.current) setBusy("");
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
        if (!captureConfirmed[`${card.stock.id}:${mediaId}`])
          throw new Error(
            "Confirm that this piece is flat and on the same surface as the reference before measuring.",
          );
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
          reference: referenceInput(photoReference(mediaId)),
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
      setListAttempt((value) => value + 1);
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
  // Exact requests whose outcome is unknown; retried unchanged, never rebuilt.
  const [pendingAnswer, setPendingAnswer] = useState<InventoryUpdate | null>(
    null,
  );
  const [pendingUnavailable, setPendingUnavailable] =
    useState<UnavailableRequest | null>(null);
  const measurement = useMemo(
    () => measurementApi(token, project.id),
    [token, project.id],
  );
  useEffect(() => {
    let live = true;
    Promise.all([
      answerReceipts.pending(token, project.id),
      unavailableReceipts.pending(token, project.id),
    ])
      .then(([a, u]) => {
        if (!live) return;
        setPendingAnswer(a);
        setPendingUnavailable(u);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [token, project.id]);
  const ready =
    project.inventory_confirmed &&
    !dirty &&
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

  async function sendAnswer(body: InventoryUpdate) {
    setBusy("answer");
    setDecisionError("");
    try {
      await answerReceipts.retain(token, project.id, body);
      setPendingAnswer(body);
      const result = await measurement.saveInventory(
        body,
        new AbortController().signal,
      );
      await answerReceipts
        .clear(token, project.id, body)
        .catch(() => undefined);
      if (!alive.current) return;
      setPendingAnswer(null);
      setAnswer("");
      onProject(result.project);
      setNotice("Measurement saved. Checking whether anything else matters…");
    } catch (failure) {
      if (!alive.current) return;
      if (!(failure instanceof MeasurementRequestError && failure.retry)) {
        await answerReceipts
          .clear(token, project.id, body)
          .catch(() => undefined);
        setPendingAnswer(null);
        setDecisionError(
          `The measurement was not saved. ${(failure as Error).message}`,
        );
      } else setDecisionError((failure as Error).message);
    } finally {
      if (alive.current) setBusy("");
    }
  }
  async function sendUnavailable(body: UnavailableRequest) {
    setBusy("answer");
    setDecisionError("");
    try {
      await unavailableReceipts.retain(token, project.id, body);
      setPendingUnavailable(body);
      await measurement.unavailable(body, new AbortController().signal);
      await unavailableReceipts
        .clear(token, project.id, body)
        .catch(() => undefined);
      if (!alive.current) return;
      setPendingUnavailable(null);
      setNotice("Noted as unknown. FORMA will not ask for it again.");
      setAsked((value) => value + 1);
    } catch (failure) {
      if (!alive.current) return;
      if (!(failure instanceof MeasurementRequestError && failure.retry)) {
        await unavailableReceipts
          .clear(token, project.id, body)
          .catch(() => undefined);
        setPendingUnavailable(null);
      }
      setDecisionError((failure as Error).message);
    } finally {
      if (alive.current) setBusy("");
    }
  }
  function answerQuestion(value: number | null) {
    const question = decision?.question;
    if (!question || locked) return;
    if (pendingAnswer || pendingUnavailable) {
      setDecisionError(
        "An earlier answer has an unknown outcome. Retry it first.",
      );
      return;
    }
    try {
      if (value === null)
        void sendUnavailable({
          expected_inventory_revision_id: project.revision_id,
          expected_active_version_id: project.active_version_id ?? null,
          expected_last_event_id: null,
          question_id: question.question_id,
          target_key: question.target.key,
          idempotency_key: crypto.randomUUID(),
          user_confirmed: true,
        });
      else
        void sendAnswer(
          answerBody(project, question, value, crypto.randomUUID()),
        );
    } catch (failure) {
      setDecisionError((failure as Error).message);
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
      <MaterialBoard
        items={items}
        stocks={stocks}
        tools={tools.filter((name) => name.trim())}
        designReady={designReady}
        designBusy={designBusy}
        status={
          busy === "muse"
            ? "Looking at your materials…"
            : itemsState === "loading"
              ? "Loading your saved materials…"
              : designBusy
                ? "Preparing your design. Your materials stay here."
                : busy
                  ? "Updating your materials…"
                  : null
        }
        onReview={(target) => {
          const element =
            target === "design"
              ? document.getElementById("muse-construction-title")
              : target === "tools"
                ? document.getElementById("available-tools")
                : target
                  ? document.getElementById(target)
                  : document.getElementById("material-review-details");
          if (!element) return;
          if (target === "design") {
            element.tabIndex = -1;
            element.scrollIntoView({ block: "start" });
            element.focus({ preventScroll: true });
            return;
          }
          let parent = element.parentElement;
          while (parent) {
            if (parent instanceof HTMLDetailsElement) parent.open = true;
            parent = parent.parentElement;
          }
          if (element instanceof HTMLDetailsElement) element.open = true;
          element.scrollIntoView({ block: "start" });
          const control = element.matches("input,textarea,select,button")
            ? element
            : element.querySelector("input,select,button,summary");
          (control as HTMLElement | null)?.focus({ preventScroll: true });
        }}
      />
      <details
        id="material-review-details"
        open={items.length === 0 && cards.length === 0}
      >
        <summary>Review and edit every material</summary>
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
                  order around the rectangle, starting at one end of the width.
                  A single rectangle cannot show how accurate its own fit is.
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
                  Send this photo to Meta Muse for suggestions (this request
                  only)
                </label>
                <button
                  type="button"
                  className="primary"
                  disabled={locked || !museConsent || itemsState !== "ready"}
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
              onClick={() => addCard([null], photo?.id ?? null)}
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
                void locate(
                  cards.find((c) => c.stock.id === samTarget) ?? null,
                  samPending,
                );
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
                      value={nameDrafts[card.stock.id] ?? card.name}
                      disabled={locked}
                      onChange={(e) =>
                        setNameDrafts((d) => ({
                          ...d,
                          [card.stock.id]: e.target.value,
                        }))
                      }
                      onBlur={() => commitName(card)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitName(card);
                      }}
                      aria-label="Material name"
                    />
                  </label>
                  <button
                    type="button"
                    className="quiet danger"
                    disabled={locked}
                    onClick={() => remove(card)}
                  >
                    Remove
                  </button>
                  <button
                    type="button"
                    className="quiet"
                    disabled={locked}
                    onClick={() => replacePiece(card)}
                  >
                    Different piece
                  </button>
                </div>
                {items
                  .filter(
                    (i) =>
                      i.stock_id === card.stock.id &&
                      !linkFits(i, [card.stock]),
                  )
                  .map((i) => (
                    <div key={i.id} className="warning reconcile" role="alert">
                      <p>
                        &ldquo;{i.name}&rdquo; is now identified as{" "}
                        {identityLabel(i.identity)}, but this material is saved
                        as {card.stock.material} {card.stock.kind}. It cannot be
                        used for a design until you choose:
                      </p>
                      <div className="button-row">
                        <button
                          type="button"
                          className="secondary"
                          disabled={locked}
                          onClick={() => remove(card)}
                        >
                          Remove this material
                        </button>
                      </div>
                      <p className="help">
                        Or change the item&rsquo;s type back under Identified
                        items, or change this material&rsquo;s type to fit it.
                        Then save.
                      </p>
                    </div>
                  ))}
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
                {samMissed[card.stock.id] && cardPhoto && (
                  <div className="notice sam-missed" role="status">
                    <p>
                      {samMissed[card.stock.id]} Your photo, reference and this
                      material are kept.
                    </p>
                    <div className="button-row">
                      <button
                        type="button"
                        className="secondary"
                        disabled={locked}
                        onClick={() =>
                          setDrawing({ card: card.stock.id, what: "box" })
                        }
                      >
                        Draw a box
                      </button>
                      {fields.length > 0 && (
                        <button
                          type="button"
                          className="secondary"
                          disabled={locked || busy !== ""}
                          onClick={() => void suggestRegion(card)}
                        >
                          {busy === "outline:" + card.stock.id
                            ? "Looking…"
                            : "Suggest an outline"}
                        </button>
                      )}
                    </div>
                    {fields.length > 0 && (
                      <p className="help">
                        A suggestion is found from colour edges on the server,
                        without Muse or SAM. Check it before measuring.
                      </p>
                    )}
                  </div>
                )}
                {fields.length > 0 && cardPhoto && (
                  <div className="button-row">
                    <label className="consent">
                      <input
                        type="checkbox"
                        checked={
                          captureConfirmed[
                            `${card.stock.id}:${cardPhoto.id}`
                          ] ?? false
                        }
                        disabled={locked}
                        onChange={(event) =>
                          setCaptureConfirmed((current) => ({
                            ...current,
                            [`${card.stock.id}:${cardPhoto.id}`]:
                              event.target.checked,
                          }))
                        }
                      />
                      This piece is flat, not folded or stacked, and lies on the
                      same surface as the reference in this photo.
                    </label>
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
                      disabled={
                        locked ||
                        (!card.box && !card.polygon) ||
                        !captureConfirmed[`${card.stock.id}:${cardPhoto.id}`]
                      }
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
                              {d.display_value}{" "}
                              {d.unit === "mm2" ? "mm²" : "mm"} (sensitivity
                              range {Math.round(d.sensitivity_low)}–
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
                          disabled={
                            locked ||
                            !captureConfirmed[
                              `${card.stock.id}:${card.mediaId ?? photoId}`
                            ]
                          }
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
                            Save estimated dimensions
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
                    <p className="help">
                      Estimated dimensions are saved as unconfirmed. Before a
                      buildable design, the app may ask you to measure a size
                      with a ruler.
                    </p>
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
        <IdentifiedItems
          token={token}
          projectId={project.id}
          items={items}
          photos={photos}
          stocks={stocks}
          problems={itemProblems}
          locked={locked || itemsState !== "ready"}
          onChange={changeItem}
          onRemove={(id) =>
            changeItems((current) => current.filter((i) => i.id !== id))
          }
          onUseAsMaterial={useAsMaterial}
        />
        {(cards.length > 0 || items.length > 0 || itemsDirty) && (
          <div className="guided-save">
            <button
              type="button"
              className="quiet"
              disabled={locked}
              onClick={() => addCard([null], photo?.id ?? null)}
            >
              Add another material
            </button>
            <button
              type="button"
              className="primary"
              disabled={locked || inventoryStale || (!dirty && !itemsDirty)}
              onClick={() => {
                if (dirty) {
                  onSave(
                    itemsDirty
                      ? () => setItemsSaveTick((t) => t + 1)
                      : undefined,
                  );
                } else void saveItems();
              }}
            >
              Save materials
            </button>
            <span className="help">
              {dirty || itemsDirty
                ? "Unsaved changes. Unknown sizes stay unknown; photo estimates stay estimates."
                : project.inventory_confirmed
                  ? "Materials saved."
                  : ""}
            </span>
          </div>
        )}
      </details>
      {ready && (
        <section
          className="next-question"
          aria-labelledby="next-question-title"
        >
          <h3 id="next-question-title">Next useful question</h3>
          {(pendingAnswer || pendingUnavailable) && (
            <aside className="retry-panel">
              <p>
                An earlier answer may not have been saved. Retry it exactly
                before answering again.
              </p>
              <button
                type="button"
                className="secondary"
                disabled={locked}
                onClick={() =>
                  pendingAnswer
                    ? void sendAnswer(pendingAnswer)
                    : pendingUnavailable &&
                      void sendUnavailable(pendingUnavailable)
                }
              >
                Retry the earlier answer
              </button>
            </aside>
          )}
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

function problemMap(
  problems: readonly { item_id: string; problem: string }[],
): Record<string, string[]> {
  const map: Record<string, string[]> = {};
  for (const p of problems) (map[p.item_id] ??= []).push(p.problem);
  return map;
}
