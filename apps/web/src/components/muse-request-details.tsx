import type { ProviderUsage } from "../lib/generated/api-contracts";
import { formatProviderUsage } from "../lib/provider-usage";

export default function MuseRequestDetails({
  status,
  model,
  elapsedMs,
  usage,
  modelRounds,
  toolExecutions,
}: {
  status: string;
  model: string;
  elapsedMs: number;
  usage?: ProviderUsage | null;
  modelRounds?: number;
  toolExecutions?: number;
}) {
  return (
    <p className="help">
      Request diagnostics — status: {status}; model: {model};
      {modelRounds !== undefined && <> rounds: {modelRounds};</>}
      {toolExecutions !== undefined && <> tool calls: {toolExecutions};</>}{" "}
      duration: {elapsedMs} ms. {formatProviderUsage(usage)}
    </p>
  );
}
