// Recognised-item cards client (#177 follow-up). No provider call.
import type {
  RecognizedItems,
  RecognizedItemsUpdate,
} from "./generated/api-contracts";
import type { ItemProposal } from "./generated/contracts";
// @ts-expect-error -- Node tests import TypeScript directly.
import { MATERIAL_CATALOG } from "./generated/material-catalog.ts";

export class ItemsRequestError extends Error {
  readonly status: number;
  // True when the save may have completed; retry the exact same body.
  readonly retryExact: boolean;
  constructor(message: string, status: number, retryExact: boolean) {
    super(message);
    this.status = status;
    this.retryExact = retryExact;
  }
}

const ID = /^[A-Za-z][A-Za-z0-9_-]{0,95}$/;
const CATEGORY_IDS = new Set<string>(
  (MATERIAL_CATALOG.categories as readonly { id: string }[]).map((c) => c.id),
);
const OUTCOMES = new Set(["catalog", "other", "uncertain"]);

function object(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

function unit(v: unknown) {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1;
}

function validBox(v: unknown) {
  return (
    v == null ||
    (object(v) &&
      unit(v.x1) &&
      unit(v.y1) &&
      unit(v.x2) &&
      unit(v.y2) &&
      (v.x2 as number) > (v.x1 as number) &&
      (v.y2 as number) > (v.y1 as number))
  );
}

/** The same rules the server applies: a category only for a catalog outcome. */
export function validIdentity(v: unknown): boolean {
  if (!object(v) || typeof v.outcome !== "string" || !OUTCOMES.has(v.outcome))
    return false;
  const alternatives = v.alternatives ?? [];
  if (
    !Array.isArray(alternatives) ||
    alternatives.length > 3 ||
    !alternatives.every((a) => typeof a === "string" && CATEGORY_IDS.has(a))
  )
    return false;
  const category = v.category_id ?? null;
  if (v.outcome === "catalog")
    return (
      typeof category === "string" &&
      CATEGORY_IDS.has(category) &&
      !alternatives.includes(category)
    );
  if (category !== null) return false;
  if (v.outcome === "other")
    return typeof v.other_label === "string" && v.other_label.trim() !== "";
  return v.other_label == null;
}

/** Muse item proposals that are usable; others are dropped, never guessed. */
export function validProposals(value: unknown): ItemProposal[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (p): p is ItemProposal =>
      object(p) &&
      validIdentity(p.identity) &&
      typeof p.visible_evidence === "string" &&
      validBox(p.box),
  );
}

function validItems(
  value: unknown,
  projectId: string,
): value is RecognizedItems {
  return (
    object(value) &&
    value.project_id === projectId &&
    (value.revision === null ||
      (typeof value.revision === "string" && ID.test(value.revision))) &&
    Array.isArray(value.items) &&
    value.items.every(
      (i) =>
        object(i) &&
        typeof i.id === "string" &&
        ID.test(i.id) &&
        typeof i.name === "string" &&
        validIdentity(i.identity) &&
        validBox(i.box),
    ) &&
    Array.isArray(value.problems ?? [])
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
    throw new ItemsRequestError(
      "The connection failed before an answer arrived. Try again.",
      0,
      true,
    );
  }
  const body = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const message =
      object(body) && typeof body.message === "string"
        ? body.message
        : "Item cards are unavailable right now.";
    throw new ItemsRequestError(
      message,
      response.status,
      response.status >= 500 || response.status === 429,
    );
  }
  if (body === null)
    throw new ItemsRequestError("The answer was cut off. Try again.", 0, true);
  return body;
}

export function recognizedItems(token: string, projectId: string) {
  const root = `/api/projects/${encodeURIComponent(projectId)}/recognized-items`;
  const checked = (value: unknown) => {
    if (!validItems(value, projectId))
      throw new ItemsRequestError(
        "Saved item cards could not be read.",
        0,
        true,
      );
    return value;
  };
  return {
    async read(signal?: AbortSignal): Promise<RecognizedItems> {
      return checked(await send(token, root, { method: "GET" }, signal));
    },
    async save(
      body: RecognizedItemsUpdate,
      signal?: AbortSignal,
    ): Promise<RecognizedItems> {
      return checked(
        await send(
          token,
          root,
          { method: "PUT", body: JSON.stringify(body) },
          signal,
        ),
      );
    },
  };
}
