// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { modelKeyHeaders } from "./developer-settings.ts";
import type {
  MuseConstructionRequest,
  MuseConstructionResult,
  MuseConstructionReceipts,
  MuseConstructionReplacementRequest,
  MuseConstructionReplacementAuthorization,
} from "./generated/api-contracts";
// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { ApiError } from "./api.ts";
// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { validConstructionResult } from "./construction-result.ts";

/** An authorized ancestor stays unknown; only its linked child may proceed. */
export function blockingConstructionReceipts(
  receipts: MuseConstructionReceipts["receipts"],
  pendingKey?: string,
  revisionId?: string,
  forSavedPreview = false,
) {
  const linkedChild = (receipt: MuseConstructionReceipts["receipts"][number]) =>
    receipts.find(
      (r) =>
        r.idempotency_key === receipt.replacement_idempotency_key &&
        r.replaces_idempotency_key === receipt.idempotency_key,
    );
  const authorizesSelectedKey = (
    receipt: MuseConstructionReceipts["receipts"][number],
    seen = new Set<string>(),
  ): boolean => {
    if (seen.has(receipt.idempotency_key)) return false;
    seen.add(receipt.idempotency_key);
    if (
      receipt.replacement_idempotency_key === pendingKey &&
      receipt.replacement_expected_revision_id === revisionId
    )
      return true;
    const child = linkedChild(receipt);
    return !!child && authorizesSelectedKey(child, seen);
  };
  const completedSuccessor = (
    receipt: MuseConstructionReceipts["receipts"][number],
    seen = new Set<string>(),
  ): boolean => {
    if (seen.has(receipt.idempotency_key)) return false;
    seen.add(receipt.idempotency_key);
    const child = linkedChild(receipt);
    return (
      !!child &&
      (child.state === "completed" ||
        (child.state === "unknown" && completedSuccessor(child, seen)))
    );
  };
  return receipts.filter((receipt) => {
    if (receipt.state === "completed") return false;
    if (receipt.state !== "unknown" || !receipt.replacement_idempotency_key)
      return true;
    return (
      !completedSuccessor(receipt) &&
      (forSavedPreview || !authorizesSelectedKey(receipt))
    );
  });
}

export async function authorizeConstructionReplacement(
  token: string,
  projectId: string,
  body: MuseConstructionReplacementRequest,
): Promise<MuseConstructionReplacementAuthorization> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/construction/replacement-authorizations`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        signal: controller.signal,
      },
    );
    if (!response.ok) throw new Error();
    const value = await response.json();
    if (
      !value ||
      value.project_id !== projectId ||
      value.expected_revision_id !== body.expected_revision_id ||
      value.original_idempotency_key !== body.original_idempotency_key ||
      value.original_digest !== body.original_digest ||
      value.replacement_idempotency_key !== body.replacement_idempotency_key ||
      typeof value.replayed !== "boolean"
    )
      throw new Error();
    return value;
  } catch {
    throw new ApiError(
      0,
      "replacement_authorization_unavailable",
      "Replacement authorization could not be confirmed. Check request status before trying again. No model request was sent by this action.",
    );
  } finally {
    clearTimeout(timeout);
  }
}

/** Read the existing completed result. Never POST, retry or settle a receipt. */
export async function savedConstruction(
  token: string,
  projectId: string,
  revisionId: string,
  signal?: AbortSignal,
): Promise<MuseConstructionResult | null> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal?.aborted) cancel();
  signal?.addEventListener("abort", cancel, { once: true });
  const timeout = setTimeout(cancel, 15_000);
  try {
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/construction/preview?expected_inventory_revision_id=${encodeURIComponent(revisionId)}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        signal: controller.signal,
      },
    );
    if (response.status === 404) return null;
    if (!response.ok) throw new Error();
    // Bound the downloaded body as well as the parsed display collections.
    const reader = response.body?.getReader();
    if (!reader) throw new Error();
    const chunks: Uint8Array[] = [];
    let bytes = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 8_000_000 || controller.signal.aborted) {
        await reader.cancel();
        throw new Error();
      }
      chunks.push(value);
    }
    const buffer = new Uint8Array(bytes);
    let offset = 0;
    for (const chunk of chunks) {
      buffer.set(chunk, offset);
      offset += chunk.length;
    }
    const result: unknown = JSON.parse(new TextDecoder().decode(buffer));
    if (
      controller.signal.aborted ||
      !validConstructionResult(result, projectId, revisionId)
    )
      throw new Error();
    return result;
  } catch {
    throw new ApiError(
      0,
      "saved_construction_unavailable",
      "The saved manual could not be verified for these materials. No generation was started and no unknown request was resolved.",
    );
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", cancel);
  }
}

const MESSAGES: Record<string, string> = {
  consent_required:
    "Consent to share this request and selected photo is required.",
  stale_version:
    "Saved materials changed. Reload the project before proposing again.",
  not_found: "The project or selected photo is no longer available.",
  blocked:
    "This project cannot start a new construction proposal. Check its current build and materials.",
  provider_not_configured: "MetaMuse is not configured on this server.",
  provider_authentication:
    "MetaMuse rejected the server credential. Ask the operator to check it.",
  access_denied: "The configured MetaMuse model is unavailable to this server.",
  rate_limit: "MetaMuse reached its rate limit. Try later with fresh consent.",
  generation_in_progress:
    "The original request is still running. Check that request again; do not start another.",
  generation_outcome_unknown:
    "The original provider outcome is unknown. New generation is blocked until it is reconciled.",
  idempotency_conflict:
    "The original request no longer matches this retry. Reload and check its outcome.",
  timeout:
    "The request timed out. Its provider outcome may be unknown; check the original request.",
  network_error:
    "The connection ended before the outcome was known. Check the original request.",
  invalid_response:
    "The response could not be read. Check the original request before generating another.",
  proposal_rejected:
    "The server rejected the model output and resolved this request. Review your notes before starting another proposal.",
  validation_error:
    "The proposal request was rejected. Check the saved materials and selected photo.",
};

export function uncertainConstructionOutcome(code: string): boolean {
  return [
    "timeout",
    "network_error",
    "invalid_response",
    "generation_in_progress",
    "generation_outcome_unknown",
    "cancelled",
  ].includes(code);
}

export async function proposeConstruction(
  token: string,
  projectId: string,
  body: MuseConstructionRequest,
  signal?: AbortSignal,
): Promise<MuseConstructionResult> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  const timeout = setTimeout(cancel, 130_000);
  let response: Response;
  try {
    response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/construction/propose`,
      {
        method: "POST",
        headers: {
          ...modelKeyHeaders(),
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        signal: controller.signal,
      },
    );
  } catch {
    throw new ApiError(0, "network_error", MESSAGES.network_error);
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", cancel);
  }
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new ApiError(
      response.status,
      "invalid_response",
      MESSAGES.invalid_response,
    );
  }
  if (!response.ok) {
    const serverCode =
      typeof value === "object" &&
      value !== null &&
      "code" in value &&
      typeof value.code === "string"
        ? value.code
        : "provider_error";
    // This parsed server rejection clears its receipt. Unreadable responses
    // and invalid successful results remain uncertain client invalid_response.
    const code =
      serverCode === "invalid_response" && response.status === 502
        ? "proposal_rejected"
        : serverCode;
    throw new ApiError(
      response.status,
      code in MESSAGES ? code : "provider_error",
      MESSAGES[code] ??
        "MetaMuse could not finish this request. No construction has been approved.",
    );
  }
  const result = value as MuseConstructionResult;
  if (
    !result ||
    result.project_id !== projectId ||
    result.inventory_revision_id !== body.expected_revision_id ||
    !Array.isArray(result.candidates) ||
    !Array.isArray(result.questions) ||
    !result.diagnostics
  ) {
    throw new ApiError(
      response.status,
      "invalid_response",
      MESSAGES.invalid_response,
    );
  }
  return result;
}

