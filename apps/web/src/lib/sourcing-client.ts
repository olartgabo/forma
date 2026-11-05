// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { modelKeyHeaders } from "./developer-settings.ts";
import type {
  ResearchRequest,
  ResearchRun,
  SourcingNeeds,
  LocationSearchResponse,
  NearbyResponse,
  NearbyRequest,
  ConfirmedLocation,
} from "./generated/api-contracts";

export class SourcingError extends Error {
  readonly code: string;
  readonly uncertain: boolean;
  constructor(code: string, uncertain = false) {
    super(
      code === "source_unavailable"
        ? "Supplier research is not available yet. You can still open Marketplace yourself."
        : code === "location_consent_required"
          ? "Allow map lookup before sharing a search area."
          : code === "location_unavailable" || code === "nearby_unavailable"
            ? "Map lookup is unavailable. Try another city or try again later."
            : code === "authorization_required"
              ? "Marketplace research needs Meta authorization."
              : code === "conflict"
                ? "This project changed. Reload its needs before researching."
                : "Research could not be confirmed. Check its status before trying again.",
    );
    this.code = code;
    this.uncertain = uncertain;
  }
}
const record = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null;
const text = (v: unknown): v is string =>
  typeof v === "string" && v.length <= 4000;
export function safeSupplierUrl(value: unknown): value is string {
  if (!text(value)) return false;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase().replace(/\.$/, "");
    return (
      url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      !url.port &&
      !host.endsWith(".localhost") &&
      host !== "localhost" &&
      !host.endsWith(".local") &&
      !host.endsWith(".internal") &&
      host.includes(".") &&
      !/^\d+\.\d+\.\d+\.\d+$/.test(host) &&
      !host.includes(":") &&
      !["facebook.com", "fb.com", "fb.me", "meta.ai"].some(
        (h) => host === h || host.endsWith(`.${h}`),
      )
    );
  } catch {
    return false;
  }
}
async function request(
  token: string,
  path: string,
  signal: AbortSignal,
  body?: object,
  uncertainPost = !!body,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? modelKeyHeaders() : {}),
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
      signal,
      cache: "no-store",
      redirect: "error",
      credentials: "omit",
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new SourcingError("network_error", uncertainPost);
  }
  if (!response.ok) {
    let value: unknown;
    try {
      value = await response.json();
    } catch {
      value = null;
    }
    const code =
      record(value) && text(value.code) ? value.code : "request_failed";
    throw new SourcingError(
      response.status === 409 && code !== "outcome_unknown" ? "conflict" : code,
      code === "outcome_unknown" ||
        (uncertainPost &&
          response.status >= 500 &&
          code !== "source_unavailable"),
    );
  }
  try {
    return await response.json();
  } catch {
    throw new SourcingError("invalid_response", uncertainPost);
  }
}
const base = (project: string) =>
  `/api/projects/${encodeURIComponent(project)}/sourcing`;
const finite = (value: unknown, min: number, max: number) =>
  typeof value === "number" &&
  Number.isFinite(value) &&
  value >= min &&
  value <= max;
const coordinates = (value: Record<string, unknown>) =>
  finite(value.latitude, -90, 90) && finite(value.longitude, -180, 180);
