import type { ProviderUsage } from "../lib/generated/api-contracts";
import { museCopyFor } from "../lib/muse-language";
import {
  formatMuseLatency,
  formatProviderUsage,
  museRequestStatus,
} from "../lib/provider-usage";
import { useMuseLanguage } from "./muse-language-provider";

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
  locale,
}: {
  busy?: boolean;
  pendingMessage?: string;
  onCancel?: () => void;
  cancelledMessage?: string;
  errorCode?: string;
  errorMessage?: string;
  diagnostics?: MuseDiagnostics | null;
  locale?: unknown;
}) {
  const context = useMuseLanguage();
  const effectiveLocale = locale ?? context.locale;
  const copy = museCopyFor(effectiveLocale);
  const failure = errorMessage
    ? museRequestStatus({ errorCode }, effectiveLocale)
    : null;
  return (
    <div lang={effectiveLocale === "es" ? "es" : "en"}>
      {busy && (
        <>
          <p className="help" aria-live="polite">
            {pendingMessage}
          </p>
          {onCancel && (
            <div className="muse-actions">
              <button type="button" className="secondary" onClick={onCancel}>
                {copy.actions.cancel}
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
          {copy.diagnostics.label} — {copy.diagnostics.status}:{" "}
          {diagnostics.status}; {copy.diagnostics.model}: {diagnostics.model};
          {diagnostics.modelRounds !== undefined && (
            <>
              {" "}
              {copy.diagnostics.rounds}: {diagnostics.modelRounds};
            </>
          )}
          {diagnostics.toolExecutions !== undefined && (
            <>
              {" "}
              {copy.diagnostics.toolCalls}: {diagnostics.toolExecutions};
            </>
          )}{" "}
          {formatMuseLatency(diagnostics.elapsedMs, effectiveLocale)}.{" "}
          {formatProviderUsage(diagnostics.usage, effectiveLocale)}
        </p>
      )}
    </div>
  );
}
