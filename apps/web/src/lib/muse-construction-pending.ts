import type {
  Media,
  MuseConstructionRequest,
  Project,
} from "./generated/api-contracts";

const PREFIX = "forma-construction-pending-v1:";
const ID = /^[A-Za-z][A-Za-z0-9_-]{0,95}$/;
type PhotoIdentity = Pick<Media, "id" | "byte_count" | "content_type">;
export type PendingConstruction = {
  version: 1;
  project_id: string;
  goal: string;
  photo: PhotoIdentity | null;
  payload: MuseConstructionRequest;
};

export function constructionRequestCanRestart(code: string | undefined) {
  // These route errors either precede dispatch or clear the server receipt.
  // Stale/context conflicts and unreadable responses do not resolve paid work.
  return [
    "validation_error",
    "consent_required",
    "provider_not_configured",
    "provider_authentication",
    "access_denied",
    "rate_limit",
    "proposal_rejected",
  ].includes(code ?? "");
}

function object(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}
function keys(v: Record<string, unknown>, expected: string[]) {
  return (
    Object.keys(v).length === expected.length &&
    expected.every((key) => Object.hasOwn(v, key))
  );
}
function identifier(v: unknown): v is string {
  return typeof v === "string" && ID.test(v);
}
export function validPendingConstruction(v: unknown): v is PendingConstruction {
  if (
    !object(v) ||
    !keys(v, ["version", "project_id", "goal", "photo", "payload"]) ||
    v.version !== 1 ||
    !identifier(v.project_id) ||
    typeof v.goal !== "string" ||
    !v.goal.length ||
    v.goal.length > 2000 ||
    !object(v.payload)
  )
    return false;
  const p = v.payload;
  if (
    !keys(p, [
      ...(Object.hasOwn(p, "approximate") ? ["approximate"] : []),
      "expected_revision_id",
      "user_notes",
      "media_id",
      "provider_context_consented",
      "provider_transfer_consented",
      "idempotency_key",
    ]) ||
    (Object.hasOwn(p, "approximate") && p.approximate !== true) ||
    (p.approximate === true && p.media_id === null) ||
    !identifier(p.expected_revision_id) ||
    !(
      p.user_notes === null ||
      (typeof p.user_notes === "string" && p.user_notes.length <= 1000)
    ) ||
    !(p.media_id === null || identifier(p.media_id)) ||
    p.provider_context_consented !== true ||
    p.provider_transfer_consented !== (p.media_id !== null) ||
    typeof p.idempotency_key !== "string" ||
    p.idempotency_key.length < 8 ||
    p.idempotency_key.length > 128
  )
    return false;
  if (p.media_id === null) return v.photo === null;
  return (
    object(v.photo) &&
    keys(v.photo, ["id", "byte_count", "content_type"]) &&
    v.photo.id === p.media_id &&
    typeof v.photo.byte_count === "number" &&
    Number.isInteger(v.photo.byte_count) &&
    v.photo.byte_count > 0 &&
    v.photo.byte_count <= 5_000_000 &&
    (v.photo.content_type === "image/jpeg" ||
      v.photo.content_type === "image/png")
  );
}
async function scope(token: string, projectId: string) {
  if (!token || !identifier(projectId))
    throw new Error("Reconnect before recovering proposal requests.");
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(token),
  );
  return (
    PREFIX +
    Array.from(new Uint8Array(digest), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join("") +
    ":" +
    projectId
  );
}
function read(
  key: string,
  projectId: string,
  storage: Storage,
): PendingConstruction | null {
  const raw = storage.getItem(key);
  if (raw === null) return null;
  let value: unknown;
  try {
    if (raw.length > 32768) throw new Error();
    value = JSON.parse(raw);
  } catch {
    throw new Error(
      "The retained proposal request cannot be verified. New requests are blocked until browser recovery storage is repaired.",
    );
  }
  if (!validPendingConstruction(value) || value.project_id !== projectId)
    throw new Error(
      "The retained proposal request has invalid identity or values. No request will be replayed.",
    );
  return value;
}
export async function pendingConstruction(
  token: string,
  projectId: string,
  storage?: Storage,
) {
  return read(
    await scope(token, projectId),
    projectId,
    storage ?? window.localStorage,
  );
}
export async function retainConstruction(
  token: string,
  record: PendingConstruction,
  storage?: Storage,
) {
  if (!validPendingConstruction(record))
    throw new Error(
      "The proposal request cannot be safely retained. No request was sent.",
    );
  const key = await scope(token, record.project_id);
  const target = storage ?? window.localStorage;
  const prior = read(key, record.project_id, target);
  if (prior) {
    if (JSON.stringify(prior) !== JSON.stringify(record))
      throw new Error(
        "Another proposal request remains unresolved. Recover it before starting a new request.",
      );
    return prior;
  }
  const serialized = JSON.stringify(record);
  target.setItem(key, serialized);
  if (target.getItem(key) !== serialized)
    throw new Error(
      "Browser recovery storage did not retain the proposal request. No request was sent.",
    );
  return record;
}
export async function clearConstruction(
  token: string,
  record: PendingConstruction,
  storage?: Storage,
) {
  const key = await scope(token, record.project_id);
  const target = storage ?? window.localStorage;
  if (
    JSON.stringify(read(key, record.project_id, target)) !==
    JSON.stringify(record)
  )
    throw new Error(
      "The local proposal receipt changed. Resolve it before making another request.",
    );
  target.removeItem(key);
  if (target.getItem(key) !== null)
    throw new Error(
      "The proposal returned, but its recovery receipt could not be cleared. Check the original request before generating another.",
    );
}
export function constructionContextChanged(
  record: PendingConstruction,
  project: Pick<Project, "id" | "revision_id" | "goal">,
  photos: Media[],
) {
  const selected = photos.find((p) => p.id === record.payload.media_id);
  return (
    record.project_id !== project.id ||
    record.payload.expected_revision_id !== project.revision_id ||
    record.goal !== project.goal ||
    (!!record.photo &&
      (!selected ||
        selected.byte_count !== record.photo.byte_count ||
        selected.content_type !== record.photo.content_type))
  );
}
