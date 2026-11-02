"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, proposeRepairs } from "../lib/api";
import type { RepairProposeResult } from "../lib/generated/api-contracts";
import type {
  DiagnosisProposal,
  RepairPatch,
} from "../lib/generated/contracts";
import { museDiagnosticsFromResult } from "../lib/provider-usage";
import type { MuseAvailability } from "../lib/muse-provider";
import MuseRequestStatus from "./muse-request-status";
import { useMuseLanguage } from "./muse-language-provider";

function errorMessage(error: unknown, fallback?: string) {
  return error instanceof ApiError
    ? error.message
    : (fallback ??
        "The request could not finish. Check the API connection and try again.");
}

export type MuseCandidateMerge = { added: number; skipped: number };

export default function MuseRepairPanel({
  token,
  projectId,
  versionId,
  lastEventId,
  diagnosis,
  progressLoaded,
  disabled,
  onCandidates,
  museAvailability,
}: {
  token: string;
  projectId: string;
  versionId: string;
  lastEventId: string | null;
  diagnosis?: DiagnosisProposal | null;
  progressLoaded: boolean;
  disabled: boolean;
  onCandidates: (candidates: readonly RepairPatch[]) => MuseCandidateMerge;
  museAvailability?: MuseAvailability;
}) {
  const [problem, setProblem] = useState("");
  const [consented, setConsented] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{
    code?: string;
    message: string;
  } | null>(null);
  const [cancelledMessage, setCancelledMessage] = useState("");
  const [result, setResult] = useState<RepairProposeResult | null>(null);
  const [merge, setMerge] = useState<MuseCandidateMerge | null>(null);
  const { locale, copy } = useMuseLanguage();
  const controller = useRef<AbortController | null>(null);
  const epoch = useRef(0);
  const versionRef = useRef(versionId);
  versionRef.current = versionId;
  const projectRef = useRef(projectId);
  projectRef.current = projectId;
  const onCandidatesRef = useRef(onCandidates);
  onCandidatesRef.current = onCandidates;
  const diagnosisRef = useRef(diagnosis);

  useEffect(
    () => () => {
      epoch.current += 1;
      controller.current?.abort();
    },
    [],
  );

  // A new handoff (new diagnosis) aborts an in-flight Muse request.
  useEffect(() => {
    if (diagnosisRef.current === diagnosis) return;
    diagnosisRef.current = diagnosis;
    epoch.current += 1;
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
    setConsented(false);
    setResult(null);
    setMerge(null);
    setFailure(null);
    setCancelledMessage("");
  }, [diagnosis]);

  // A new active version invalidates consent and any shown Muse result.
  useEffect(() => {
    epoch.current += 1;
    controller.current?.abort();
    controller.current = null;
    setConsented(false);
    setResult(null);
    setMerge(null);
    setFailure(null);
    setCancelledMessage("");
    setBusy(false);
  }, [token, projectId, versionId]);

  function cancel() {
    epoch.current += 1;
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
    setFailure(null);
    setCancelledMessage(copy.repair.cancelled);
  }

  async function ask() {
    if (
      !progressLoaded ||
      !consented ||
      !problem.trim() ||
      busy ||
      disabled ||
      museAvailability?.enabled === false ||
      !diagnosis
    )
      return;
    const requestEpoch = ++epoch.current;
    const requestController = new AbortController();
    controller.current = requestController;
    const requestedVersion = versionId;
    const requestedProject = projectId;
    const requestedDiagnosis = diagnosis;
    // Consent covers this one request only: consume it on dispatch.
    setConsented(false);
    setBusy(true);
    setFailure(null);
    setCancelledMessage("");
    setResult(null);
    setMerge(null);
    try {
      const next = await proposeRepairs(
        token,
        projectId,
        {
          expected_version_id: versionId,
          expected_last_event_id: lastEventId,
          reported_problem: problem.trim(),
          diagnosis: requestedDiagnosis,
          provider_context_consented: true,
        },
        requestController.signal,
      );
      if (
        requestController.signal.aborted ||
        requestEpoch !== epoch.current ||
        versionRef.current !== requestedVersion ||
        projectRef.current !== requestedProject
      )
        return;
      setResult(next);
      setMerge(onCandidatesRef.current(next.candidates));
    } catch (failure) {
      if (
        requestController.signal.aborted ||
        requestEpoch !== epoch.current ||
        versionRef.current !== requestedVersion ||
        projectRef.current !== requestedProject
      )
        return;
      if (failure instanceof ApiError && failure.code === "cancelled") {
        setCancelledMessage(copy.repair.cancelled);
        return;
      }
      setFailure({
        code: failure instanceof ApiError ? failure.code : undefined,
        message: errorMessage(failure, copy.repair.requestFailed),
      });
    } finally {
      setConsented(false);
      if (!requestController.signal.aborted && requestEpoch === epoch.current) {
        controller.current = null;
        setBusy(false);
      }
    }
  }

  const actionDisabled =
    !progressLoaded ||
    !consented ||
    !problem.trim() ||
    busy ||
    disabled ||
    museAvailability?.enabled === false ||
    !diagnosis;

  return (
    <section
      className="muse-panel"
      aria-labelledby="muse-repair-title"
      lang={locale}
    >
      <h4 id="muse-repair-title">{copy.repair.title}</h4>
      <p>{copy.repair.intro}</p>
      {!diagnosis ? (
        <p className="help" role="note">
          {copy.repair.needsDiagnosis}
        </p>
      ) : (
        <p className="help">{copy.repair.sendsContext}</p>
      )}
      <label htmlFor="muse-repair-problem">{copy.repair.problemLabel}</label>
      <textarea
        id="muse-repair-problem"
        rows={4}
        maxLength={1000}
        value={problem}
        disabled={busy}
        onChange={(event) => setProblem(event.target.value)}
        placeholder={copy.repair.problemPlaceholder}
      />
      {museAvailability?.enabled === false && (
        <p className="help" role="note">
          {locale === "es"
            ? copy.provider.notConfiguredReason
            : museAvailability.reason}
        </p>
      )}
      <label className="checkbox-label" htmlFor="muse-repair-consent">
        <input
          id="muse-repair-consent"
          type="checkbox"
          checked={consented}
          disabled={busy || museAvailability?.enabled === false}
          onChange={(event) => setConsented(event.target.checked)}
        />
        {copy.repair.consent}
      </label>
      <div className="muse-actions">
        <button
          type="button"
          className="primary"
          disabled={actionDisabled}
          onClick={() => void ask()}
        >
          {copy.repair.ask}
        </button>
      </div>
      <MuseRequestStatus
        busy={busy}
        pendingMessage={copy.repair.pending}
        onCancel={cancel}
        cancelledMessage={cancelledMessage}
        errorCode={failure?.code}
        errorMessage={failure?.message}
        diagnostics={
          result ? museDiagnosticsFromResult(result.diagnostics) : null
        }
        locale={locale}
      />
      {result && merge && result.candidates.length > 0 && (
        <p className="notice" aria-live="polite">
          {merge.added > 0
            ? copy.repair.addedOne(merge.added)
            : copy.repair.noAdded}
          {merge.skipped > 0 ? copy.repair.skipped(merge.skipped) : ""}
        </p>
      )}
      {result &&
        result.candidates.length === 0 &&
        result.questions.length === 0 && (
          <p className="notice" aria-live="polite">
            {copy.repair.noCandidates}
          </p>
        )}
      {result && result.questions.length > 0 && (
        <div className="muse-result">
          <p>
            {result.candidates.length === 0
              ? copy.repair.needsInfo
              : copy.repair.alsoAsked}
          </p>
          <h4>{copy.repair.questions}</h4>
          <ul>
            {result.questions.map((question, index) => (
              <li key={`${index}-${question}`}>{question}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
