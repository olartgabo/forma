"use client";

import { useEffect, useRef, useState } from "react";
import type { SavedProjectSummary } from "../lib/generated/api-contracts";
import {
  loadProjectGeometry,
  type ProjectThumbnailData,
} from "../lib/project-geometry-client";
import EngineModelPreview from "./engine-model-preview";
import { savedDrawingThumbnail } from "../lib/saved-drawing-thumbnail";

function SavedDrawing({ svg }: { svg: string }) {
  const [drawing, setDrawing] = useState<{ svg: string; url: string } | null>(
    null,
  );
  useEffect(() => {
    const thumbnail = savedDrawingThumbnail(svg);
    if (!thumbnail) return;
    const url = URL.createObjectURL(
      new Blob([thumbnail], { type: "image/svg+xml" }),
    );
    setDrawing({ svg, url });
    return () => URL.revokeObjectURL(url);
  }, [svg]);
  return drawing?.svg === svg ? (
    <img
      src={drawing.url}
      alt="Saved engine assembly drawing"
      style={{ width: "100%", objectFit: "contain" }}
    />
  ) : null;
}

export default function ProjectThumbnail({
  token,
  project,
}: {
  token: string;
  project: SavedProjectSummary;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [result, setResult] = useState<{
    key: string;
    geometry: ProjectThumbnailData;
  } | null>(null);
  const key = JSON.stringify([
    token,
    project.id,
    project.active_version_id,
    project.revision_id,
  ]);
  useEffect(() => {
    const controller = new AbortController();
    let observer: IntersectionObserver | undefined;
    let started = false;
    const load = () => {
      if (started || !token) return;
      started = true;
      observer?.disconnect();
      void loadProjectGeometry(token, project, controller.signal)
        .then((geometry) => {
          if (!controller.signal.aborted && geometry)
            setResult({ key, geometry });
        })
        .catch(() => {
          /* A failed read stays a quiet placeholder; no automatic retry. */
        });
    };
    if (typeof IntersectionObserver === "undefined") load();
    else if (host.current) {
      observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) load();
        },
        { rootMargin: "100px" },
      );
      observer.observe(host.current);
    }
    return () => {
      controller.abort();
      observer?.disconnect();
    };
  }, [key, token, project.id, project.active_version_id, project.revision_id]);
  return (
    <div ref={host} style={{ width: "100%", height: "100%" }}>
      {result?.key === key ? (
        "svg" in result.geometry ? (
          <SavedDrawing svg={result.geometry.svg} />
        ) : (
          <EngineModelPreview geometry={result.geometry} />
        )
      ) : (
        <svg
          viewBox="0 0 320 200"
          width="100%"
          height="100%"
          aria-hidden="true"
        >
          <path
            d="M32 168H288M32 32V168"
            fill="none"
            stroke="currentColor"
            opacity="0.08"
          />
        </svg>
      )}
    </div>
  );
}
