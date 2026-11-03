"use client";

import { useEffect, useRef, useState } from "react";
import type { StabilityOverlay } from "../../lib/generated/contracts";
import { requestAnalysis, type AnalysisResponse } from "./client";
import GeometryPreview from "./geometry-preview";
import MeasurementCapture from "./measurement-capture";

const label = (value: string) => value.replaceAll("_", " ");
const number = (value: number) => Number(value.toPrecision(5)).toString();
function Overlay({ overlay }: { overlay: StabilityOverlay }) {
  const points = [
    ...overlay.support_polygon,
    overlay.center_of_mass,
    ...overlay.critical_edge,
  ];
  const minX = Math.min(...points.map((p) => p.x));
  const maxX = Math.max(...points.map((p) => p.x));
  const minY = Math.min(...points.map((p) => p.y));
  const maxY = Math.max(...points.map((p) => p.y));
  const scale = 240 / Math.max(maxX - minX, maxY - minY, 0.001);
  const xy = (p: { x: number; y: number }) =>
    `${30 + (p.x - minX) * scale},${270 - (p.y - minY) * scale}`;
  return (
    <figure>
      <figcaption>
        {overlay.case_id} — {overlay.orientation}: modeled world geometry, top
        view (m)
      </figcaption>
      <svg
        viewBox="0 0 320 310"
        role="img"
        aria-label={`${overlay.case_id}: center of mass projection, support polygon and critical edge`}
        style={{ width: "100%", maxWidth: 420 }}
      >
        <polygon
          points={overlay.support_polygon.map(xy).join(" ")}
          fill="#e2e8f0"
          stroke="#334155"
          strokeWidth="2"
        />
        <polyline
          points={overlay.critical_edge.map(xy).join(" ")}
          fill="none"
          stroke="#b45309"
          strokeWidth="4"
        />
        <circle
          cx={30 + (overlay.center_of_mass.x - minX) * scale}
          cy={270 - (overlay.center_of_mass.y - minY) * scale}
          r="5"
          fill="#111827"
        />
        <text x="10" y="16">
          COM ● · support outline · critical edge (thick)
        </text>
      </svg>
      <p>
        COM: x {number(overlay.center_of_mass.x)}, y{" "}
        {number(overlay.center_of_mass.y)}, z {number(overlay.center_of_mass.z)}{" "}
        m.
      </p>
      <p>
        Signed margin: {number(overlay.signed_margin_m)} m. Restoring moment:{" "}
        {number(overlay.restoring_moment_n_m)} N_m.
      </p>
      <details>
        <summary>Support and critical edge coordinates (m)</summary>
        <p>
          Support:{" "}
          {overlay.support_polygon
            .map((p) => `(${number(p.x)}, ${number(p.y)}, ${number(p.z)})`)
            .join("; ")}
        </p>
        <p>
          Critical edge:{" "}
          {overlay.critical_edge
            .map((p) => `(${number(p.x)}, ${number(p.y)}, ${number(p.z)})`)
            .join("; ")}
        </p>
      </details>
    </figure>
  );
}
export default function StabilityReportPanel({
  token,
  projectId,
  planVersionId,
  inventoryRevisionId,
  refreshKey = 0,
  disabled = false,
  onMeasurementsSaved,
  onMeasurementLockChange,
}: {
  token: string;
  projectId: string;
  planVersionId: string;
  inventoryRevisionId: string;
  refreshKey?: number;
  disabled?: boolean;
  onMeasurementsSaved?: () => void;
  onMeasurementLockChange?: (active: boolean) => void;
}) {
  const measurementScope = JSON.stringify([
    token,
    projectId,
    planVersionId,
    inventoryRevisionId,
  ]);
  const [measurementNotice, setMeasurementNotice] = useState<string | null>(
    null,
  );
  const [measurementHistorical, setMeasurementHistorical] = useState(false);
  const identity = JSON.stringify([
    token,
    projectId,
    planVersionId,
    inventoryRevisionId,
    refreshKey,
    disabled,
  ]);
  const current = useRef(identity);
  current.current = identity;
  const mounted = useRef(true);
  const controller = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [measurementActive, setMeasurementActive] = useState(false);
  const [geometryReady, setGeometryReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<{
    identity: string;
    response: AnalysisResponse;
    date: string;
    historical: boolean;
  } | null>(null);
  useEffect(() => {
    mounted.current = true;
    setBusy(false);
    setError(null);
    setSaved(null);
    setMeasurementActive(false);
    setGeometryReady(false);
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, [identity]);
  const visible = saved?.identity === identity ? saved : null;
  async function analyze() {
    controller.current?.abort();
    const own = new AbortController();
    controller.current = own;
    const requestedIdentity = identity;
    setBusy(true);
    setError(null);
    setSaved((old) => (old ? { ...old, historical: true } : null));
    const timeout = setTimeout(() => own.abort(), 20000);
    try {
      const response = await requestAnalysis(
        token,
        { projectId, planVersionId, inventoryRevisionId },
        own.signal,
      );
      if (
        !own.signal.aborted &&
        mounted.current &&
        current.current === requestedIdentity
      ) {
        setGeometryReady(
          response.geometry_preview?.stage === "reported_assembled" ||
            !!response.report,
        );
        setSaved({
          identity: requestedIdentity,
          response,
          date: new Date().toISOString(),
          historical: false,
        });
      }
    } catch (e) {
      if (mounted.current && current.current === requestedIdentity)
        setError(
          own.signal.aborted
            ? "Analysis stopped or timed out. Analyze again when ready."
            : e instanceof Error
              ? e.message
              : "Analysis failed.",
        );
    } finally {
      clearTimeout(timeout);
      if (mounted.current && current.current === requestedIdentity)
        setBusy(false);
    }
  }
  return (
    <section aria-label="Stability analysis">
      <h3>Stability analysis</h3>
      <p>Modeled calculations; physical verification is separate.</p>
      <button
        type="button"
        disabled={disabled || busy || measurementActive || !token}
        onClick={analyze}
      >
        {busy ? "Analyzing stability…" : "Analyze stability"}
      </button>
      {error && <p role="alert">{error}</p>}
      {measurementNotice === measurementScope && (
        <p role="status">
          {measurementHistorical
            ? "Recovered a saved measurement record for an earlier plan or inventory. Analyze the current plan to check what still applies."
            : "Measurements saved. Analyze stability again to calculate from this new record."}
        </p>
      )}
      <MeasurementCapture
        key={identity}
        token={token}
        expected={{ projectId, planVersionId, inventoryRevisionId }}
        available={geometryReady}
        disabled={disabled || busy}
        onSessionChange={(active) => {
          setMeasurementActive(active);
          onMeasurementLockChange?.(active);
        }}
        onInvalidate={() => {
          setMeasurementNotice(null);
          setSaved(null);
          setError(null);
        }}
        onSaved={(historical = false) => {
          setMeasurementHistorical(historical);
          setMeasurementNotice(measurementScope);
          setSaved(null);
          setError(null);
          onMeasurementsSaved?.();
        }}
      />
      {visible && (
        <div aria-live="polite">
          <p>
            {visible.historical
              ? "Historical report — stale; latest request has no current result."
              : "Analysis result"}{" "}
            · {new Date(visible.date).toLocaleString()}
          </p>
          <p>Status: {label(visible.response.status)}</p>
          {!!visible.response.blockers.length && (
            <ul>
              {visible.response.blockers.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          )}
          {visible.response.geometry_preview && (
            <GeometryPreview geometry={visible.response.geometry_preview} />
          )}
          {visible.response.report && (
            <>
              <p>
                Modeled status: {label(visible.response.report.status)}.
                Coverage: {label(visible.response.report.coverage)}.
              </p>
              <p>
                State basis:{" "}
                {visible.response.report.state_basis ?? "unspecified"}.
              </p>
              {!!visible.response.report.assumption_ids?.length && (
                <p>
                  Assumptions:{" "}
                  {visible.response.report.assumption_ids.join("; ")}
                </p>
              )}
              {!!visible.response.report.input_warnings?.length && (
                <ul>
                  {visible.response.report.input_warnings.map((warning, i) => (
                    <li key={i}>{warning}</li>
                  ))}
                </ul>
              )}
              {!!visible.response.report.unresolved_predicates?.length && (
                <>
                  <h4>Assumptions and unresolved inputs</h4>
                  <ul>
                    {visible.response.report.unresolved_predicates?.map(
                      (p, i) => (
                        <li key={i}>{p}</li>
                      ),
                    )}
                  </ul>
                </>
              )}
              <ul>
                {visible.response.report.results?.map((r) => (
                  <li key={`${r.case_id}/${r.check_type}`}>
                    {r.case_id} — {label(r.check_type)}: {label(r.status)}.{" "}
                    {r.explanation}
                    {!!r.unresolved_predicates?.length && (
                      <p>{r.unresolved_predicates?.join("; ")}</p>
                    )}
                  </li>
                ))}
              </ul>
              <p>
                Slide, joint and deformation checks:{" "}
                {(["slide", "joint", "deformation"] as const)
                  .map(
                    (kind) =>
                      `${kind}: ${
                        visible.response
                          .report!.results?.filter((r) => r.check_type === kind)
                          .map((r) => `${r.case_id} ${label(r.status)}`)
                          .join(", ") || "unsupported / not evaluated"
                      }`,
                  )
                  .join("; ")}
                .
              </p>
              {visible.response.report.overlays?.map((o) => (
                <Overlay key={o.case_id} overlay={o} />
              ))}
            </>
          )}
        </div>
      )}
    </section>
  );
}
