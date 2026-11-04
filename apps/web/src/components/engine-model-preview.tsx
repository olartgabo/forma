"use client";

import { useId, useMemo } from "react";
import type { EnginePreviewGeometry } from "../lib/engine-model-projection";
import { projectEngineModel } from "../lib/engine-model-projection";

export default function EngineModelPreview({
  geometry,
}: {
  geometry: EnginePreviewGeometry;
}) {
  const id = useId().replace(/:/g, "");
  const facets = useMemo(() => projectEngineModel(geometry), [geometry]);
  return (
    <svg
      className="engine-model-preview"
      viewBox="0 0 360 240"
      width="100%"
      height="100%"
      aria-hidden="true"
      focusable="false"
      data-engine-model={facets ? "ready" : "unavailable"}
      style={{ display: "block", overflow: "hidden" }}
    >
      {facets ? (
        <>
          <defs>
            <pattern
              id={`${id}-grain`}
              width="5"
              height="5"
              patternUnits="userSpaceOnUse"
              patternTransform="rotate(-25)"
            >
              <path
                d="M0 0V5"
                stroke="#e5f7ff"
                strokeWidth="0.45"
                opacity="0.28"
              />
            </pattern>
            {facets.map((facet, index) => {
              const tone = facet.light;
              return (
                <linearGradient
                  key={facet.facetId}
                  id={`${id}-face-${index}`}
                  x1="0"
                  y1="0"
                  x2="0.8"
                  y2="1"
                >
                  <stop
                    offset="0"
                    stopColor={`rgb(${Math.round(48 + tone * 50)} ${Math.round(121 + tone * 62)} ${Math.round(207 + tone * 43)})`}
                  />
                  <stop
                    offset="1"
                    stopColor={`rgb(${Math.round(22 + tone * 25)} ${Math.round(79 + tone * 53)} ${Math.round(151 + tone * 57)})`}
                  />
                </linearGradient>
              );
            })}
          </defs>
          {facets.map((facet, index) => (
            <g
              key={facet.facetId}
              data-engine-facet={facet.facetId}
              data-engine-part={facet.partId}
            >
              <polygon
                points={facet.points}
                fill={`url(#${id}-face-${index})`}
                stroke="#d4f4ff"
                strokeWidth="1.1"
                strokeLinejoin="round"
              />
              <polygon
                points={facet.points}
                fill={`url(#${id}-grain)`}
                stroke="none"
              />
            </g>
          ))}
        </>
      ) : (
        <g stroke="#6e9ca0" opacity="0.28" fill="none" strokeWidth="1">
          <path d="M162 112h36M180 94v36" />
          <circle cx="180" cy="112" r="27" strokeDasharray="2 6" />
        </g>
      )}
    </svg>
  );
}
