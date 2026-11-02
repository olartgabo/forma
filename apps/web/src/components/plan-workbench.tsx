import { useEffect, useRef, useState } from "react";
import { activatePlan, ApiError, listPlans, loadPlan } from "../lib/api";
import PhysicalProgress from "./physical-progress";
import type {
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
  photos,
}: {
  token: string;
  project: Project;
  approvalDisabled: boolean;
  onLockChange: (locked: boolean) => void;
  onActivated: (next: Project) => void;
  onReload: () => void;
  photos: readonly Media[];
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
  const [progressPending, setProgressPending] = useState(false);
  const [activationError, setActivationError] = useState("");
  const [activationStale, setActivationStale] = useState(false);
  const controller = useRef(new AbortController());

  useEffect(() => {
    const lifetime = new AbortController();
    controller.current = lifetime;
    return () => lifetime.abort();
  }, []);

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
      {!loading && !listError && plans.length === 0 && (
        <p className="empty-note">
          No compiled plan has been saved for this project yet. Your materials
          and requirements are saved; design generation is still being
          connected.
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
                  disabled={approvalDisabled || pending !== null}
                  onReloadProject={onReload}
                  onLockChange={(locked) => {
                    setProgressPending(locked);
                    onLockChange(locked);
                  }}
                />
              )}
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
