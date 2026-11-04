"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, listSavedProjects } from "../lib/api";
import type { SavedProjectSummary } from "../lib/generated/api-contracts";
import { workbenchCopy } from "../lib/workbench-language";
import { useMuseLanguage } from "./muse-language-provider";
import styles from "./saved-projects-panel.module.css";

const PAGE_SIZE = 20;

function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "The request could not finish. Check the API connection and try again.";
}

export default function SavedProjectsPanel({
  token,
  disabled,
  onOpen,
}: {
  token: string;
  disabled: boolean;
  onOpen: (id: string) => void;
}) {
  const { locale } = useMuseLanguage();
  const copy = workbenchCopy[locale];
  const [projects, setProjects] = useState<readonly SavedProjectSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const epoch = useRef(0);
  const moreController = useRef<AbortController | null>(null);

  useEffect(() => {
    const requestEpoch = ++epoch.current;
    const controller = new AbortController();
    setProjects([]);
    setNextCursor(null);
    setError("");
    setLoading(true);
    setLoadingMore(false);
    void listSavedProjects(token, { limit: PAGE_SIZE }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted || requestEpoch !== epoch.current) return;
        setProjects(result.projects);
        setNextCursor(result.next_cursor ?? null);
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
      moreController.current?.abort();
      moreController.current = null;
    };
  }, [token, attempt]);

  async function loadMore() {
    if (!nextCursor || loadingMore || loading) return;
    const requestEpoch = epoch.current;
    const controller = new AbortController();
    moreController.current = controller;
    setLoadingMore(true);
    setError("");
    try {
      const result = await listSavedProjects(
        token,
        { limit: PAGE_SIZE, cursor: nextCursor },
        controller.signal,
      );
      if (controller.signal.aborted || requestEpoch !== epoch.current) return;
      setProjects((current) => {
        const seen = new Set(current.map((project) => project.id));
        return [
          ...current,
          ...result.projects.filter((project) => !seen.has(project.id)),
        ];
      });
      setNextCursor(result.next_cursor ?? null);
    } catch (failure) {
      if (!controller.signal.aborted && requestEpoch === epoch.current)
        setError(errorMessage(failure));
    } finally {
      if (moreController.current === controller) moreController.current = null;
      if (!controller.signal.aborted && requestEpoch === epoch.current)
        setLoadingMore(false);
    }
  }

  return (
    <div>
      <h3>{copy.saved}</h3>
      <div aria-live="polite">
        {loading && (
          <>
            <p className="help">{copy.loadingSaved}</p>
            <ul className={styles.skeleton} aria-hidden="true">
              {[1, 2].map((row) => (
                <li key={row}>
                  <span />
                  <span />
                </li>
              ))}
            </ul>
          </>
        )}
        {error && (
          <div className="error" role="alert">
            <p lang="en">{error}</p>
            <button
              type="button"
              className="secondary"
              onClick={() => setAttempt((value) => value + 1)}
            >
              {copy.reloadSaved}
            </button>
          </div>
        )}
      </div>
      {!loading && !error && projects.length === 0 && (
        <p className="empty-note">{copy.emptySaved}</p>
      )}
      {projects.length > 0 && (
        <ul>
          {projects.map((project) => (
            <li key={project.id}>
              <p>
                <strong>{project.goal}</strong>
                <br />
                <span className="help">
                  {copy.projectId} {project.id} · {copy.revision}{" "}
                  {project.revision_id} ·{" "}
                  {project.inventory_confirmed
                    ? copy.confirmed
                    : copy.unconfirmed}
                  {project.active_version_id
                    ? ` · ${copy.active} ${project.active_version_id}`
                    : ` · ${copy.noActive}`}
                </span>
              </p>
              <button
                type="button"
                className="secondary"
                disabled={disabled}
                onClick={() => onOpen(project.id)}
              >
                {copy.openSaved(project.id)}
              </button>
            </li>
          ))}
        </ul>
      )}
      {nextCursor && (
        <button
          type="button"
          className="secondary"
          disabled={disabled || loadingMore}
          onClick={() => void loadMore()}
        >
          {loadingMore ? copy.loadingMore : copy.more}
        </button>
      )}
    </div>
  );
}
