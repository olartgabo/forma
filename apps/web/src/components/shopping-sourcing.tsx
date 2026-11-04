"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, listSavedProjects } from "../lib/api";
import type { SavedProjectSummary } from "../lib/generated/api-contracts";
import SourcingPanel from "./sourcing-panel";

const PAGE_SIZE = 50;
const MAX_PAGES = 10;

export default function ShoppingSourcing({
  token,
  disabled,
  onOpen,
}: {
  token: string;
  disabled: boolean;
  onOpen: (id: string) => void;
}) {
  const [projects, setProjects] = useState<readonly SavedProjectSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [pages, setPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const epoch = useRef(0);
  const moreController = useRef<AbortController | null>(null);
  const cursors = useRef(new Set<string>());

  useEffect(() => {
    const requestEpoch = ++epoch.current;
    const controller = new AbortController();
    setProjects([]);
    setNextCursor(null);
    setPages(0);
    setError("");
    setLoading(true);
    setLoadingMore(false);
    cursors.current.clear();
    void listSavedProjects(token, { limit: PAGE_SIZE }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted || requestEpoch !== epoch.current) return;
        setProjects(result.projects);
        setPages(1);
        setNextCursor(result.next_cursor ?? null);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted && requestEpoch === epoch.current)
          setError(message(failure));
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
    if (!nextCursor || loading || moreController.current || pages >= MAX_PAGES)
      return;
    const cursor = nextCursor;
    const requestEpoch = epoch.current;
    const controller = new AbortController();
    moreController.current = controller;
    setLoadingMore(true);
    setError("");
    try {
      const result = await listSavedProjects(
        token,
        { limit: PAGE_SIZE, cursor },
        controller.signal,
      );
      if (controller.signal.aborted || requestEpoch !== epoch.current) return;
      cursors.current.add(cursor);
      const following = result.next_cursor ?? null;
      if (following && cursors.current.has(following)) {
        setError("The project list changed. Reload it to continue.");
        setNextCursor(null);
      } else setNextCursor(following);
      setProjects((current) => {
        const seen = new Set(current.map((project) => project.id));
        return [
          ...current,
          ...result.projects.filter((project) => !seen.has(project.id)),
        ];
      });
      setPages((value) => value + 1);
    } catch (failure) {
      if (!controller.signal.aborted && requestEpoch === epoch.current)
        setError(message(failure));
    } finally {
      if (moreController.current === controller) moreController.current = null;
      if (!controller.signal.aborted && requestEpoch === epoch.current)
        setLoadingMore(false);
    }
  }

  return (
    <div id="shopping-list">
      <div aria-live="polite">
        {loading && <p className="help">Loading your shopping projects…</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
      {!loading && (
        <button
          type="button"
          className="secondary"
          disabled={disabled || loadingMore}
          onClick={() => setAttempt((value) => value + 1)}
        >
          Reload shopping projects
        </button>
      )}
      {!loading && pages > 0 && (
        <SourcingPanel
          token={token}
          projects={projects}
          disabled={disabled}
          onOpen={onOpen}
        />
      )}
      {nextCursor && pages < MAX_PAGES && (
        <button
          type="button"
          className="secondary"
          disabled={disabled || loadingMore}
          onClick={() => void loadMore()}
        >
          {loadingMore
            ? "Loading more projects…"
            : "Load more shopping projects"}
        </button>
      )}
      {nextCursor && pages >= MAX_PAGES && (
        <p className="help">
          Showing up to 500 projects. Open another project by its saved ID in
          the workbench.
        </p>
      )}
    </div>
  );
}

function message(failure: unknown) {
  return failure instanceof ApiError
    ? failure.message
    : "Could not load your projects. Check the connection and reload the list.";
}
