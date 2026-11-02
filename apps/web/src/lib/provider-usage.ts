import type { ProviderUsage } from "./generated/api-contracts";

// Bounds mirror the canonical ProviderUsage contract: at most 16 model
// calls and at most 1,000,000,000 tokens per call, aggregated per request.
const MAX_MODEL_CALLS = 16;
const MAX_TOKENS_TOTAL = 16_000_000_000;

function formatCount(value: unknown, max: number): string {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < 0 ||
    value > max
  )
    return "not reported";
  return value.toLocaleString("en-US");
}

export function formatProviderUsage(
  usage: ProviderUsage | null | undefined | unknown,
): string {
  if (typeof usage !== "object" || usage === null || Array.isArray(usage))
    return "Provider-reported usage: not reported.";
  const counts = usage as Record<string, unknown>;
  const modelCalls = formatCount(counts.model_calls, MAX_MODEL_CALLS);
  const inputTokens = formatCount(counts.input_tokens, MAX_TOKENS_TOTAL);
  const outputTokens = formatCount(counts.output_tokens, MAX_TOKENS_TOTAL);
  return `Provider-reported usage — model calls: ${modelCalls}; input tokens: ${inputTokens}; output tokens: ${outputTokens}.`;
}

export type MuseStatusKind =
  | "pending"
  | "cancelled"
  | "timeout"
  | "rate_limit"
  | "provider_not_configured"
  | "invalid_response"
  | "provider_failure"
  | "success";

export function museStatusKindForCode(code: unknown): MuseStatusKind {
  switch (code) {
    case "cancelled":
      return "cancelled";
    case "timeout":
    case "request_timeout":
      return "timeout";
    case "rate_limit":
      return "rate_limit";
    case "provider_not_configured":
      return "provider_not_configured";
    case "invalid_response":
      return "invalid_response";
    default:
      return "provider_failure";
  }
}

export function museStatusKindForState(input: {
  busy?: unknown;
  cancelled?: unknown;
  errorCode?: unknown;
  succeeded?: unknown;
}): MuseStatusKind {
  if (input.busy) return "pending";
  if (input.cancelled) return "cancelled";
  if (input.errorCode !== undefined && input.errorCode !== null)
    return museStatusKindForCode(input.errorCode);
  if (input.succeeded) return "success";
  return "provider_failure";
}

export function museStatusLabel(kind: unknown): string {
  switch (kind) {
    case "pending":
      return "Waiting for Muse";
    case "cancelled":
      return "Request cancelled";
    case "timeout":
      return "Request timed out";
    case "rate_limit":
      return "Rate limit reached";
    case "provider_not_configured":
      return "Muse is not configured";
    case "invalid_response":
      return "Unusable Muse response";
    case "success":
      return "Request completed";
    default:
      return "Muse request failed";
  }
}

export function museRequestStatus(input: {
  busy?: unknown;
  cancelled?: unknown;
  errorCode?: unknown;
  succeeded?: unknown;
}): { kind: MuseStatusKind; label: string } {
  const kind = museStatusKindForState(input);
  return { kind, label: museStatusLabel(kind) };
}

export function formatMuseLatency(elapsedMs: unknown): string {
  if (
    typeof elapsedMs !== "number" ||
    !Number.isFinite(elapsedMs) ||
    elapsedMs < 0
  )
    return "duration: not reported";
  return `duration: ${elapsedMs} ms`;
}
