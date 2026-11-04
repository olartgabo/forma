export class LocalizationError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}
// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { receipts } from "../components/design-candidates/pending.ts";
import type {
  Box,
  Media,
  PhotoLocalizationRequest,
  PhotoLocalizationResult,
} from "./generated/api-contracts";

export function validPhotoBox(
  value: unknown,
  photo: Media,
  concept?: string,
): value is Box {
  if (!value || typeof value !== "object") return false;
  const b = value as Box;
  return (
    typeof b.label === "string" &&
    b.label.trim().length > 0 &&
    b.label.length <= 120 &&
    (concept === undefined || b.label === concept) &&
    (b.source === "sam" || b.source === "manual") &&
    [b.x1, b.x2, b.y1, b.y2, b.width, b.height].every(Number.isInteger) &&
    b.width === photo.width_px &&
    b.height === photo.height_px &&
    b.x1 >= 0 &&
    b.y1 >= 0 &&
    b.x2 >= b.x1 &&
    b.y2 >= b.y1 &&
    b.x2 < b.width &&
    b.y2 < b.height
  );
}

export async function localizePhoto(
  token: string,
  projectId: string,
  photo: Media | undefined,
  body: PhotoLocalizationRequest,
): Promise<PhotoLocalizationResult> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/photo-localizations`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    },
  );
  let value: PhotoLocalizationResult & { code?: string; message?: string };
  try {
    value = await response.json();
  } catch {
    throw new LocalizationError(
      0,
      "unknown",
      "SAM response could not be read. Keep this exact request and check its receipt.",
    );
  }
  if (!response.ok)
    throw new LocalizationError(
      response.status,
      value.code || "unknown",
      value.message ||
        "SAM outcome is unknown. Check this exact request again.",
    );
  if (
    value.project_id !== projectId ||
    value.revision_id !== body.expected_revision_id ||
    value.media_id !== body.media_id ||
    !photo ||
    value.width_px !== photo.width_px ||
    value.height_px !== photo.height_px ||
    value.physical_status !== "unverified_photo_annotation" ||
    typeof value.replayed !== "boolean" ||
    typeof value.model !== "string" ||
    !value.model.trim() ||
    !Array.isArray(value.boxes) ||
    value.boxes.length > 32 ||
    !value.boxes.every(
      (b) =>
        !!photo && validPhotoBox(b, photo, body.concept) && b.source === "sam",
    ) ||
    !value.usage ||
    !Number.isInteger(value.usage.model_calls) ||
    value.usage.model_calls < 0 ||
    value.usage.model_calls > 16
  )
    throw new LocalizationError(
      0,
      "unknown",
      "SAM returned an invalid photo reference. Keep this exact request and check its receipt.",
    );
  return value;
}

export function validLocalizationRequest(
  value: unknown,
): value is PhotoLocalizationRequest {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  const fields = [
    "media_id",
    "expected_revision_id",
    "idempotency_key",
    "concept",
    "provider_transfer_consented",
  ];
  const id = (x: unknown) =>
    typeof x === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,95}$/.test(x);
  return (
    Object.keys(v).length === fields.length &&
    fields.every((k) => Object.hasOwn(v, k)) &&
    id(v.media_id) &&
    id(v.expected_revision_id) &&
    typeof v.idempotency_key === "string" &&
    v.idempotency_key.length >= 8 &&
    v.idempotency_key.length <= 128 &&
    v.provider_transfer_consented === true &&
    typeof v.concept === "string" &&
    /^[\p{L}\p{N}_ -]{1,80}$/u.test(v.concept) &&
    !!v.concept.trim() &&
    !v.concept.toLowerCase().includes(" and ")
  );
}

// One retained SAM request per owner and project, shared by every SAM caller.
export const localizationReceipts = receipts<PhotoLocalizationRequest>(
  "forma-photo-localization-v1:",
  validLocalizationRequest,
  "SAM request",
);

export type OutlineSuggestionResult = {
  status:
    | "suggested"
    | "reference_not_found"
    | "nothing_found"
    | "only_reference"
    | "only_cut_off"
    | "outline_not_confirmed"
    | "unsupported_shape";
  box: { x1: number; y1: number; x2: number; y2: number } | null;
  message: string;
};

/** Local, deterministic region suggestion for when SAM finds nothing. No
 * provider call and nothing is saved; the result is only a box to check. */
export async function suggestOutline(
  token: string,
  projectId: string,
  photo: Media,
  body: {
    media_id: string;
    expected_revision_id: string;
    stock_kind: "sheet" | "strip" | "tape" | "cord";
    reference: unknown;
  },
): Promise<OutlineSuggestionResult> {
  let response: Response;
  try {
    response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/photo-outline-suggestions`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        cache: "no-store",
      },
    );
  } catch {
    throw new Error("FORMA could not be reached. Draw a box instead.");
  }
  const value = (await response.json().catch(() => null)) as
    | (OutlineSuggestionResult & {
        project_id?: string;
        media_id?: string;
        revision_id?: string;
        message?: string;
      })
    | null;
  if (!response.ok || !value)
    throw new Error(
      response.status === 409
        ? "Materials changed in another session. Reload before trying again."
        : "No outline could be suggested. Draw a box instead.",
    );
  const box = value.box;
  if (
    value.project_id !== projectId ||
    value.media_id !== body.media_id ||
    value.revision_id !== body.expected_revision_id ||
    typeof value.message !== "string" ||
    (value.status === "suggested") !== !!box ||
    (box &&
      !(
        Number.isInteger(box.x1) &&
        Number.isInteger(box.y1) &&
        Number.isInteger(box.x2) &&
        Number.isInteger(box.y2) &&
        0 <= box.x1 &&
        box.x1 < box.x2 &&
        box.x2 < photo.width_px &&
        0 <= box.y1 &&
        box.y1 < box.y2 &&
        box.y2 < photo.height_px
      ))
  )
    throw new Error("No outline could be suggested. Draw a box instead.");
  return {
    status: value.status,
    box: box ? { x1: box.x1, y1: box.y1, x2: box.x2, y2: box.y2 } : null,
    message: value.message,
  };
}
