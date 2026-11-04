"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, proposeRepairs } from "../lib/api";
import type {
  DiagnosisDiagnostics,
  RepairProposeResult,
} from "../lib/generated/api-contracts";
import type {
  DiagnosisProposal,
  RepairPatch,
} from "../lib/generated/contracts";
import {
  formatCombinedProviderUsage,
  museDiagnosticsFromResult,
} from "../lib/provider-usage";
import {
  museFailureText,
  museNoticeText,
  museStoredFailure,
  type MuseNoticeId,
  type MuseStoredFailure,
} from "../lib/muse-language";
import type { MuseAvailability } from "../lib/muse-provider";
import MuseRequestStatus from "./muse-request-status";
import { useMuseLanguage } from "./muse-language-provider";

export type MuseCandidateMerge = { added: number; skipped: number };

export default function MuseRepairPanel({
  token,
  projectId,
  versionId,
  lastEventId,
  diagnosis,
  diagnosisDiagnostics,
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
  diagnosisDiagnostics?: DiagnosisDiagnostics | null;
  progressLoaded: boolean;
  disabled: boolean;
  onCandidates: (candidates: readonly RepairPatch[]) => MuseCandidateMerge;
  museAvailability?: MuseAvailability;
}) {
  const [problem, setProblem] = useState("");
  const [consented, setConsented] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<MuseStoredFailure | null>(null);
  const [cancelledNotice, setCancelledNotice] = useState<MuseNoticeId | null>(
    null,
  );
  const [result, setResult] = useState<RepairProposeResult | null>(null);
  const [combinedDiagnosis, setCombinedDiagnosis] =
    useState<DiagnosisDiagnostics | null>(null);
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
  const diagnosisDiagnosticsRef = useRef(diagnosisDiagnostics);

  useEffect(
    () => () => {
      epoch.current += 1;
      controller.current?.abort();
    },
    [],
  );

  // A new handoff (new diagnosis) aborts an in-flight Muse request.
  useEffect(() => {
    if (
      diagnosisRef.current === diagnosis &&
      diagnosisDiagnosticsRef.current === diagnosisDiagnostics
    )
      return;
    diagnosisRef.current = diagnosis;
    diagnosisDiagnosticsRef.current = diagnosisDiagnostics;
    epoch.current += 1;
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
    setConsented(false);
    setResult(null);
    setCombinedDiagnosis(null);
    setMerge(null);
    setFailure(null);
    setCancelledNotice(null);
  }, [diagnosis, diagnosisDiagnostics]);

  // A new active version invalidates consent and any shown Muse result.
  useEffect(() => {
    epoch.current += 1;
    controller.current?.abort();
    controller.current = null;
    setConsented(false);
    setResult(null);
    setCombinedDiagnosis(null);
    setMerge(null);
    setFailure(null);
    setCancelledNotice(null);
    setBusy(false);
  }, [token, projectId, versionId]);

  function cancel() {
    epoch.current += 1;
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
    setResult(null);
    setCombinedDiagnosis(null);
    setMerge(null);
    setFailure(null);
    setCancelledNotice("repair-cancelled");
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
    const requestedDiagnosisDiagnostics = diagnosisDiagnostics ?? null;
    // Consent covers this one request only: consume it on dispatch.
    setConsented(false);
    setBusy(true);
    setFailure(null);
    setCancelledNotice(null);
    setResult(null);
    setCombinedDiagnosis(null);
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
      setCombinedDiagnosis(requestedDiagnosisDiagnostics);
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
        setCancelledNotice("repair-cancelled");
        return;
      }
      setFailure(
        museStoredFailure({
          code: failure instanceof ApiError ? failure.code : undefined,
          apiMessage: failure instanceof ApiError ? failure.message : undefined,
          fallbackSection: "repair",
        }),
      );
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
        succeeded={Boolean(result?.candidates.length)}
        onCancel={cancel}
        cancelledMessage={museNoticeText(cancelledNotice, locale)}
        errorCode={failure?.code}
        errorMessage={failure ? museFailureText(failure, locale) : undefined}
        diagnostics={
          result ? museDiagnosticsFromResult(result.diagnostics) : null
        }
        locale={locale}
      />
      {result && (
        <div className="muse-result">
          <p className="help">
            {formatCombinedProviderUsage(
              combinedDiagnosis,
              result.diagnostics,
              locale,
            )}
          </p>
        </div>
      )}
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
