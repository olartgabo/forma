import type { ProviderUsage } from "../lib/generated/api-contracts";
import {
  formatMuseLatency,
  formatProviderUsage,
  museRequestStatus,
} from "../lib/provider-usage";

export type MuseDiagnostics = {
  status: string;
  model: string;
  elapsedMs: number;
  usage?: ProviderUsage | null;
  modelRounds?: number;
  toolExecutions?: number;
};

export default function MuseRequestStatus({
  busy = false,
  pendingMessage,
  onCancel,
  cancelledMessage,
  errorCode,
  errorMessage,
  diagnostics,
}: {
  busy?: boolean;
  pendingMessage?: string;
  onCancel?: () => void;
  cancelledMessage?: string;
  errorCode?: string;
  errorMessage?: string;
  diagnostics?: MuseDiagnostics | null;
}) {
  const failure = errorMessage ? museRequestStatus({ errorCode }) : null;
  return (
    <>
      {busy && (
        <>
          <p className="help" aria-live="polite">
            {pendingMessage}
          </p>
          {onCancel && (
            <div className="muse-actions">
              <button type="button" className="secondary" onClick={onCancel}>
                Cancel
              </button>
            </div>
          )}
        </>
      )}
      {cancelledMessage && (
        <p className="notice" aria-live="polite">
          {cancelledMessage}
        </p>
      )}
      {failure && errorMessage && (
        <p className="error" role="alert">
          {failure.label}: {errorMessage}
        </p>
      )}
      {diagnostics && (
        <p className="help">
          Request diagnostics — status: {diagnostics.status}; model:{" "}
          {diagnostics.model};
          {diagnostics.modelRounds !== undefined && (
            <> rounds: {diagnostics.modelRounds};</>
          )}
          {diagnostics.toolExecutions !== undefined && (
            <> tool calls: {diagnostics.toolExecutions};</>
          )}{" "}
          {formatMuseLatency(diagnostics.elapsedMs)}.{" "}
          {formatProviderUsage(diagnostics.usage)}
        </p>
      )}
    </>
  );
}