const categories = ["hardware", "stationery", "doityourself", "craft"];
function nearbyPlaces(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length <= 10 &&
    value.every((place) => {
      if (!record(place)) return false;
      return (
        text(place.id) &&
        text(place.name) &&
        coordinates(place) &&
        finite(place.distance_m, 0, 100000) &&
        (place.distance_min_m === null ||
          finite(place.distance_min_m, 0, 200000)) &&
        (place.distance_max_m === null ||
          finite(place.distance_max_m, 0, 200000)) &&
        ((place.distance_min_m === null && place.distance_max_m === null) ||
          (typeof place.distance_min_m === "number" &&
            typeof place.distance_max_m === "number" &&
            place.distance_min_m <= Number(place.distance_m) &&
            place.distance_max_m >= Number(place.distance_m))) &&
        text(place.address) &&
        (place.website === null || safeSupplierUrl(place.website)) &&
        typeof place.osm_url === "string" &&
        /^https:\/\/www\.openstreetmap\.org\/(node|way|relation)\/\d+$/.test(
          place.osm_url,
        ) &&
        categories.includes(String(place.category))
      );
    })
  );
}
export async function resolveSourcingLocation(
  token: string,
  project: string,
  city: string,
  transferConsented: boolean,
  signal: AbortSignal,
): Promise<LocationSearchResponse> {
  if (!transferConsented) throw new SourcingError("location_consent_required");
  const value = await request(
    token,
    `${base(project)}/locations`,
    signal,
    { city, transfer_consented: true },
    false,
  );
  if (
    !record(value) ||
    !text(value.attribution) ||
    !Array.isArray(value.choices) ||
    value.choices.length > 3 ||
    !value.choices.every(
      (choice) =>
        record(choice) &&
        text(choice.id) &&
        text(choice.label) &&
        coordinates(choice) &&
        choice.location_basis === "city_center" &&
        choice.accuracy_m === null &&
        (choice.country_code == null ||
          (typeof choice.country_code === "string" &&
            /^[A-Z]{2}$/i.test(choice.country_code))),
    )
  )
    throw new SourcingError("invalid_response");
  return value as LocationSearchResponse;
}
export async function discoverNearby(
  token: string,
  project: string,
  body: NearbyRequest,
  signal: AbortSignal,
): Promise<NearbyResponse> {
  const value = await request(
    token,
    `${base(project)}/nearby`,
    signal,
    body,
    false,
  );
  if (
    !record(value) ||
    !nearbyPlaces(value.places) ||
    !["found", "empty"].includes(String(value.status)) ||
    !text(value.attribution) ||
    !text(value.message)
  )
    throw new SourcingError("invalid_response");
  return value as NearbyResponse;
}
export async function reverseSourcingLocation(
  token: string,
  project: string,
  location: ConfirmedLocation,
  signal: AbortSignal,
): Promise<{
  location: ConfirmedLocation;
  suggested_currency: string | null;
  attribution: string;
}> {
  if (!location.confirmed || !location.transfer_consented)
    throw new SourcingError("location_consent_required");
  const value = await request(
    token,
    `${base(project)}/reverse`,
    signal,
    { location },
    false,
  );
  const resolved =
    record(value) && record(value.location) ? value.location : null;
  if (
    !record(value) ||
    !resolved ||
    !text(value.attribution) ||
    !(
      value.suggested_currency === null ||
      /^[A-Z]{3}$/.test(String(value.suggested_currency))
    ) ||
    !text(resolved.label) ||
    resolved.confirmed !== true ||
    resolved.transfer_consented !== true ||
    !["country_code", "city", "region"].every(
      (key) => resolved[key] == null || text(resolved[key]),
    ) ||
    !["latitude", "longitude", "accuracy_m", "location_basis"].every(
      (key) => resolved[key] === location[key as keyof ConfirmedLocation],
    )
  )
    throw new SourcingError("invalid_response");
  return value as {
    location: ConfirmedLocation;
    suggested_currency: string | null;
    attribution: string;
  };
}

