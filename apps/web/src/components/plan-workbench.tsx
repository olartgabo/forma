import { useEffect, useRef, useState } from "react";
import {
  activatePlan,
  ApiError,
  generateDesign,
  listPlans,
  loadPlan,
} from "../lib/api";
import type {
  DesignGenerateRequest,
  DesignGenerateResult,
  ManualPanel,
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

function Diagram({ panel }: { panel: ManualPanel }) {
  const [url, setUrl] = useState<string | null>(null);
  const [enlarged, setEnlarged] = useState(false);
  useEffect(() => {
    const next = URL.createObjectURL(
      new Blob([panel.svg], { type: "image/svg+xml" }),
    );
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [panel.svg]);
  return url ? (
    <>
      <button
        type="button"
        className="quiet"
        aria-expanded={enlarged}
        onClick={() => setEnlarged((value) => !value)}
      >
        {enlarged ? "Fit diagram to screen" : "Enlarge diagram"}
      </button>
      <div
        className={`manual-diagram-frame${enlarged ? " enlarged" : ""}`}
        tabIndex={enlarged ? 0 : undefined}
        role={enlarged ? "region" : undefined}
        aria-label={
          enlarged
            ? "Full-size diagram; scroll to inspect dimensions"
            : undefined
        }
      >
        <img
          className="manual-diagram"
          src={url}
          alt={`Assembly diagram for ${panel.operation_id}. ${panel.instruction}`}
        />
      </div>
    </>
  ) : (
    <p>Loading diagram…</p>
  );
}

const titles: Record<string, string> = {
  cut_rect: "Cut the labelled panels",
  fold: "Fold the retaining lip",
  tape_joint: "Attach the tape hinge",
  inspect: "Inspect the assembly",
  functional_test: "Test the stand",
};

export default function PlanWorkbench({
  token,
  project,
  approvalDisabled,
  onLockChange,
  onActivated,
  onReload,
}: {
  token: string;
  project: Project;
  approvalDisabled: boolean;
  onLockChange: (locked: boolean) => void;
  onActivated: (next: Project) => void;
  onReload: () => void;
}) {
  const [plans, setPlans] = useState<readonly PlanSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [version, setVersion] = useState<PlanVersion | null>(null);
  const [step, setStep] = useState(0);
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
  const [activationError, setActivationError] = useState("");
  const [activationStale, setActivationStale] = useState(false);
  const [designNotes, setDesignNotes] = useState("");
  const [designConsented, setDesignConsented] = useState(false);
  const [designBusy, setDesignBusy] = useState(false);
  const [designResult, setDesignResult] = useState<DesignGenerateResult | null>(
    null,
  );
  const [designError, setDesignError] = useState("");
  const [designNotice, setDesignNotice] = useState("");
  const [designPending, setDesignPending] =
    useState<DesignGenerateRequest | null>(null);
  const designController = useRef<AbortController | null>(null);
  const designEpoch = useRef(0);
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
    setDesignError("");
    setDesignNotice("");
    setDesignPending(null);
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
        setSelected((current) =>
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
    setDesignError("");
    setDesignNotice(
      "Cancelled. FORMA stopped waiting for Muse; Muse may already be processing the request, so check saved previews or retry the same request to learn the outcome.",
    );
  }

  async function runDesign(body: DesignGenerateRequest) {
    if (designBusy || approvalDisabled || pending !== null) return;
    const requestEpoch = ++designEpoch.current;
    const requestController = new AbortController();
    designController.current = requestController;
    const requestProject = project.id;
    const requestRevision = project.revision_id;
    setDesignPending(body);
    setDesignBusy(true);
    setDesignError("");
    setDesignNotice("");
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
        setDesignNotice(
          "Cancelled. FORMA stopped waiting for Muse; Muse may already be processing the request, so check saved previews or retry the same request to learn the outcome.",
        );
        return;
      }
      setDesignError(message(error));
      if (
        error instanceof ApiError &&
        error.status >= 400 &&
        error.status < 500 &&
        error.code !== "generation_in_progress"
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

  function startDesign() {
    if (!designConsented) return;
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
    approvalDisabled ||
    pending !== null ||
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
        disabled={loading || pending !== null || approvalDisabled}
        onClick={() => setAttempt((value) => value + 1)}
      >
        Refresh saved plans
      </button>
      <div className="muse-design">
        <h3>Generate with Muse</h3>
        <p>
          Muse proposes up to two designs from the saved project. FORMA compiles
          and saves only previews that pass its checks. Generating a preview
          does not approve a plan, record physical work or send a photo.
        </p>
        <label htmlFor="design-notes">Notes for Muse (optional)</label>
        <textarea
          id="design-notes"
          value={designNotes}
          maxLength={1000}
          disabled={designBusy}
          onChange={(event) => setDesignNotes(event.target.value)}
        />
        <label className="checkbox-label" htmlFor="design-consent">
          <input
            id="design-consent"
            type="checkbox"
            checked={designConsented}
            disabled={designBusy}
            onChange={(event) => setDesignConsented(event.target.checked)}
          />
          Share this project&apos;s saved goal, materials, requirements and my
          notes above with Meta&apos;s Muse service for this one request. No
          photo is sent by this action.
        </label>
        {project.active_version_id && (
          <p className="help">
            A plan is already active for this project, so Muse generation is
            unavailable until a revision flow is connected.
          </p>
        )}
        <div className="muse-actions">
          <button
            type="button"
            className="primary"
            disabled={designDisabled}
            onClick={startDesign}
          >
            Generate with Muse
          </button>
          {designBusy && (
            <button type="button" className="secondary" onClick={cancelDesign}>
              Cancel
            </button>
          )}
        </div>
        {designBusy && (
          <p className="help" aria-live="polite">
            Asking Muse… Cancelling stops FORMA waiting; it does not guarantee
            Muse stopped. There are no automatic retries.
          </p>
        )}
        {designNotice && (
          <p className="notice" aria-live="polite">
            {designNotice}
          </p>
        )}
        {designError && (
          <p className="error" role="alert">
            {designError}
          </p>
        )}
        {designPending && !designBusy && (
          <aside className="retry-panel">
            <h3>Check the generation result</h3>
            <p>
              The outcome is unknown. Check saved previews first, or retry the
              identical Muse request; FORMA will not start a new paid run
              automatically.
            </p>
            <button
              type="button"
              className="secondary"
              disabled={approvalDisabled}
              onClick={() => setAttempt((value) => value + 1)}
            >
              Check saved previews
            </button>{" "}
            <button
              type="button"
              disabled={approvalDisabled || pending !== null}
              onClick={() => void runDesign(designPending)}
            >
              Retry same Muse request
            </button>
          </aside>
        )}
        {designResult && (
          <div className="muse-result">
            <h3>Muse design result</h3>
            <p>
              Status: {designResult.status.replaceAll("_", " ")}. Saved previews
              below still require separate approval.
            </p>
            {(designResult.questions ?? []).length > 0 && (
              <>
                <h4>Questions to answer</h4>
                <ul>
                  {(designResult.questions ?? []).map((question, index) => (
                    <li key={`${index}-${question}`}>{question}</li>
                  ))}
                </ul>
              </>
            )}
            {(designResult.blockers ?? []).length > 0 && (
              <>
                <h4>Blockers</h4>
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
                      ? ` — saved preview ${candidate.version.version_id}`
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
            <p className="help">
              Request diagnostics — status: {designResult.diagnostics.status};
              model: {designResult.diagnostics.model}; rounds:{" "}
              {designResult.diagnostics.model_rounds}; tool calls:{" "}
              {designResult.diagnostics.tool_executions}; duration:{" "}
              {designResult.diagnostics.elapsed_ms} ms.
            </p>
          </div>
        )}
      </div>
      {!loading && !listError && plans.length === 0 && (
        <p className="empty-note">
          No compiled plan has been saved for this project yet. Your materials
          and requirements are saved; use Generate with Muse above to ask for
          compiled previews.
        </p>
      )}
      {plans.length > 0 && (
        <>
          <label htmlFor="plan-version">Saved plan</label>
          <select
            id="plan-version"
            value={selected ?? ""}
            disabled={pending !== null}
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
            Physical verification not attempted
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
              <h3 tabIndex={-1}>
                Step {step + 1} of {version.manual.panels.length} —{" "}
                {titles[
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
                  disabled={step === 0}
                  onClick={() => setStep((value) => value - 1)}
                >
                  Previous step
                </button>
                <span aria-live="polite">
                  Step {step + 1} / {version.manual.panels.length}
                </span>
                <button
                  type="button"
                  disabled={step + 1 >= version.manual.panels.length}
                  onClick={() => setStep((value) => value + 1)}
                >
                  Next step
                </button>
              </div>
            </article>
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
