import { useCallback, useEffect, useRef, useState } from "react";
import {
  activatePlan,
  ApiError,
  generateDesign,
  listPlans,
  loadPlan,
} from "../lib/api";
import AdaptWorkbench from "./adapt-workbench";
import DesignCandidates from "./design-candidates";
import FabricationReportPanel from "./fabrication-report/fabrication-report-panel";
import { operationTitles } from "../lib/operation-titles";
import type { RepairHandoff } from "../lib/repair-handoff";
import type { DiagnosisFocus } from "../lib/build-diagnosis";
import Diagram from "./manual-diagram";
import { museDiagnosticsFromResult } from "../lib/provider-usage";
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
import PhysicalProgress from "./physical-progress";
import StabilityReportPanel from "./stability-report";
import AssemblyView from "./assembly-view";
import type {
  DesignGenerateRequest,
  DesignGenerateResult,
  ManualPanel,
  Media,
  PlanActivation,
  PlanSummary,
  PlanVersion,
  Project,
} from "../lib/generated/api-contracts";

function message(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "Could not load this plan. Try again.";
}

export default function PlanWorkbench({
  token,
  project,
  approvalDisabled,
  onLockChange,
  onActivated,
  onReload,
  photos,
  onProgressChange,
  repairHandoff,
  onDiagnoseFailure,
  museAvailability,
  diagnosisRefreshKey,
}: {
  token: string;
  project: Project;
  approvalDisabled: boolean;
  onLockChange: (locked: boolean) => void;
  onActivated: (next: Project) => void;
  onReload: () => void;
  photos: readonly Media[];
  onProgressChange: () => void;
  repairHandoff?: { handoff: RepairHandoff; targetId: string } | null;
  onDiagnoseFailure?: (focus: DiagnosisFocus) => void;
  museAvailability?: MuseAvailability;
  diagnosisRefreshKey?: number;
}) {
  const [plans, setPlans] = useState<readonly PlanSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const shownActive = useRef<string | null | undefined>(undefined);
  const [version, setVersion] = useState<PlanVersion | null>(null);
  const [step, setStep] = useState(0);
  const [stabilityRefresh, setStabilityRefresh] = useState(0);
  const [measurementRefresh, setMeasurementRefresh] = useState(0);
  const [measurementPending, setMeasurementPending] = useState(false);
  const handleMeasurementsSaved = useCallback(() => {
    setMeasurementRefresh((value) => value + 1);
  }, []);
  const handleProgressChange = useCallback(() => {
    setStabilityRefresh((value) => value + 1);
    setFabricationKey((value) => value + 1);
    onProgressChange();
  }, [onProgressChange]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [planError, setPlanError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [approved, setApproved] = useState(false);
  const [pending, setPending] = useState<{
    versionId: string;
    body: PlanActivation;
  } | null>(null);
  const [saving, setSaving] = useState(false);
  const [progressPending, setProgressPending] = useState(false);
  const [fabricationKey, setFabricationKey] = useState(0);
  const [activationError, setActivationError] = useState("");
  const [activationStale, setActivationStale] = useState(false);
  const [designNotes, setDesignNotes] = useState("");
  const [designConsented, setDesignConsented] = useState(false);
  const [designBusy, setDesignBusy] = useState(false);
  const [designResult, setDesignResult] = useState<DesignGenerateResult | null>(
    null,
  );
  const [designFailure, setDesignFailure] = useState<MuseStoredFailure | null>(
    null,
  );
  const [designNotice, setDesignNotice] = useState<MuseNoticeId | null>(null);
  const [designPending, setDesignPending] =
    useState<DesignGenerateRequest | null>(null);
  const [designUnknown, setDesignUnknown] = useState(false);
  const designController = useRef<AbortController | null>(null);
  const designEpoch = useRef(0);
  const { locale, copy } = useMuseLanguage();
  const controller = useRef(new AbortController());

  useEffect(() => {
    const lifetime = new AbortController();
    controller.current = lifetime;
    return () => lifetime.abort();
  }, []);

  // Session, project or revision changes invalidate Muse generation state.
  useEffect(() => {
    designEpoch.current += 1;
    designController.current?.abort();
    designController.current = null;
    setDesignConsented(false);
    setDesignResult(null);
    setDesignFailure(null);
    setDesignNotice(null);
    setDesignPending(null);
    setDesignUnknown(false);
    setDesignBusy(false);
  }, [token, project.id, project.revision_id]);

  useEffect(
    () => () => {
      designEpoch.current += 1;
      designController.current?.abort();
    },
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setListError("");
    setActivationStale(false);
    setActivationError("");
    void listPlans(token, project.id, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setPlans(result.plans);
        // A newly activated version (approval or repair) replaces the
        // selection; otherwise keep the plan the builder was viewing.
        const activeChanged = shownActive.current !== project.active_version_id;
        shownActive.current = project.active_version_id;
        setSelected((current) =>
          !activeChanged &&
          result.plans.some((plan) => plan.version_id === current)
            ? current
            : (project.active_version_id ??
              result.plans[0]?.version_id ??
              null),
        );
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setListError(message(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [
    token,
    project.id,
    project.revision_id,
    project.active_version_id,
    attempt,
  ]);

  useEffect(() => {
    const controller = new AbortController();
    setVersion(null);
    setPlanError("");
    setStep(0);
    setApproved(false);
    if (selected)
      void loadPlan(token, project.id, selected, controller.signal)
        .then((next) => {
          if (!controller.signal.aborted) setVersion(next);
        })
        .catch((error: unknown) => {
          if (!controller.signal.aborted) setPlanError(message(error));
        });
    return () => controller.abort();
  }, [token, project.id, selected, attempt]);

  function cancelDesign() {
    designEpoch.current += 1;
    designController.current?.abort();
    designController.current = null;
    setDesignBusy(false);
    setDesignFailure(null);
    setDesignUnknown(true);
    setDesignNotice("design-cancelled");
  }

  async function runDesign(body: DesignGenerateRequest) {
    if (
      designBusy ||
      approvalDisabled ||
      pending !== null ||
      museAvailability?.enabled === false
    )
      return;
    // Consent covers this one request only: consume it on dispatch so any
    // later success, failure or cancellation requires a fresh opt-in. The
    // in-flight request keeps the body captured by the caller unchanged.
    setDesignConsented(false);
    const requestEpoch = ++designEpoch.current;
    const requestController = new AbortController();
    designController.current = requestController;
    const requestProject = project.id;
    const requestRevision = project.revision_id;
    setDesignPending(body);
    setDesignUnknown(false);
    setDesignBusy(true);
    setDesignFailure(null);
    setDesignNotice(null);
    setDesignResult(null);
    try {
      const next = await generateDesign(
        token,
        requestProject,
        body,
        requestController.signal,
      );
      if (
        requestController.signal.aborted ||
        requestEpoch !== designEpoch.current ||
        next.project_id !== requestProject ||
        next.inventory_revision_id !== requestRevision
      )
        return;
      setDesignResult(next);
      setDesignPending(null);
      setDesignUnknown(false);
      const accepted = (next.candidates ?? []).find(
        (candidate) => candidate.status === "accepted" && candidate.version,
      );
      if (accepted?.version) setSelected(accepted.version.version_id);
      setAttempt((value) => value + 1);
    } catch (error) {
      if (
        requestController.signal.aborted ||
        requestEpoch !== designEpoch.current
      )
        return;
      if (error instanceof ApiError && error.code === "cancelled") {
        setDesignUnknown(true);
        setDesignNotice("design-cancelled");
        return;
      }
      if (
        error instanceof ApiError &&
        [
          "timeout",
          "network_error",
          "generation_in_progress",
          "generation_outcome_unknown",
          "request_timeout",
          "connection_failed",
        ].includes(error.code)
      )
        setDesignUnknown(true);
      setDesignFailure(
        museStoredFailure({
          code: error instanceof ApiError ? error.code : undefined,
          apiMessage: error instanceof ApiError ? error.message : undefined,
          fallbackSection: "design",
        }),
      );
      if (
        error instanceof ApiError &&
        error.status >= 400 &&
        error.status < 500 &&
        error.code !== "generation_in_progress" &&
        error.code !== "generation_outcome_unknown"
      )
        setDesignPending(null);
    } finally {
      if (
        !requestController.signal.aborted &&
        requestEpoch === designEpoch.current
      ) {
        designController.current = null;
        setDesignBusy(false);
      }
    }
  }

  function startNewDesignRequest() {
    // Explicit fresh start only: discard the old key, reset consent, and let
    // the user consent again before Generate creates a fresh key.
    setDesignPending(null);
    setDesignUnknown(false);
    setDesignFailure(null);
    setDesignConsented(false);
    setDesignNotice("design-new-request");
  }

  function retryDesign() {
    // Retrying may start a provider run when the previous request failed
    // before dispatch was recorded, so it needs a fresh consent too. The
    // saved body and its idempotency key are reused unchanged.
    if (
      !designConsented ||
      !designPending ||
      designUnknown ||
      museAvailability?.enabled === false
    )
      return;
    void runDesign(designPending);
  }

  function startDesign() {
    if (
      !designConsented ||
      designPending !== null ||
      designUnknown ||
      museAvailability?.enabled === false
    )
      return;
    const notes = designNotes.trim();
    void runDesign({
      expected_revision_id: project.revision_id,
      ...(notes ? { user_notes: notes } : {}),
      idempotency_key: crypto.randomUUID(),
      provider_context_consented: true,
    });
  }

  async function approve(request: { versionId: string; body: PlanActivation }) {
    if (saving || approvalDisabled) return;
    setPending(request);
    setSaving(true);
    onLockChange(true);
    setActivationError("");
    setActivationStale(false);
    const signal = controller.current.signal;
    try {
      const result = await activatePlan(
        token,
        project.id,
        request.versionId,
        request.body,
        signal,
      );
      if (signal.aborted) return;
      setPending(null);
      setApproved(false);
      onLockChange(false);
      onActivated(result.project);
    } catch (error) {
      if (signal.aborted) return;
      setActivationError(message(error));
      if (
        error instanceof ApiError &&
        error.status >= 400 &&
        error.status < 500
      ) {
        setPending(null);
        onLockChange(false);
        setActivationStale(error.status === 409);
      }
    } finally {
      if (!signal.aborted) setSaving(false);
    }
  }

  const panel = version?.manual.panels[step];
  const current = version?.version_id === project.active_version_id;
  const stale =
    version !== null && version.inventory_revision_id !== project.revision_id;
  const canApprove =
    version !== null &&
    !project.active_version_id &&
    !stale &&
    !activationStale;
  const designDisabled =
    !designConsented ||
    designBusy ||
    designPending !== null ||
    designUnknown ||
    approvalDisabled ||
    pending !== null ||
    museAvailability?.enabled === false ||
    project.active_version_id !== null;
  return (
    <section
      className="plan-workbench"
      aria-labelledby="plans-title"
      aria-busy={loading || saving}
    >
      <div className="section-title">
        <span aria-hidden="true">3</span>
        <h2 id="plans-title">Review your plan and manual</h2>
      </div>
      <p>
        Review a compiled plan before approving it. Browsing steps does not
        record physical work.
      </p>
      <div aria-live="polite">
        {loading && <p>Loading saved plans…</p>}
        {listError && (
          <p className="error" role="alert">
            {listError}
          </p>
        )}
        {planError && (
          <p className="error" role="alert">
            {planError}
          </p>
        )}
        {activationError && (
          <p className="error" role="alert">
            {activationError}
          </p>
        )}
      </div>
      <button
        type="button"
        className="secondary"
        disabled={
          loading || pending !== null || progressPending || approvalDisabled
        }
        onClick={() => setAttempt((value) => value + 1)}
      >
        Refresh saved plans
      </button>
      <div className="muse-design" lang={locale}>
        <h3>{copy.design.title}</h3>
        <p>{copy.design.intro}</p>
        <label htmlFor="design-notes">{copy.design.notesLabel}</label>
        <textarea
          id="design-notes"
          value={designNotes}
          maxLength={1000}
          disabled={designBusy}
          onChange={(event) => setDesignNotes(event.target.value)}
        />
        {museAvailability?.enabled === false && (
          <p className="help" role="note">
            {locale === "es"
              ? copy.provider.notConfiguredReason
              : museAvailability.reason}
          </p>
        )}
        <label className="checkbox-label" htmlFor="design-consent">
          <input
            id="design-consent"
            type="checkbox"
            checked={designConsented}
            disabled={designBusy || museAvailability?.enabled === false}
            onChange={(event) => setDesignConsented(event.target.checked)}
          />
          {copy.design.consent}
        </label>
        {project.active_version_id && (
          <p className="help">{copy.design.activeHelp}</p>
        )}
        <div className="muse-actions">
          <button
            type="button"
            className="primary"
            disabled={designDisabled}
            onClick={startDesign}
          >
            {copy.design.generate}
          </button>
        </div>
        <MuseRequestStatus
          busy={designBusy}
          pendingMessage={copy.design.pending}
          onCancel={cancelDesign}
          cancelledMessage={museNoticeText(designNotice, locale)}
          errorCode={designFailure?.code}
          errorMessage={
            designFailure ? museFailureText(designFailure, locale) : undefined
          }
          diagnostics={
            designResult
              ? museDiagnosticsFromResult(designResult.diagnostics)
              : null
          }
          locale={locale}
        />
        {designPending && !designBusy && designUnknown && (
          <aside className="retry-panel" lang={locale}>
            <h3>{copy.design.unknownTitle}</h3>
            <p>{copy.design.unknownBody}</p>
            <button
              type="button"
              className="secondary"
              disabled={approvalDisabled}
              onClick={() => setAttempt((value) => value + 1)}
            >
              {copy.design.checkPreviews}
            </button>{" "}
            <button
              type="button"
              disabled={approvalDisabled || pending !== null}
              onClick={startNewDesignRequest}
            >
              {copy.design.startNew}
            </button>
          </aside>
        )}
        {designPending && !designBusy && !designUnknown && (
          <aside className="retry-panel" lang={locale}>
            <h3>{copy.design.retryTitle}</h3>
            <p>{copy.design.retryBody}</p>
            <button
              type="button"
              className="secondary"
              disabled={approvalDisabled}
              onClick={() => setAttempt((value) => value + 1)}
            >
              {copy.design.checkPreviews}
            </button>{" "}
            <button
              type="button"
              disabled={
                !designConsented ||
                approvalDisabled ||
                pending !== null ||
                museAvailability?.enabled === false
              }
              onClick={retryDesign}
            >
              {copy.design.retrySame}
            </button>
          </aside>
        )}
        {designResult && (
          <div className="muse-result">
            <h3>{copy.design.resultTitle}</h3>
            <p>
              {copy.design.status} {designResult.status.replaceAll("_", " ")}.{" "}
              {copy.design.statusNote}
            </p>
            {(designResult.questions ?? []).length > 0 && (
              <>
                <h4>{copy.design.questions}</h4>
                <ul>
                  {(designResult.questions ?? []).map((question, index) => (
                    <li key={`${index}-${question}`}>{question}</li>
                  ))}
                </ul>
              </>
            )}
            {(designResult.blockers ?? []).length > 0 && (
              <>
                <h4>{copy.design.blockers}</h4>
                <ul>
                  {(designResult.blockers ?? []).map((blocker, index) => (
                    <li key={`${index}-${blocker.code}`}>{blocker.message}</li>
                  ))}
                </ul>
              </>
            )}
            {(designResult.candidates ?? []).length > 0 && (
              <ul>
                {(designResult.candidates ?? []).map((candidate) => (
                  <li key={candidate.candidate_id}>
                    {candidate.candidate_id}:{" "}
                    {candidate.status.replaceAll("_", " ")}
                    {candidate.version
                      ? ` — ${copy.design.savedPreview} ${candidate.version.version_id}`
                      : ""}
                    {(candidate.blockers ?? []).length > 0 && (
                      <ul>
                        {(candidate.blockers ?? []).map((blocker, index) => (
                          <li key={`${index}-${blocker.code}`}>
                            {blocker.message}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      {!project.active_version_id && (
        <DesignCandidates
          token={token}
          context={{
            projectId: project.id,
            inventoryRevisionId: project.revision_id,
            activeVersionId: null,
            lastEventId: null,
          }}
          disabled={approvalDisabled || pending !== null || saving}
          museEnabled={museAvailability?.enabled !== false}
          onSelected={(versionId) => {
            setSelected(versionId);
            setAttempt((value) => value + 1);
          }}
        />
      )}
      {!loading && !listError && plans.length === 0 && (
        <p className="empty-note" lang={locale}>
          {copy.design.noPlan}
        </p>
      )}
      {plans.length > 0 && (
        <>
          <label htmlFor="plan-version">Saved plan</label>
          <select
            id="plan-version"
            value={selected ?? ""}
            disabled={pending !== null || progressPending}
            onChange={(event) => {
              setSelected(event.target.value);
              setActivationError("");
              setActivationStale(false);
            }}
          >
            {plans.map((plan) => (
              <option value={plan.version_id} key={plan.version_id}>
                {plan.version_id === project.active_version_id
                  ? "Active plan"
                  : project.active_version_id
                    ? "Not active"
                    : "Preview"}{" "}
                · {plan.candidate_id} · {plan.version_id}
              </option>
            ))}
          </select>
        </>
      )}
      {version && (
        <>
          <p className="plan-state">
            <strong>{current ? "Active plan" : "Plan preview"}</strong> ·
            {current
              ? "User-reported physical progress below"
              : "Physical verification not attempted"}
          </p>
          {!current && (
            <p className="help">
              Preview only. Approve a current plan before starting physical
              work.
            </p>
          )}
          {stale && (
            <p className="error">
              These instructions use an older inventory revision. A new preview
              is required before approval.
            </p>
          )}
          {panel && (
            <article className="manual-step">
              <nav className="drawing-index" aria-label="Assembly drawings">
                {version.manual.panels.map((drawing, index) => (
                  <button
                    type="button"
                    key={drawing.operation_id}
                    aria-current={index === step ? "step" : undefined}
                    aria-label={`Open drawing for step ${index + 1}`}
                    disabled={progressPending}
                    onClick={() => setStep(index)}
                  >
                    {String(index + 1).padStart(2, "0")}
                  </button>
                ))}
              </nav>
              <h3 tabIndex={-1}>
                Step {step + 1} of {version.manual.panels.length} —{" "}
                {operationTitles[
                  version.plan.operations.find(
                    (operation) => operation.id === panel.operation_id,
                  )?.type ?? ""
                ] ?? "Assembly step"}
              </h3>
              <p>{panel.instruction}</p>
              <Diagram
                key={`${version.version_id}:${panel.operation_id}`}
                panel={panel}
              />
              <p>
                <strong>Operation:</strong> {panel.operation_id}
              </p>
              <p>
                <strong>Parts:</strong>{" "}
                {panel.part_ids.join(", ") || "See stock layout"}
              </p>
              <p>
                <strong>Tools:</strong> {panel.tools.join(", ")}
              </p>
              <ul>
                {version.plan.checkpoints
                  .filter((checkpoint) =>
                    panel.checkpoint_ids.includes(checkpoint.id),
                  )
                  .map((checkpoint) => (
                    <li key={checkpoint.id}>
                      {checkpoint.description}{" "}
                      <span className="help">
                        ({checkpoint.method.replaceAll("_", " ")})
                      </span>
                    </li>
                  ))}
              </ul>
              <div className="manual-navigation">
                <button
                  type="button"
                  disabled={step === 0 || progressPending}
                  onClick={() => setStep((value) => value - 1)}
                >
                  Previous step
                </button>
                <span aria-live="polite">
                  Step {step + 1} / {version.manual.panels.length}
                </span>
                <button
                  type="button"
                  disabled={
                    step + 1 >= version.manual.panels.length || progressPending
                  }
                  onClick={() => setStep((value) => value + 1)}
                >
                  Next step
                </button>
              </div>
              {current && (
                <PhysicalProgress
                  key={version.version_id}
                  token={token}
                  projectId={project.id}
                  version={version}
                  operationId={panel.operation_id}
                  photos={photos}
                  disabled={
                    approvalDisabled || pending !== null || measurementPending
                  }
                  onReloadProject={onReload}
                  onProgressChange={handleProgressChange}
                  onDiagnoseFailure={onDiagnoseFailure}
                  museAvailability={museAvailability}
                  refreshKey={(diagnosisRefreshKey ?? 0) + measurementRefresh}
                  onLockChange={(locked) => {
                    setProgressPending(locked);
                    onLockChange(locked);
                  }}
                />
              )}
            </article>
          )}
          {current && version && (
            <AssemblyView
              key={`assembly:${project.id}:${version.version_id}`}
              token={token}
              projectId={project.id}
              planVersionId={version.version_id}
              inventoryRevisionId={project.revision_id}
              refreshKey={
                stabilityRefresh +
                measurementRefresh +
                (diagnosisRefreshKey ?? 0)
              }
              selectedOperationId={panel?.operation_id ?? null}
              disabled={
                approvalDisabled ||
                pending !== null ||
                progressPending ||
                measurementPending
              }
              onSelectOperation={(operationId) => {
                const index = version.manual.panels.findIndex(
                  (item) => item.operation_id === operationId,
                );
                if (index >= 0) setStep(index);
              }}
            />
          )}
          {current && version && (
            <StabilityReportPanel
              key={`${project.id}:${version.version_id}`}
              token={token}
              projectId={project.id}
              planVersionId={version.version_id}
              inventoryRevisionId={project.revision_id}
              refreshKey={stabilityRefresh + (diagnosisRefreshKey ?? 0)}
              onMeasurementsSaved={handleMeasurementsSaved}
              onMeasurementLockChange={setMeasurementPending}
              disabled={approvalDisabled || pending !== null || progressPending}
            />
          )}
          {current && (
            <FabricationReportPanel
              token={token}
              projectId={project.id}
              plan={version.plan}
              source={{ kind: "version", versionId: version.version_id }}
              refreshKey={fabricationKey}
              onShowOperation={(operationId) => {
                const index = version.manual.panels.findIndex(
                  (item) => item.operation_id === operationId,
                );
                if (index >= 0) setStep(index);
              }}
            />
          )}
          {current && (
            <AdaptWorkbench
              token={token}
              projectId={project.id}
              version={version}
              disabled={
                approvalDisabled ||
                pending !== null ||
                progressPending ||
                measurementPending
              }
              onApproved={onReload}
              onLockChange={onLockChange}
              handoff={repairHandoff?.handoff ?? null}
              handoffTargetId={repairHandoff?.targetId}
              museAvailability={museAvailability}
            />
          )}
          <details className="manual-materials">
            <summary>Materials and planned quantities</summary>
            <ul>
              {version.manual.bill_of_materials.map((item) => (
                <li key={item.id}>
                  {item.description}:{" "}
                  {item.quantity === null
                    ? "Unknown"
                    : `${item.quantity} ${item.unit}`}{" "}
                  · {item.stock_id}
                </li>
              ))}
            </ul>
            <p className="help">
              Planned quantities do not record actual consumption or remaining
              physical stock.
            </p>
          </details>
          {version.plan.parts.length > 0 && (
            <details className="manual-materials">
              <summary>Planned parts ({version.plan.parts.length})</summary>
              <ul className="part-files">
                {version.plan.parts.map((part, index) => (
                  <li key={part.id}>
                    <span className="part-file-tab">
                      Part {String(index + 1).padStart(2, "0")}
                    </span>
                    <div className="part-file-body">
                      <strong>{part.id}</strong>
                      <span>
                        {part.geometry.width} × {part.geometry.height} mm
                      </span>
                      <span>Stock {part.source_stock_id}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {canApprove && (
            <div className="plan-approval">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={approved}
                  disabled={approvalDisabled || pending !== null}
                  onChange={(event) => setApproved(event.target.checked)}
                />
                I reviewed this plan and its required physical checks.
              </label>
              <button
                type="button"
                className="primary"
                disabled={!approved || approvalDisabled || pending !== null}
                onClick={() =>
                  void approve({
                    versionId: version.version_id,
                    body: {
                      expected_revision_id: project.revision_id,
                      idempotency_key: crypto.randomUUID(),
                      user_approved: true,
                    },
                  })
                }
              >
                Approve this plan
              </button>
              <p className="help">
                Approval fixes the plan for this inventory. It does not mark
                cuts, assembly or tests complete.
              </p>
            </div>
          )}
        </>
      )}
      {pending && !saving && (
        <aside className="retry-panel">
          <h3>Check the approval result</h3>
          <p>
            The connection ended before the result was known. Retry the same
            approval to check its outcome.
          </p>
          <button
            type="button"
            disabled={approvalDisabled}
            onClick={() => void approve(pending)}
          >
            Retry plan approval
          </button>
        </aside>
      )}
      {activationStale && (
        <button
          type="button"
          className="secondary"
          disabled={approvalDisabled}
          onClick={onReload}
        >
          Reload project before reviewing again
        </button>
      )}
    </section>
  );
}
