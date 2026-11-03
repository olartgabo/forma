import type { StabilityMeasurementRequest } from "../../lib/generated/api-contracts";

// This is a recovery receipt, not a credential or a second evidence database.
// Values remain untrusted until the authenticated API accepts the exact request.
const PREFIX = "forma-stability-pending-v1:";
const MAX_LENGTH = 32768;
const MAX_RECORDS = 32;
const ID = /^[A-Za-z][A-Za-z0-9_-]{0,95}$/;
export type PendingMeasurement = {
  key: string;
  projectId: string;
  payload: StabilityMeasurementRequest;
};

function object(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}
function keys(v: Record<string, unknown>, expected: readonly string[]) {
  return (
    Object.keys(v).length === expected.length &&
    expected.every((k) => Object.hasOwn(v, k))
  );
}
function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}
function positive(v: unknown): v is number {
  return finite(v) && v > 0;
}
function text(v: unknown) {
  return typeof v === "string" && v.trim().length > 0 && v.length <= 2000;
}
function identifier(v: unknown): v is string {
  return typeof v === "string" && ID.test(v);
}
function measuredBody(v: unknown) {
  if (
    !object(v) ||
    !keys(v, [
      "mass_kg",
      "center_of_mass_m",
      "mass_resolution_kg",
      "position_resolution_m",
      "method",
    ]) ||
    !positive(v.mass_kg) ||
    !positive(v.mass_resolution_kg) ||
    v.mass_resolution_kg >= v.mass_kg ||
    !positive(v.position_resolution_m) ||
    !text(v.method)
  )
    return false;
  const c = v.center_of_mass_m;
  return (
    object(c) &&
    keys(c, ["x", "y", "z"]) &&
    finite(c.x) &&
    finite(c.y) &&
    finite(c.z) &&
    c.z >= 0
  );
}
const flags = [
  "stand_includes_all_parts_and_connectors",
  "actual_contacts_confirmed",
  "rigid_assembly_assumed",
  "horizontal_surface_confirmed",
  "stationary_device_assumed",
  "gravity_only_assumed",
] as const;
export function validPendingPayload(
  v: unknown,
): v is StabilityMeasurementRequest {
  if (
    !object(v) ||
    !keys(v, [
      "plan_version_id",
      "expected_inventory_revision_id",
      "expected_last_event_id",
      "idempotency_key",
      "user_confirmed",
      "measurements",
    ]) ||
    !identifier(v.plan_version_id) ||
    !identifier(v.expected_inventory_revision_id) ||
    !(
      v.expected_last_event_id === null || identifier(v.expected_last_event_id)
    ) ||
    typeof v.idempotency_key !== "string" ||
    v.idempotency_key.length < 8 ||
    v.idempotency_key.length > 128 ||
    v.user_confirmed !== true
  )
    return false;
  const m = v.measurements;
  if (
    !object(m) ||
    !keys(m, ["stand", "cases", "support", "required_margin_m", ...flags]) ||
    !flags.every((k) => m[k] === true) ||
    !measuredBody(m.stand) ||
    !finite(m.required_margin_m) ||
    m.required_margin_m < 0 ||
    !Array.isArray(m.cases) ||
    m.cases.length !== 2
  )
    return false;
  const orientations = new Set<string>();
  for (const c of m.cases) {
    if (
      !object(c) ||
      !keys(c, ["orientation", "device", "pose_description"]) ||
      (c.orientation !== "portrait" && c.orientation !== "landscape") ||
      !measuredBody(c.device) ||
      !text(c.pose_description)
    )
      return false;
    orientations.add(c.orientation);
  }
  const s = m.support;
  return (
    orientations.size === 2 &&
    object(s) &&
    keys(s, [
      "x_min_m",
      "x_max_m",
      "y_min_m",
      "y_max_m",
      "resolution_m",
      "method",
    ]) &&
    finite(s.x_min_m) &&
    finite(s.x_max_m) &&
    finite(s.y_min_m) &&
    finite(s.y_max_m) &&
    s.x_min_m < s.x_max_m &&
    s.y_min_m < s.y_max_m &&
    positive(s.resolution_m) &&
    s.resolution_m < Math.min(s.x_max_m - s.x_min_m, s.y_max_m - s.y_min_m) &&
    text(s.method)
  );
}
async function scope(token: string, projectId: string) {
  if (!token || !identifier(projectId))
    throw new Error("Reconnect before recovering measurement saves.");
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
    projectId +
    ":"
  );
}
function recordKey(prefix: string, payload: StabilityMeasurementRequest) {
  return (
    prefix +
    payload.plan_version_id +
    ":" +
    encodeURIComponent(payload.idempotency_key)
  );
}
function readRecords(
  prefix: string,
  projectId: string,
  storage: Storage,
): PendingMeasurement[] {
  if (storage.length > 10000)
    throw new Error(
      "Browser recovery storage is too large to verify. No measurement request was sent.",
    );
  const records: PendingMeasurement[] = [];
  for (let index = 0; index < storage.length; index++) {
    const key = storage.key(index);
    if (!key?.startsWith(prefix)) continue;
    const raw = storage.getItem(key);
    if (!raw || raw.length > MAX_LENGTH)
      throw new Error(
        "A locally retained measurement save cannot be verified. New saves are blocked until recovery storage is repaired.",
      );
    let record: unknown;
    try {
      record = JSON.parse(raw);
    } catch {
      throw new Error(
        "A locally retained measurement save is unreadable. New saves are blocked until recovery storage is repaired.",
      );
    }
    if (
      !object(record) ||
      !keys(record, ["version", "project_id", "payload"]) ||
      record.version !== 1 ||
      record.project_id !== projectId ||
      !validPendingPayload(record.payload) ||
      key !== recordKey(prefix, record.payload)
    )
      throw new Error(
        "A locally retained measurement save has invalid identity or values. No request will be replayed.",
      );
    records.push({ key, projectId, payload: record.payload });
    if (records.length > MAX_RECORDS)
      throw new Error(
        "Too many unresolved measurement saves. New saves are blocked until recovery storage is repaired.",
      );
  }
  return records.sort((a, b) => a.key.localeCompare(b.key));
}
export async function pendingMeasurements(
  token: string,
  projectId: string,
  storage?: Storage,
): Promise<PendingMeasurement[]> {
  try {
    return readRecords(
      await scope(token, projectId),
      projectId,
      storage ?? window.localStorage,
    );
  } catch (e) {
    throw new Error(
      e instanceof Error
        ? e.message
        : "Browser recovery storage is unavailable. Measurement saving is blocked.",
    );
  }
}
export async function retainMeasurement(
  token: string,
  projectId: string,
  payload: StabilityMeasurementRequest,
  storage?: Storage,
): Promise<PendingMeasurement> {
  if (!validPendingPayload(payload))
    throw new Error(
      "The measurement request cannot be safely retained. Check its values before saving.",
    );
  const prefix = await scope(token, projectId);
  const target = storage ?? window.localStorage;
  const key = recordKey(prefix, payload);
  const current = readRecords(prefix, projectId, target);
  const prior = current.find((r) => r.key === key);
  if (prior) {
    if (JSON.stringify(prior.payload) !== JSON.stringify(payload))
      throw new Error(
        "An unresolved measurement save already uses this key. Recover it before editing.",
      );
    return prior;
  }
  if (current.length)
    throw new Error(
      "Another measurement save remains unresolved. Recover it before starting a new save.",
    );
  const serialized = JSON.stringify({
    version: 1,
    project_id: projectId,
    payload,
  });
  if (serialized.length > MAX_LENGTH)
    throw new Error("The measurement save exceeds the browser recovery limit.");
  target.setItem(key, serialized);
  if (target.getItem(key) !== serialized)
    throw new Error(
      "Browser recovery storage did not retain the request. No measurement request was sent.",
    );
  return { key, projectId, payload };
}
export async function clearMeasurement(
  token: string,
  record: PendingMeasurement,
  storage?: Storage,
): Promise<void> {
  const target = storage ?? window.localStorage;
  const current = readRecords(
    await scope(token, record.projectId),
    record.projectId,
    target,
  );
  const saved = current.find((r) => r.key === record.key);
  if (
    !saved ||
    JSON.stringify(saved.payload) !== JSON.stringify(record.payload)
  )
    throw new Error(
      "The local recovery receipt changed. Resolve it before making another save.",
    );
  target.removeItem(record.key);
  if (target.getItem(record.key) !== null)
    throw new Error(
      "The save was resolved, but its local recovery receipt could not be cleared. Retry recovery before editing.",
    );
}
