"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, proposeRepairs } from "../lib/api";
import type { RepairProposeResult } from "../lib/generated/api-contracts";
import type {
  DiagnosisProposal,
  RepairPatch,
} from "../lib/generated/contracts";
import { museDiagnosticsFromResult } from "../lib/provider-usage";
import MuseRequestStatus from "./muse-request-status";

function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "The request could not finish. Check the API connection and try again.";
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
}: {
  token: string;
  projectId: string;
  versionId: string;
  lastEventId: string | null;
  diagnosis?: DiagnosisProposal | null;
  progressLoaded: boolean;
  disabled: boolean;
  onCandidates: (candidates: readonly RepairPatch[]) => MuseCandidateMerge;
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
    setCancelledMessage(
      "Cancelled. FORMA stopped waiting for Muse; Muse may already be processing the request, so no result was shown.",
    );
  }

  async function ask() {
    if (
      !progressLoaded ||
      !consented ||
      !problem.trim() ||
      busy ||
      disabled ||
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
        setCancelledMessage(
          "Cancelled. FORMA stopped waiting for Muse; Muse may already be processing the request, so no result was shown.",
        );
        return;
      }
      setFailure({
        code: failure instanceof ApiError ? failure.code : undefined,
        message: errorMessage(failure),
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
    !diagnosis;

  return (
    <section className="muse-panel" aria-labelledby="muse-repair-title">
      <h4 id="muse-repair-title">Ask Muse for repair options</h4>
      <p>
        Muse can propose repair candidates from your reported problem, the Muse
        diagnosis (if present) and the active plan context. Proposals are
        unverified: they are only added to the candidate list below. Nothing is
        simulated or approved until you confirm remaining stock, press Simulate
        repairs and approve a preview yourself.
      </p>
      {!diagnosis ? (
        <p className="help" role="note">
          A Muse diagnosis is needed first. Ask Muse what went wrong above and
          review a repair from that diagnosis, then return here. FORMA will not
          invent a diagnosis.
        </p>
      ) : (
        <p className="help">
          This request sends your reported problem, the Muse diagnosis from the
          handoff and the active plan context to Meta&apos;s Muse service for
          this one request.
        </p>
      )}
      <label htmlFor="muse-repair-problem">Reported problem</label>
      <textarea
        id="muse-repair-problem"
        rows={4}
        maxLength={1000}
        value={problem}
        disabled={busy}
        onChange={(event) => setProblem(event.target.value)}
        placeholder="For example: the brace tore at the slot"
      />
      <label className="checkbox-label" htmlFor="muse-repair-consent">
        <input
          id="muse-repair-consent"
          type="checkbox"
          checked={consented}
          disabled={busy}
          onChange={(event) => setConsented(event.target.checked)}
        />
        Send my reported problem, the Muse diagnosis if present and the active
        plan context to Meta&apos;s Muse service for this one request.
      </label>
      <div className="muse-actions">
        <button
          type="button"
          className="primary"
          disabled={actionDisabled}
          onClick={() => void ask()}
        >
          Ask Muse for repair options
        </button>
      </div>
      <MuseRequestStatus
        busy={busy}
        pendingMessage="Asking Muse… Cancelling stops FORMA waiting; Muse may already be processing the request. There are no automatic retries."
        onCancel={cancel}
        cancelledMessage={cancelledMessage}
        errorCode={failure?.code}
        errorMessage={failure?.message}
        diagnostics={
          result ? museDiagnosticsFromResult(result.diagnostics) : null
        }
      />
      {result && merge && result.candidates.length > 0 && (
        <p className="notice" aria-live="polite">
          {merge.added > 0
            ? `Added ${merge.added} Muse proposal${merge.added === 1 ? "" : "s"} (unverified) to the candidate list. Confirm remaining stock and press Simulate repairs to preview ${merge.added === 1 ? "it" : "them"}.`
            : "No candidates were added."}
          {merge.skipped > 0
            ? ` ${merge.skipped} proposal${merge.skipped === 1 ? " was" : "s were"} skipped (duplicate or the 3-candidate limit was reached).`
            : ""}
        </p>
      )}
      {result &&
        result.candidates.length === 0 &&
        result.questions.length === 0 && (
          <p className="notice" aria-live="polite">
            Muse returned no repair candidates. No candidates were added; add a
            candidate yourself or give more detail and ask again.
          </p>
        )}
      {result && result.questions.length > 0 && (
        <div className="muse-result">
          <p>
            {result.candidates.length === 0
              ? "Muse needs more information before proposing repairs. No candidates were added from these questions."
              : "Muse also asked the following questions."}
          </p>
          <h4>Questions from Muse</h4>
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
