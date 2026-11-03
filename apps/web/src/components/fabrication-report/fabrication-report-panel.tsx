"use client";

import { useEffect, useId, useState } from "react";
import {
  ApiError,
  loadFabricationReport,
  loadPreviewFabricationReport,
  assessFabricationReport,
} from "../../lib/api";
import {
  fabricationStatusText,
  orderText,
  readinessGroups,
  toolText,
} from "../../lib/fabrication-report";
import type {
  FabricationReport,
  OperationReadiness,
  FabricationAssessment,
} from "../../lib/generated/api-contracts";
import type { BuildPlan } from "../../lib/generated/contracts";
import { operationTitles } from "../../lib/operation-titles";
import ReportAssessmentForm from "./report-assessment-form";

export type FabricationSource =
  | { kind: "version"; versionId: string }
  | { kind: "preview"; previewId: string; versionId: string };

function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "The step check could not load. Check the API connection and try again.";
}

function title(plan: BuildPlan, operationId: string) {
  const type = plan.operations.find((op) => op.id === operationId)?.type ?? "";
  return `${operationTitles[type] ?? "Assembly step"} (${operationId})`;
}

function Reasons({ operation }: { operation: OperationReadiness }) {
  return (
    <ul>
      {operation.blockers.map((blocker, index) => (
        <li key={`${index}-${blocker.code}`}>{blocker.message}</li>
      ))}
      {operation.waiting_on_operation_ids.length > 0 && (
        <li>Waits for {operation.waiting_on_operation_ids.join(", ")}.</li>
      )}
    </ul>
  );
}

export default function FabricationReportPanel({
  token,
  projectId,
  plan,
  source,
  refreshKey = 0,
  onShowOperation,
}: {
  token: string;
  projectId: string;
  plan: BuildPlan;
  source: FabricationSource;
  refreshKey?: number;
  onShowOperation?: (operationId: string) => void;
}) {
  const [loaded, setLoaded] = useState<{
    key: string;
    report?: FabricationReport;
    error?: string;
  } | null>(null);
  const [assessment, setAssessment] = useState<{
    context: string;
    body: FabricationAssessment;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const { kind, versionId } = source;
  const previewId = source.kind === "preview" ? source.previewId : null;
  const context = JSON.stringify([
    token,
    projectId,
    versionId,
    previewId,
    refreshKey,
  ]);
  const body = assessment?.context === context ? assessment.body : null;
  const requestKey = JSON.stringify([context, attempt, body]);
  const serialized = body === null ? null : JSON.stringify(body);

  useEffect(() => {
    const controller = new AbortController();
    const loaded =
      previewId === null
        ? serialized === null
          ? loadFabricationReport(
              token,
              projectId,
              versionId,
              controller.signal,
            )
          : assessFabricationReport(
              token,
              projectId,
              versionId,
              JSON.parse(serialized),
              controller.signal,
            )
        : loadPreviewFabricationReport(
            token,
            projectId,
            previewId,
            versionId,
            controller.signal,
          );
    void loaded
      .then((result) => {
        if (controller.signal.aborted) return;
        setLoaded({ key: requestKey, report: result });
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setLoaded({ key: requestKey, error: errorMessage(failure) });
      });
    return () => {
      controller.abort();
    };
  }, [token, projectId, versionId, previewId, serialized, requestKey]);

  const current = loaded?.key === requestKey ? loaded : null;
  const report = current?.report;
  const error = current?.error;
  const loading = current === null;

  const groups = report ? readinessGroups(report) : null;
  const next = groups?.next ?? null;
  const heading =
    kind === "preview" ? "If approved, next step" : "Next step check";
  const headingId = useId();

  return (
    <section
      className="fabrication-report"
      aria-labelledby={headingId}
      aria-busy={loading}
    >
      <h4 id={headingId}>{heading}</h4>
      <p className="help">
        Worked out from the saved plan, the steps you reported and FORMA&apos;s
        declared tool and access rules. It does not record work, approve a
        repair or authorize cutting, and it does not show that a step will work
        physically.
      </p>
      <div aria-live="polite">
        {loading && <p className="help">Checking which step can come next…</p>}
        {error && (
          <div className="error" role="alert">
            <p>{error}</p>
            <button
              type="button"
              className="secondary"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Check again
            </button>
          </div>
        )}
      </div>
      {body !== null && (
        <p className="help">
          Using your confirmed inputs for this report only.{" "}
          <button
            type="button"
            className="secondary"
            onClick={() => setAssessment(null)}
          >
            Clear report confirmations
          </button>
        </p>
      )}
      {report && groups && (
        <>
          <p>
            <strong>{fabricationStatusText[report.status]}</strong>
          </p>
          {report.blockers.length > 0 && (
            <>
              <h5>Blocking the whole build</h5>
              <ul>
                {report.blockers.map((blocker, index) => (
                  <li key={`${index}-${blocker.code}`}>{blocker.message}</li>
                ))}
              </ul>
            </>
          )}
          {next && (
            <div className="fabrication-next">
              <p>
                <strong>Next:</strong> {title(plan, next.operation_id)}
              </p>
              {next.tools.length > 0 && (
                <ul aria-label="Tools for this step">
                  {next.tools.map((tool) => (
                    <li key={tool.tool}>{toolText(tool)}</li>
                  ))}
                </ul>
              )}
              {next.required_confirmations.length > 0 && (
                <>
                  <h5>Confirm before you start</h5>
                  <ul>
                    {next.required_confirmations.map((text, index) => (
                      <li key={`${index}-${text}`}>{text}</li>
                    ))}
                  </ul>
                </>
              )}
              {onShowOperation && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onShowOperation(next.operation_id)}
                >
                  Show this step in the manual
                </button>
              )}
            </div>
          )}
          <p className="help">{orderText(report)}</p>
          {report.order_blockers.length > 0 && (
            <ul>
              {report.order_blockers.map((blocker, index) => (
                <li key={`${index}-${blocker.code}`}>{blocker.message}</li>
              ))}
            </ul>
          )}
          {(groups.blocked.length > 0 ||
            groups.waiting.length > 0 ||
            groups.ready.length > 0) && (
            <details>
              <summary>Why the other remaining steps are not next</summary>
              <ul>
                {[...groups.ready, ...groups.blocked, ...groups.waiting].map(
                  (operation) => (
                    <li key={operation.operation_id}>
                      {title(plan, operation.operation_id)}:{" "}
                      {operation.status === "ready"
                        ? "can also be attempted now"
                        : operation.status === "waiting"
                          ? "waiting"
                          : "blocked"}
                      <Reasons operation={operation} />
                    </li>
                  ),
                )}
              </ul>
            </details>
          )}
          <p className="help">
            {groups.completed} step{groups.completed === 1 ? "" : "s"} recorded
            as done · Plan {report.snapshot.version_id} · Last report{" "}
            {report.snapshot.last_event_id ?? "none yet"}
          </p>
        </>
      )}
      {report && kind === "version" && body === null && (
        <ReportAssessmentForm
          key={report.snapshot.inputs_sha256}
          report={report}
          onAssess={(body) => setAssessment({ context, body })}
        />
      )}
      <button
        type="button"
        className="secondary"
        disabled={loading}
        onClick={() => {
          setAssessment(null);
          setAttempt((value) => value + 1);
        }}
      >
        Refresh step check
      </button>
    </section>
  );
}