// Receipt inspection is read-only and never resumes provider work.
export async function constructionReceipts(
  token: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<MuseConstructionReceipts> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  const timeout = setTimeout(cancel, 15_000);
  try {
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/construction/receipts`,
      {
        method: "GET",
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        signal: controller.signal,
      },
    );
    if (!response.ok) throw new Error();
    const value: unknown = await response.json();
    const codes = new Set([
      "timeout",
      "network_error",
      "budget_exhausted",
      "server_error",
      "result_not_confirmed",
      "stale_version",
      "blocked",
      "not_found",
      "generation_outcome_unknown",
    ]);
    if (
      !value ||
      typeof value !== "object" ||
      !("receipts" in value) ||
      !Array.isArray(value.receipts) ||
      value.receipts.length > 16
    )
      throw new Error();
    const receipts = value.receipts.map((receipt: unknown) => {
      if (
        !receipt ||
        typeof receipt !== "object" ||
        !("idempotency_key" in receipt) ||
        typeof receipt.idempotency_key !== "string" ||
        receipt.idempotency_key.length < 8 ||
        receipt.idempotency_key.length > 128 ||
        !("digest" in receipt) ||
        typeof receipt.digest !== "string" ||
        !/^[a-f0-9]{64}$/.test(receipt.digest) ||
        !("state" in receipt) ||
        !["pending", "unknown", "completed"].includes(String(receipt.state))
      )
        throw new Error();
      const code = "error_code" in receipt ? receipt.error_code : null;
      if (code !== null && (typeof code !== "string" || !codes.has(code)))
        throw new Error();
      const replacementKey =
        "replacement_idempotency_key" in receipt
          ? receipt.replacement_idempotency_key
          : undefined;
      const replacementRevision =
        "replacement_expected_revision_id" in receipt
          ? receipt.replacement_expected_revision_id
          : undefined;
      const replaces =
        "replaces_idempotency_key" in receipt
          ? receipt.replaces_idempotency_key
          : undefined;
      const validKey = (v: unknown) =>
        typeof v === "string" && v.length >= 8 && v.length <= 128;
      if (
        (replacementKey != null &&
          (!validKey(replacementKey) ||
            typeof replacementRevision !== "string" ||
            !/^[A-Za-z][A-Za-z0-9_-]{0,95}$/.test(replacementRevision))) ||
        (replacementKey == null && replacementRevision != null) ||
        (replaces != null && !validKey(replaces))
      )
        throw new Error();
      return {
        idempotency_key: receipt.idempotency_key,
        digest: receipt.digest,
        state: receipt.state,
        error_code: code,
        ...(replacementKey != null
          ? {
              replacement_idempotency_key: replacementKey,
              replacement_expected_revision_id: replacementRevision,
            }
          : {}),
        ...(replaces != null ? { replaces_idempotency_key: replaces } : {}),
      };
    });
    return { receipts } as MuseConstructionReceipts;
  } catch {
    throw new ApiError(
      0,
      "receipt_status_unavailable",
      "Request status could not be confirmed. Generation is blocked; check request status again.",
    );
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", cancel);
  }
}
