// Photo estimate client (#177). Local server computation; no provider call.
import type {
  PhotoEstimateList,
  PhotoEstimateRecord,
  PhotoEstimateRequest,
} from "./generated/api-contracts";

export class EstimateRequestError extends Error {
  readonly status: number;
  // True when the request may have completed; retry the exact same body.
  readonly retryExact: boolean;
  constructor(message: string, status: number, retryExact: boolean) {
    super(message);
    this.status = status;
    this.retryExact = retryExact;
  }
}

const ID = /^[A-Za-z][A-Za-z0-9_-]{0,95}$/;
const OUTCOMES = new Set([
  "estimate",
  "enclosing_only",
  "needs_better_photo",
  "needs_manual_measurement",
  "unsupported_shape",
  "reference_not_found",
  "reference_unverified",
]);

function object(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

export function validRecord(
  value: unknown,
  projectId: string,
): value is PhotoEstimateRecord {
  if (!object(value) || !object(value.estimate)) return false;
  const e = value.estimate;
  const dims = Array.isArray(e.dimensions) ? e.dimensions : [];
  return (
    typeof value.estimate_id === "string" &&
    ID.test(value.estimate_id) &&
    value.project_id === projectId &&
    (value.status === "current" || value.status === "stale") &&
    Array.isArray(value.stale_reasons ?? []) &&
    typeof e.outcome === "string" &&
    OUTCOMES.has(e.outcome) &&
    e.measurement_status === "photo_estimate_unconfirmed" &&
    object(e.input) &&
    typeof e.input.stock_id === "string" &&
    typeof e.input.media_id === "string" &&
    dims.every(
      (d) =>
        object(d) &&
        Number.isFinite(d.value) &&
        Number.isFinite(d.display_value) &&
        Number.isFinite(d.display_step) &&
        (d.display_step as number) > 0 &&
        Number.isFinite(d.sensitivity_low) &&
        Number.isFinite(d.sensitivity_high),
    ) &&
    // Only full estimates may fill a stock size.
    (e.outcome === "estimate" ||
      dims.every((d) => object(d) && d.stock_field == null))
  );
}

async function send(
  token: string,
  path: string,
  init: RequestInit,
  signal?: AbortSignal,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      signal,
      cache: "no-store",
      credentials: "omit",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    });
  } catch {
    throw new EstimateRequestError(
      signal?.aborted
        ? "Measurement stopped before an answer arrived."
        : "The connection failed before an answer arrived. Try again.",
      0,
      true,
    );
  }
  const body = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const message =
      object(body) && typeof body.message === "string"
        ? body.message
        : "Photo measurement is unavailable right now.";
    const retryExact = response.status >= 500 || response.status === 429;
    throw new EstimateRequestError(message, response.status, retryExact);
  }
  if (body === null)
    throw new EstimateRequestError(
      "The answer was cut off. Try the same measurement again.",
      0,
      true,
    );
  return body;
}

export function photoEstimates(token: string, projectId: string) {
  const root = `/api/projects/${encodeURIComponent(projectId)}/photo-estimates`;
  return {
    async create(
      body: PhotoEstimateRequest,
      signal?: AbortSignal,
    ): Promise<PhotoEstimateRecord> {
      const value = await send(
        token,
        root,
        { method: "POST", body: JSON.stringify(body) },
        signal,
      );
      if (!validRecord(value, projectId))
        throw new EstimateRequestError(
          "The measurement answer was not valid. Try the same measurement again.",
          0,
          true,
        );
      return value;
    },
    async list(signal?: AbortSignal): Promise<PhotoEstimateRecord[]> {
      const value = (await send(token, root, { method: "GET" }, signal)) as
        PhotoEstimateList | unknown;
      if (
        !object(value) ||
        !Array.isArray(value.records) ||
        !value.records.every((r) => validRecord(r, projectId))
      )
        throw new EstimateRequestError(
          "Saved photo estimates could not be read.",
          0,
          true,
        );
      return [...(value.records as PhotoEstimateRecord[])];
    },
  };
}

export const REFERENCE_CARD_URL = "/api/photo-reference-card.svg";
