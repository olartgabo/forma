"use client";

import { useEffect, useRef, useState } from "react";
import type { AssemblyViewResponse } from "../../lib/generated/contracts";
import {
  initialCamera,
  projectFacets,
  projectWorldPoints,
  type Camera,
} from "../../../../../packages/assembly_view/projection";
import { requestView } from "./client";
import styles from "./viewer.module.css";

export default function AssemblyView({
  token,
  projectId,
  planVersionId,
  inventoryRevisionId,
  refreshKey = 0,
  selectedOperationId,
  onSelectOperation,
  disabled = false,
}: {
  token: string;
  projectId: string;
  planVersionId: string;
  inventoryRevisionId: string;
  refreshKey?: number;
  selectedOperationId: string | null;
  onSelectOperation: (id: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [reload, setReload] = useState(0);
  const [response, setResponse] = useState<AssemblyViewResponse | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [camera, setCamera] = useState<Camera>(initialCamera);
  const [selectedPart, setSelectedPart] = useState<string | null>(null);
  const [overlayCase, setOverlayCase] = useState("");
  const drag = useRef<{ id: number; x: number; y: number } | null>(null);
  // A response cannot survive a changed authorization, history, or manual context.
  const identity = `${token}:${projectId}:${planVersionId}:${inventoryRevisionId}:${refreshKey}:${reload}:${selectedOperationId ?? ""}`;
  const [loadedIdentity, setLoadedIdentity] = useState("");
  useEffect(() => {
    setResponse(null);
    setError("");
    setSelectedPart(null);
    setOverlayCase("");
    setCamera(initialCamera);
    drag.current = null;
    if (!open) {
      setPending(false);
      return;
    }
    const controller = new AbortController();
    setPending(true);
    requestView(
      token,
      { projectId, planVersionId, inventoryRevisionId },
      controller.signal,
      selectedOperationId,
    )
      .then((value) => {
        if (!controller.signal.aborted) {
          setResponse(value);
          setLoadedIdentity(identity);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Assembly unavailable. Use the SVG manual.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setPending(false);
      });
    return () => {
      controller.abort();
      drag.current = null;
    };
  }, [
    open,
    identity,
    token,
    projectId,
    planVersionId,
    inventoryRevisionId,
    selectedOperationId,
  ]);
  const view = loadedIdentity === identity ? response : null;
  const geometry = view?.geometry;
  const illustration = view?.planned_illustration;
  const plannedFacets = illustration?.facets.length
    ? projectFacets(illustration.facets, camera)
    : [];
  const links = view?.operation_parts ?? [];
  const operationParts =
    links.find((item) => item.operation_id === selectedOperationId)?.part_ids ??
    [];
  const facets = geometry ? projectFacets(geometry.facets, camera) : [];
  const overlays = view?.overlay_report?.overlays ?? [];
  const overlay =
    overlays.find((item) => item.case_id === overlayCase) ?? overlays[0];
  const overlayVisible = !!geometry && !!overlay && camera.explode === 0;
  const projectedOverlay = overlayVisible
    ? projectWorldPoints(geometry.facets, camera, [
        ...overlay.support_polygon,
        ...overlay.critical_edge,
        overlay.center_of_mass,
      ])
    : [];
  const orbit = (yaw: number, pitch: number) =>
    setCamera((value) => ({
      ...value,
      yaw: (value.yaw + yaw) % 360,
      pitch: Math.max(-80, Math.min(80, value.pitch + pitch)),
    }));
  return (
    <section className={styles.viewer} aria-label="Assembly viewer">
      <h3>Explore the assembly</h3>
      <p>
        Rotate the nominal assembly and find its parts in the manual. Viewing
        records no physical work.
      </p>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "Close assembly view" : "Open assembly view"}
      </button>
      {open && (
        <div className={styles.content}>
          <button
            type="button"
            disabled={pending}
            onClick={() => setReload((value) => value + 1)}
          >
            Refresh assembly view
          </button>
          <p role="status">
            {pending
              ? "Loading assembly…"
              : error ||
                (view?.status === "unsupported"
                  ? "This physical stage has no supported assembly view. Use the authoritative SVG manual and recorded history below."
                  : "")}
          </p>
          {view?.blockers?.map((message) => (
            <p key={message}>{message}</p>
          ))}
          {illustration && (
            <section
              aria-label="Planned operation illustration"
              data-operation-id={illustration.operation_id}
            >
              <h4>Planned operation illustration</h4>
              {illustration.notes.map((note) => (
                <p key={note}>{note}</p>
              ))}
              {plannedFacets.length ? (
                <svg
                  viewBox="0 0 480 380"
                  role="img"
                  aria-label="Planned target positions for this operation"
                >
                  {plannedFacets.map((facet) => (
                    <g key={facet.facet_id}>
                      <polygon
                        points={facet.points
                          .map((p) => `${p.x},${p.y}`)
                          .join(" ")}
                        fill="#e2e8f0"
                        stroke="#1e3a5f"
                        strokeWidth="2"
                      />
                      <text x={facet.label.x} y={facet.label.y}>
                        {facet.part_id}
                      </text>
                    </g>
                  ))}
                </svg>
              ) : (
                <p>No part geometry is available at this operation.</p>
              )}
              <button type="button" onClick={() => orbit(-15, 0)}>
                Rotate planned illustration left
              </button>
              <button type="button" onClick={() => orbit(15, 0)}>
                Rotate planned illustration right
              </button>
            </section>
          )}
          {geometry && (
            <>
              <h4>
                {geometry.stage === "planned_preview"
                  ? "Planned assembly preview"
                  : "User-reported assembled stage"}
              </h4>
              <p>
                Nominal geometry. This does not measure the actual shape,
                confirm joints, or establish a physical test pass.
              </p>
              {overlay ? (
                <div aria-label="Saved modeled overlay">
                  <label>
                    Saved report case
                    <select
                      value={overlay.case_id}
                      onChange={(event) => setOverlayCase(event.target.value)}
                    >
                      {overlays.map((item) => (
                        <option key={item.case_id} value={item.case_id}>
                          {item.case_id}: {item.orientation}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p>
                    Saved modeled overlay: center of mass, support outline and
                    critical edge. This is a point estimate, not a physical
                    pass.
                  </p>
                  <p>
                    Saved report status: {view?.overlay_report?.status}.
                    Coverage: {view?.overlay_report?.coverage}.
                  </p>
                  <p>
                    Signed tipping margin:{" "}
                    {Number(overlay.signed_margin_m.toPrecision(5))} m. Report{" "}
                    {view?.overlay_report_id}.
                  </p>
                  {camera.explode !== 0 && (
                    <p>
                      Set Separate parts to zero to show the world-space
                      overlay.
                    </p>
                  )}
                </div>
              ) : (
                <p>
                  Report overlay coverage: unavailable. Measurements and
                  physical checks remain separate.
                </p>
              )}
              <p id="assembly-controls-help">
                Drag to orbit, or focus the drawing and use arrow keys. Use the
                controls to zoom or separate parts. Separation changes only the
                display.
              </p>
              <svg
                className={styles.canvas}
                viewBox="0 0 480 380"
                role="group"
                aria-label="Rotatable nominal assembly"
                aria-describedby="assembly-controls-help"
                tabIndex={0}
                onKeyDown={(event) => {
                  const keys: Record<string, [number, number]> = {
                    ArrowLeft: [-10, 0],
                    ArrowRight: [10, 0],
                    ArrowUp: [0, 10],
                    ArrowDown: [0, -10],
                  };
                  if (keys[event.key]) {
                    event.preventDefault();
                    orbit(...keys[event.key]);
                  }
                }}
                onPointerDown={(event) => {
                  if (event.button !== 0) return;
                  drag.current = {
                    id: event.pointerId,
                    x: event.clientX,
                    y: event.clientY,
                  };
                  event.currentTarget.setPointerCapture(event.pointerId);
                }}
                onPointerMove={(event) => {
                  const previous = drag.current;
                  if (!previous || previous.id !== event.pointerId) return;
                  orbit(
                    (event.clientX - previous.x) * 0.5,
                    (event.clientY - previous.y) * 0.5,
                  );
                  drag.current = {
                    id: event.pointerId,
                    x: event.clientX,
                    y: event.clientY,
                  };
                }}
                onPointerUp={(event) => {
                  drag.current = null;
                  if (event.currentTarget.hasPointerCapture(event.pointerId))
                    event.currentTarget.releasePointerCapture(event.pointerId);
                }}
                onPointerCancel={() => {
                  drag.current = null;
                }}
                onLostPointerCapture={() => {
                  drag.current = null;
                }}
              >
                <title>
                  Canonical nominal assembly with source part labels
                </title>
                {facets.map((facet) => (
                  <g key={facet.facet_id}>
                    <polygon
                      points={facet.points
                        .map((p) => `${p.x},${p.y}`)
                        .join(" ")}
                      fill={
                        selectedPart === facet.part_id ? "#bfdbfe" : "#e2e8f0"
                      }
                      stroke="#1e3a5f"
                      strokeWidth={
                        operationParts.includes(facet.part_id) ? 4 : 2
                      }
                      strokeDasharray={
                        operationParts.includes(facet.part_id)
                          ? "8 3"
                          : undefined
                      }
                      onClick={() => setSelectedPart(facet.part_id)}
                    />
                  </g>
                ))}
                {overlayVisible && overlay && (
                  <g
                    role="group"
                    aria-label={`${overlay.case_id} modeled stability overlay`}
                    pointerEvents="none"
                  >
                    <polygon
                      points={projectedOverlay
                        .slice(0, overlay.support_polygon.length)
                        .map((p) => `${p.x},${p.y}`)
                        .join(" ")}
                      fill="none"
                      stroke="#7c3e00"
                      strokeWidth="3"
                      strokeDasharray="5 4"
                    />
                    <polyline
                      points={projectedOverlay
                        .slice(overlay.support_polygon.length, -1)
                        .map((p) => `${p.x},${p.y}`)
                        .join(" ")}
                      fill="none"
                      stroke="#7c3e00"
                      strokeWidth="5"
                    />
                    <circle
                      cx={projectedOverlay[projectedOverlay.length - 1].x}
                      cy={projectedOverlay[projectedOverlay.length - 1].y}
                      r="6"
                      fill="#7c3e00"
                    />
                  </g>
                )}
                {geometry.active_part_ids.map((partId, index) => {
                  const facet = facets.find((item) => item.part_id === partId);
                  if (!facet) return null;
                  const y = 26 + index * 24;
                  return (
                    <g key={partId} pointerEvents="none">
                      <line
                        x1="155"
                        y1={y - 4}
                        x2={facet.label.x}
                        y2={facet.label.y}
                        stroke="#475569"
                        strokeWidth="1"
                      />
                      <circle
                        cx={facet.label.x}
                        cy={facet.label.y}
                        r="3"
                        fill="#1e3a5f"
                      />
                      <text x="12" y={y} className={styles.label}>
                        {partId}
                      </text>
                    </g>
                  );
                })}
              </svg>
              <div className={styles.controls}>
                <button type="button" onClick={() => orbit(-15, 0)}>
                  Orbit left
                </button>
                <button type="button" onClick={() => orbit(15, 0)}>
                  Orbit right
                </button>
                <button type="button" onClick={() => orbit(0, 15)}>
                  Tilt up
                </button>
                <button type="button" onClick={() => orbit(0, -15)}>
                  Tilt down
                </button>
                <button type="button" onClick={() => setCamera(initialCamera)}>
                  Reset view
                </button>
              </div>
              <label className={styles.slider}>
                Zoom{" "}
                <input
                  type="range"
                  min="0.5"
                  max="1.6"
                  step="0.1"
                  value={camera.zoom}
                  onChange={(event) =>
                    setCamera((value) => ({
                      ...value,
                      zoom: Number(event.target.value),
                    }))
                  }
                />
              </label>
              <label className={styles.slider}>
                Separate parts (display only){" "}
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={camera.explode}
                  onChange={(event) =>
                    setCamera((value) => ({
                      ...value,
                      explode: Number(event.target.value),
                    }))
                  }
                />
              </label>
              <p>
                Dashed edges identify parts used in the selected manual
                operation. Blue fill identifies the selected part.
              </p>
              <div className={styles.controls} aria-label="Assembly parts">
                {geometry.active_part_ids.map((id) => (
                  <button
                    type="button"
                    key={id}
                    aria-pressed={selectedPart === id}
                    onClick={() => setSelectedPart(id)}
                  >
                    {id}
                  </button>
                ))}
              </div>
              {selectedPart && (
                <div aria-live="polite">
                  <p>Selected part: {selectedPart}</p>
                  <div className={styles.controls}>
                    {links
                      .filter((link) => link.part_ids.includes(selectedPart))
                      .map((link) => (
                        <button
                          type="button"
                          disabled={disabled}
                          key={link.operation_id}
                          onClick={() => onSelectOperation(link.operation_id)}
                        >
                          Show manual operation {link.operation_id}
                        </button>
                      ))}
                  </div>
                </div>
              )}
              <details>
                <summary>Source geometry and assumptions</summary>
                <p className={styles.identity}>
                  Plan {geometry.plan_version_id}. Producer{" "}
                  {geometry.producer_version}. Geometry hash{" "}
                  {geometry.geometry_hash}. Evidence revision{" "}
                  {view.evidence_revision}.
                </p>
                <ul>
                  {geometry.assumptions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                <p>Coordinates use metres: x across, y rearward, z up.</p>
                <ul>
                  {geometry.facets.map((facet) => (
                    <li key={facet.facet_id}>
                      {facet.facet_id}: part {facet.part_id}
                      {facet.feature_id ? `, feature ${facet.feature_id}` : ""}.
                      Vertices:{" "}
                      {facet.vertices
                        .map((p) => `(${p.x}, ${p.y}, ${p.z})`)
                        .join("; ")}
                    </li>
                  ))}
                </ul>
              </details>
            </>
          )}
          <p>
            The authoritative SVG instructions and physical history remain
            available in the manual.
          </p>
        </div>
      )}
    </section>
  );
}
