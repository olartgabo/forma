"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, loadDesignReadiness } from "../lib/api";
import type { DesignReadiness, Project } from "../lib/generated/api-contracts";

function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "The request could not finish. Check the API connection and try again.";
}

export default function DesignReadinessPanel({
  token,
  project,
  inventoryStale,
}: {
  token: string;
  project: Project;
  inventoryStale: boolean;
}) {
  const [readiness, setReadiness] = useState<DesignReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const epoch = useRef(0);
  const projectId = project.id;
  const revisionId = project.revision_id;

  useEffect(() => {
    const requestEpoch = ++epoch.current;
    const controller = new AbortController();
    setReadiness(null);
    setError("");
    setLoading(true);
    void loadDesignReadiness(token, projectId, revisionId, controller.signal)
      .then((result) => {
        if (controller.signal.aborted || requestEpoch !== epoch.current) return;
        setReadiness(result);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted && requestEpoch === epoch.current)
          setError(errorMessage(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted && requestEpoch === epoch.current)
          setLoading(false);
      });
    return () => {
      epoch.current += 1;
      controller.abort();
    };
  }, [token, projectId, revisionId, attempt]);

  return (
    <section className="muse-panel" aria-labelledby="readiness-title">
      <h2 id="readiness-title">Saved input checklist</h2>
      <p>
        This read-only checklist reflects the last saved inventory revision. It
        does not call Muse, change inventory, approve a plan or record physical
        work. A complete checklist only means no checklist inputs are missing;
        it does not mean a plan is compiled or any physical check has passed.
      </p>
      {inventoryStale && (
        <p className="error" role="alert">
          Materials or requirements have unsaved or stale changes. This
          checklist still describes saved revision {revisionId} only, not your
          unsaved edits.
        </p>
      )}
      <p className="help">
        Project {projectId} · Saved inventory revision {revisionId}
      </p>
      <div aria-live="polite">
        {loading && <p className="help">Checking saved inputs…</p>}
        {error && (
          <div className="error" role="alert">
            <p>{error}</p>
            <button
              type="button"
              className="secondary"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Recheck saved inputs
            </button>
          </div>
        )}
      </div>
      {readiness && (
        <div className="muse-result">
          <p>
            <strong>
              {readiness.status === "inputs_complete"
                ? "Checklist complete for the saved revision."
                : "More saved inputs are needed."}
            </strong>{" "}
            Inventory{" "}
            {readiness.inventory_confirmed ? "confirmed" : "not confirmed"}.
          </p>
          {readiness.missing_inputs.length > 0 && (
            <>
              <h3>Missing inputs</h3>
              <ul>
                {readiness.missing_inputs.map((input, index) => (
                  <li key={`${index}-${input}`}>{input}</li>
                ))}
              </ul>
            </>
          )}
          {readiness.blockers.length > 0 && (
            <>
              <h3>Blockers</h3>
              <ul>
                {readiness.blockers.map((blocker, index) => (
                  <li key={`${index}-${blocker.code}`}>
                    {blocker.message} ({blocker.code})
                  </li>
                ))}
              </ul>
            </>
          )}
          <button
            type="button"
            className="secondary"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Recheck saved inputs
          </button>
        </div>
      )}
    </section>
  );
}
