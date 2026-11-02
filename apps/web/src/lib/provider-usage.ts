import type { ProviderUsage } from "./generated/api-contracts";
// prettier-ignore
// @ts-expect-error -- Node type-stripping (tests import .ts directly) requires the explicit .ts extension; tsconfig lacks allowImportingTsExtensions, so TS5097 is expected here.
import { formatEnglishGroupedNumber, museCopyFor } from "./muse-language.ts";

// Bounds mirror the canonical ProviderUsage contract: at most 16 model
// calls and at most 1,000,000,000 tokens per call, aggregated per request.
const MAX_MODEL_CALLS = 16;
const MAX_TOKENS_TOTAL = 16_000_000_000;

function formatCount(value: unknown, max: number, locale: unknown): string {
  const copy = museCopyFor(locale);
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < 0 ||
    value > max
  )
    return copy.usage.notReported;
  // Labels are localized; numeric grouping stays English in every locale.
  return formatEnglishGroupedNumber(value);
}

export function formatProviderUsage(
  usage: ProviderUsage | null | undefined | unknown,
  locale: unknown = "en",
): string {
  const copy = museCopyFor(locale);
  if (typeof usage !== "object" || usage === null || Array.isArray(usage))
    return copy.usage.reportedUnknown;
  const counts = usage as Record<string, unknown>;
  const modelCalls = formatCount(counts.model_calls, MAX_MODEL_CALLS, locale);
  const inputTokens = formatCount(
    counts.input_tokens,
    MAX_TOKENS_TOTAL,
    locale,
  );
  const outputTokens = formatCount(
    counts.output_tokens,
    MAX_TOKENS_TOTAL,
    locale,
  );
  return `${copy.usage.reportedPrefix} — ${copy.usage.modelCalls}: ${modelCalls}; ${copy.usage.inputTokens}: ${inputTokens}; ${copy.usage.outputTokens}: ${outputTokens}.`;
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

export function museStatusLabel(kind: unknown, locale: unknown = "en"): string {
  const copy = museCopyFor(locale);
  switch (kind) {
    case "pending":
      return copy.status.pending;
    case "cancelled":
      return copy.status.cancelled;
    case "timeout":
      return copy.status.timeout;
    case "rate_limit":
      return copy.status.rateLimit;
    case "provider_not_configured":
      return copy.status.providerNotConfigured;
    case "invalid_response":
      return copy.status.invalidResponse;
    case "success":
      return copy.status.success;
    default:
      return copy.status.failure;
  }
}

export function museRequestStatus(
  input: {
    busy?: unknown;
    cancelled?: unknown;
    errorCode?: unknown;
    succeeded?: unknown;
  },
  locale: unknown = "en",
): { kind: MuseStatusKind; label: string } {
  const kind = museStatusKindForState(input);
  return { kind, label: museStatusLabel(kind, locale) };
}

export type MuseDiagnosticsSummary = {
  status: string;
  model: string;
  elapsedMs: number;
  usage?: ProviderUsage | null;
  modelRounds?: number;
  toolExecutions?: number;
};

export function museDiagnosticsFromResult(
  diagnostics: unknown,
): MuseDiagnosticsSummary | null {
  if (
    typeof diagnostics !== "object" ||
    diagnostics === null ||
    Array.isArray(diagnostics)
  )
    return null;
  const value = diagnostics as Record<string, unknown>;
  if (
    typeof value.status !== "string" ||
    value.status.length === 0 ||
    typeof value.model !== "string" ||
    value.model.length === 0 ||
    typeof value.elapsed_ms !== "number" ||
    !Number.isFinite(value.elapsed_ms) ||
    value.elapsed_ms < 0
  )
    return null;
  return {
    status: value.status,
    model: value.model,
    elapsedMs: value.elapsed_ms,
    usage: (value.usage ?? null) as ProviderUsage | null,
    ...(typeof value.model_rounds === "number" &&
    Number.isFinite(value.model_rounds)
      ? { modelRounds: value.model_rounds }
      : {}),
    ...(typeof value.tool_executions === "number" &&
    Number.isFinite(value.tool_executions)
      ? { toolExecutions: value.tool_executions }
      : {}),
  };
}

export function formatMuseLatency(
  elapsedMs: unknown,
  locale: unknown = "en",
): string {
  const copy = museCopyFor(locale);
  if (
    typeof elapsedMs !== "number" ||
    !Number.isFinite(elapsedMs) ||
    elapsedMs < 0
  )
    return copy.usage.durationUnknown;
  return copy.usage.duration(elapsedMs);
}
