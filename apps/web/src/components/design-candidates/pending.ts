// Recovery receipts for sent requests, not credentials. A retry resends the
// exact body and key so a completed request replays on the server instead of
// saving a second preview or dispatching MetaMuse again. Scoped to a SHA-256
// digest of the owner credential and the project.
const MAX_LENGTH = 262144;
const ID = /^[A-Za-z][A-Za-z0-9_-]{0,95}$/;

function object(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

export type Receipts<T> = {
  pending(
    token: string,
    projectId: string,
    storage?: Storage,
  ): Promise<T | null>;
  retain(
    token: string,
    projectId: string,
    body: T,
    storage?: Storage,
  ): Promise<void>;
  replace(
    token: string,
    projectId: string,
    body: T,
    storage?: Storage,
  ): Promise<void>;
  clear(
    token: string,
    projectId: string,
    body: T,
    storage?: Storage,
  ): Promise<void>;
  discard(token: string, projectId: string, storage?: Storage): Promise<void>;
};

export function receipts<T>(
  prefix: string,
  valid: (value: unknown) => value is T,
  what: string,
): Receipts<T> {
  async function storageKey(token: string, projectId: string) {
    if (!token || !ID.test(projectId))
      throw new Error(`Reconnect before sending the ${what}.`);
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(token),
    );
    const owner = Array.from(new Uint8Array(digest), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join("");
    return `${prefix}${owner}:${projectId}`;
  }
  function read(key: string, projectId: string, storage: Storage): T | null {
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
      !valid(record.body)
    )
      throw new Error(
        `A retained ${what} cannot be verified. Nothing will be sent until it is cleared.`,
      );
    return record.body;
  }
  const local = () => window.localStorage;
  return {
    async pending(token, projectId, storage = local()) {
      return read(await storageKey(token, projectId), projectId, storage);
    },
    async retain(token, projectId, body, storage = local()) {
      if (!valid(body))
        throw new Error(`The ${what} cannot be safely retained.`);
      const key = await storageKey(token, projectId);
      const prior = read(key, projectId, storage);
      if (prior && JSON.stringify(prior) !== JSON.stringify(body))
        throw new Error(
          `Another ${what} is unresolved. Retry it before sending a new one.`,
        );
      const serialized = JSON.stringify({
        version: 1,
        project_id: projectId,
        body,
      });
      storage.setItem(key, serialized);
      if (storage.getItem(key) !== serialized)
        throw new Error(
          `The browser could not retain the ${what}, so it was not sent.`,
        );
    },
    async clear(token, projectId, body, storage = local()) {
      const key = await storageKey(token, projectId);
      const prior = read(key, projectId, storage);
      if (prior && JSON.stringify(prior) === JSON.stringify(body))
        storage.removeItem(key);
    },
    async replace(token, projectId, body, storage = local()) {
      if (!valid(body))
        throw new Error(`The ${what} cannot be safely retained.`);
      const key = await storageKey(token, projectId);
      // Validate any existing record, then replace it in one storage write.
      // A failed setItem leaves the previous comparison point available.
      read(key, projectId, storage);
      const serialized = JSON.stringify({
        version: 1,
        project_id: projectId,
        body,
      });
      storage.setItem(key, serialized);
      if (storage.getItem(key) !== serialized)
        throw new Error(`The browser could not update the ${what}.`);
    },
    async discard(token, projectId, storage = local()) {
      storage.removeItem(await storageKey(token, projectId));
    },
  };
}
