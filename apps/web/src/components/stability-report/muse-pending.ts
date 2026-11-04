import type { StabilityMuseRequest } from "../../lib/generated/api-contracts";

// A recovery receipt for one sent MetaMuse request, not a credential. A retry
// resends this exact body and key so a completed request replays instead of
// dispatching to the provider again.
const PREFIX = "forma-stability-muse-pending-v1:";
const MAX_LENGTH = 8192;
const ID = /^[A-Za-z][A-Za-z0-9_-]{0,95}$/;
const FIELDS = [
  "plan_version_id",
  "expected_inventory_revision_id",
  "expected_last_event_id",
  "idempotency_key",
  "mode",
  "report_id",
  "question",
  "provider_context_consented",
];

function object(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}
function id(v: unknown) {
  return typeof v === "string" && ID.test(v);
}
export function validMuseRequest(v: unknown): v is StabilityMuseRequest {
  return (
    object(v) &&
    Object.keys(v).length === FIELDS.length &&
    FIELDS.every((k) => Object.hasOwn(v, k)) &&
    id(v.plan_version_id) &&
    id(v.expected_inventory_revision_id) &&
    (v.expected_last_event_id === null || id(v.expected_last_event_id)) &&
    typeof v.idempotency_key === "string" &&
    v.idempotency_key.length >= 8 &&
    v.idempotency_key.length <= 128 &&
    ((v.mode === "analyze_current" && v.report_id === null) ||
      (v.mode === "explain_report" && id(v.report_id))) &&
    (v.question === null ||
      (typeof v.question === "string" &&
        v.question.length >= 1 &&
        v.question.length <= 500)) &&
    v.provider_context_consented === true
  );
}
async function storageKey(token: string, projectId: string) {
  if (!token || !id(projectId))
    throw new Error("Reconnect before asking MetaMuse.");
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(token),
  );
  const owner = Array.from(new Uint8Array(digest), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
  return `${PREFIX}${owner}:${projectId}`;
}
function read(key: string, projectId: string, storage: Storage) {
  const raw = storage.getItem(key);
  if (raw === null) return null;
  let record: unknown = null;
  try {
    record = raw.length <= MAX_LENGTH ? JSON.parse(raw) : null;
  } catch {
    record = null;
  }
  if (
    !object(record) ||
    record.version !== 1 ||
    record.project_id !== projectId ||
    !validMuseRequest(record.body)
  )
    throw new Error(
      "A retained MetaMuse request cannot be verified. Nothing will be sent until it is cleared.",
    );
  return record.body;
}

export async function pendingMuse(
  token: string,
  projectId: string,
  storage: Storage = window.localStorage,
): Promise<StabilityMuseRequest | null> {
  return read(await storageKey(token, projectId), projectId, storage);
}

export async function retainMuse(
  token: string,
  projectId: string,
  body: StabilityMuseRequest,
  storage: Storage = window.localStorage,
) {
  if (!validMuseRequest(body))
    throw new Error("The MetaMuse request cannot be safely retained.");
  const key = await storageKey(token, projectId);
  const prior = read(key, projectId, storage);
  if (prior && JSON.stringify(prior) !== JSON.stringify(body))
    throw new Error(
      "Another MetaMuse request is unresolved. Retry it before asking again.",
    );
  const serialized = JSON.stringify({
    version: 1,
    project_id: projectId,
    body,
  });
  storage.setItem(key, serialized);
  if (storage.getItem(key) !== serialized)
    throw new Error(
      "The browser could not retain the request, so it was not sent.",
    );
}

export async function clearMuse(
  token: string,
  projectId: string,
  body: StabilityMuseRequest,
  storage: Storage = window.localStorage,
) {
  const key = await storageKey(token, projectId);
  const prior = read(key, projectId, storage);
  if (prior && JSON.stringify(prior) === JSON.stringify(body))
    storage.removeItem(key);
}

/** Forget a receipt that cannot be verified; it is never sent. */
export async function discardMuse(
  token: string,
  projectId: string,
  storage: Storage = window.localStorage,
) {
  storage.removeItem(await storageKey(token, projectId));
}
