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

const MAX_COMBINED_MODEL_CALLS = 32;
const MAX_COMBINED_TOKENS_TOTAL = 32_000_000_000;

export type CombinedProviderUsage = {
  modelCalls: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  summedElapsedMs: number | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validCount(value: unknown, max: number): number | null {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < 0 ||
    value > max
  )
    return null;
  return value;
}

function sumCounts(
  first: unknown,
  second: unknown,
  perRequestMax: number,
): number | null {
  const a = validCount(first, perRequestMax);
  const b = validCount(second, perRequestMax);
  if (a === null || b === null) return null;
  return a + b;
}

function elapsedOf(record: Record<string, unknown>): unknown {
  return "elapsedMs" in record ? record.elapsedMs : record.elapsed_ms;
}

function validElapsed(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0)
    return null;
  return value;
}

// Pure aggregator for exactly two request records (diagnosis + repair).
// Each record may be a raw diagnostics object ({ usage, elapsed_ms }) or a
// MuseDiagnosticsSummary ({ usage, elapsedMs }). Inputs are never mutated.
export function combineProviderUsage(
  records: unknown,
): CombinedProviderUsage | null {
  if (!Array.isArray(records) || records.length !== 2) return null;
  const [first, second] = records;
  if (!isRecord(first) || !isRecord(second)) return null;
  if (!isRecord(first.usage) || !isRecord(second.usage)) {
    // A missing/malformed usage object makes every count unknown, but a
    // record is still present; elapsed is handled per-field below.
    const a = validElapsed(elapsedOf(first));
    const b = validElapsed(elapsedOf(second));
    return {
      modelCalls: null,
      inputTokens: null,
      outputTokens: null,
      summedElapsedMs: a === null || b === null ? null : a + b,
    };
  }
  const firstElapsed = validElapsed(elapsedOf(first));
  const secondElapsed = validElapsed(elapsedOf(second));
  const summed =
    firstElapsed === null || secondElapsed === null
      ? null
      : firstElapsed + secondElapsed;
  return {
    modelCalls: sumCounts(
      first.usage.model_calls,
      second.usage.model_calls,
      MAX_MODEL_CALLS,
    ),
    inputTokens: sumCounts(
      first.usage.input_tokens,
      second.usage.input_tokens,
      MAX_TOKENS_TOTAL,
    ),
    outputTokens: sumCounts(
      first.usage.output_tokens,
      second.usage.output_tokens,
      MAX_TOKENS_TOTAL,
    ),
    summedElapsedMs: summed !== null && Number.isFinite(summed) ? summed : null,
  };
}

export function formatCombinedProviderUsage(
  diagnosisRecord: unknown,
  repairRecord: unknown,
  locale: unknown = "en",
): string {
  const copy = museCopyFor(locale);
  const combined = combineProviderUsage([diagnosisRecord, repairRecord]);
  if (combined === null) return copy.usage.combinedUnknown;
  const modelCalls = formatCount(
    combined.modelCalls,
    MAX_COMBINED_MODEL_CALLS,
    locale,
  );
  const inputTokens = formatCount(
    combined.inputTokens,
    MAX_COMBINED_TOKENS_TOTAL,
    locale,
  );
  const outputTokens = formatCount(
    combined.outputTokens,
    MAX_COMBINED_TOKENS_TOTAL,
    locale,
  );
  const duration =
    combined.summedElapsedMs === null
      ? copy.usage.combinedDurationUnknown
      : copy.usage.combinedDuration(combined.summedElapsedMs);
  return `${copy.usage.combinedPrefix} — ${copy.usage.modelCalls}: ${modelCalls}; ${copy.usage.inputTokens}: ${inputTokens}; ${copy.usage.outputTokens}: ${outputTokens}; ${duration}.`;
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
