import type {
  MuseConstructionRequest,
  MuseConstructionResult,
} from "./generated/api-contracts";
// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { ApiError } from "./api.ts";

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
