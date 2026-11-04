import { useId } from "react";
import type { ProviderUsage } from "../lib/generated/api-contracts";
import { museCopyFor } from "../lib/muse-language";
import {
  formatMuseLatency,
  formatProviderUsage,
  museRequestStatus,
} from "../lib/provider-usage";
import CubeLoader from "./cube-loader";
import styles from "./cube-loader.module.css";
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
  succeeded,
  onCancel,
  cancelledMessage,
  errorCode,
  errorMessage,
  diagnostics,
  locale,
}: {
  busy?: boolean;
  succeeded: boolean;
  onCancel?: () => void;
  cancelledMessage?: string;
  errorCode?: string;
  errorMessage?: string;
  diagnostics?: MuseDiagnostics | null;
  locale?: unknown;
}) {
  const context = useMuseLanguage();
  const pendingHelpId = useId();
  const effectiveLocale = locale ?? context.locale;
  const copy = museCopyFor(effectiveLocale);
  const failure = errorMessage
    ? museRequestStatus({ errorCode }, effectiveLocale)
    : null;
  return (
    <div lang={effectiveLocale === "es" ? "es" : "en"}>
      <div className={styles.status}>
        <CubeLoader busy={busy} succeeded={succeeded} />
        {busy && (
          <div>
            <p className={styles.statusLabel} role="status">
              {copy.status.pending}
            </p>
            {onCancel && (
              <button
                type="button"
                className="secondary"
                aria-describedby={pendingHelpId}
                onClick={onCancel}
              >
                {copy.actions.cancel}
              </button>
            )}
          </div>
        )}
      </div>
      {busy && (
        <p className="help" id={pendingHelpId}>
          {copy.status.pendingHelp}
        </p>
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