// Poll only an already dispatched run. Never regenerate on delay, failure or unknown outcome.
export async function pollResearch(
  token: string,
  project: string,
  initial: ResearchRun,
  signal: AbortSignal,
  onUpdate: (run: ResearchRun) => void,
  pause: (signal: AbortSignal) => Promise<void> = (signal) =>
    new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        signal.removeEventListener("abort", abort);
        resolve();
      }, 4000);
      function abort() {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      }
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, { once: true });
    }),
): Promise<ResearchRun> {
  let run = initial;
  for (let count = 0; run.status === "running" && count < 24; count++) {
    await pause(signal);
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    run = await reconcileResearch(
      token,
      project,
      run.revision_id,
      run.id,
      signal,
    );
    onUpdate(run);
  }
  return run;
}
export async function loadSourcingNeeds(
  token: string,
  project: string,
  signal: AbortSignal,
): Promise<SourcingNeeds> {
  const value = await request(token, `${base(project)}/needs`, signal);
  if (
    !record(value) ||
    value.project_id !== project ||
    !text(value.revision_id) ||
    !(value.active_version_id === null || text(value.active_version_id)) ||
    value.marketplace_status !== "authorization_required" ||
    !Array.isArray(value.needs) ||
    value.needs.length > 64 ||
    !value.needs.every(
      (n) =>
        record(n) &&
        text(n.id) &&
        text(n.label) &&
        ["material", "tool"].includes(String(n.kind)) &&
        n.origin === "engine" &&
        text(n.reason),
    ) ||
    !Array.isArray(value.guidance) ||
    !value.guidance.every(text) ||
    !(value.pending_run_id == null || text(value.pending_run_id))
  )
    throw new SourcingError("invalid_response");
  return value as SourcingNeeds;
}
export function validateResearchRun(
  value: unknown,
  project: string,
  revision: string,
): ResearchRun {
  if (
    !record(value) ||
    value.project_id !== project ||
    value.revision_id !== revision ||
    !text(value.item) ||
    !text(value.area) ||
    !/^[A-Z]{3}$/.test(String(value.currency)) ||
    !text(value.id) ||
    ![
      "running",
      "succeeded",
      "no_verified_results",
      "failed",
      "outcome_unknown",
    ].includes(String(value.status)) ||
    !text(value.observed_at) ||
    !Number.isFinite(Date.parse(value.observed_at)) ||
    !(value.error === null || text(value.error)) ||
    typeof value.replayed !== "boolean" ||
    !Array.isArray(value.offers) ||
    (value.nearby_places !== undefined && !nearbyPlaces(value.nearby_places)) ||
    !(value.discovery_message == null || text(value.discovery_message)) ||
    value.offers.length > 5 ||
    !value.offers.every(
      (o) =>
        record(o) &&
        text(o.title) &&
        safeSupplierUrl(o.url) &&
        /^[A-Z]{3}$/.test(String(o.currency)) &&
        [
          "listed",
          "listed_free",
          "price_unknown",
          "price_conflict",
          "partial_price",
        ].includes(String(o.price_status)) &&
        (o.price === null ||
          (typeof o.price === "string" && /^\d+(\.\d+)?$/.test(o.price))) &&
        text(o.availability) &&
        text(o.location) &&
        text(o.notes),
    )
  )
    throw new SourcingError("invalid_response", true);
  if (
    value.offers.some(
      (o) =>
        record(o) &&
        ["price_unknown", "price_conflict", "partial_price"].includes(
          String(o.price_status),
        ) &&
        o.price !== null,
    )
  )
    throw new SourcingError("invalid_response", true);
  return value as ResearchRun;
}
export async function researchSuppliers(
  token: string,
  project: string,
  body: ResearchRequest,
  signal: AbortSignal,
): Promise<ResearchRun> {
  const result = validateResearchRun(
    await request(token, `${base(project)}/research`, signal, body),
    project,
    body.expected_revision_id,
  );
  if (
    result.item !== body.item ||
    result.area !== body.area ||
    result.currency !== body.currency
  )
    throw new SourcingError("invalid_response", true);
  return result;
}
export async function reconcileResearch(
  token: string,
  project: string,
  revision: string | null,
  id: string,
  signal: AbortSignal,
): Promise<ResearchRun> {
  const raw = await request(
    token,
    `${base(project)}/research/${encodeURIComponent(id)}`,
    signal,
  );
  const value = validateResearchRun(
    raw,
    project,
    revision ?? (record(raw) && text(raw.revision_id) ? raw.revision_id : ""),
  );
  if (value.id !== id) throw new SourcingError("invalid_response", true);
  return value;
}
