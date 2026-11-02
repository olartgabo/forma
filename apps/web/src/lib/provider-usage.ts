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
