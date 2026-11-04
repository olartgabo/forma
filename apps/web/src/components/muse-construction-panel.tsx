"use client";

import { useEffect, useRef, useState } from "react";
import type {
  Media,
  Project,
  MuseConstructionResult,
  MuseConstructionCandidateResult,
  MuseConstructionReceipts,
} from "../lib/generated/api-contracts";
import type { ConstructionPlan, Point3 } from "../lib/generated/contracts";
import type { MuseAvailability } from "../lib/muse-provider";
import { ApiError } from "../lib/api";
import {
  proposeConstruction,
  constructionReceipts,
  savedConstruction,
  authorizeConstructionReplacement,
  blockingConstructionReceipts,
  uncertainConstructionOutcome,
} from "../lib/muse-construction-client";
import {
  pendingConstruction,
  retainConstruction,
  clearConstruction,
  retainReplacementConstruction,
  constructionContextChanged,
  constructionRequestCanRestart,
  type PendingConstruction,
} from "../lib/muse-construction-pending";
import { museDiagnosticsFromResult } from "../lib/provider-usage";
import CubeLoader from "./cube-loader";
import ConstructionStepDiagrams from "./construction-step-diagrams";
import {
  projectConstructionFacets,
  fitConstructionProjection,
  constructionCamera,
} from "../lib/construction-projection";
import MuseRequestStatus from "./muse-request-status";
import {
  constructionStepTitle,
  constructionPiecePresence,
  materialMeasurementChecklist,
} from "../lib/muse-construction-guidance";

function faceOutline(vertices: readonly Point3[]) {
  if (vertices.length < 3) return null;
  const origin = vertices[0];
  const subtract = (a: Point3, b: Point3) => ({
    x: a.x - b.x,
    y: a.y - b.y,
    z: a.z - b.z,
  });
  const dot = (a: Point3, b: Point3) => a.x * b.x + a.y * b.y + a.z * b.z;
  const edge = subtract(vertices[1], origin);
  const length = Math.hypot(edge.x, edge.y, edge.z);
  if (length < 1e-9) return null;
  const axis = { x: edge.x / length, y: edge.y / length, z: edge.z / length };
  const offsets = vertices.map((v) => subtract(v, origin));
  const perpendicular = offsets
    .map((v) => {
      const along = dot(v, axis);
      return {
        x: v.x - along * axis.x,
        y: v.y - along * axis.y,
        z: v.z - along * axis.z,
      };
    })
    .find((v) => Math.hypot(v.x, v.y, v.z) > 1e-9);
  if (!perpendicular) return null;
  const depth = Math.hypot(perpendicular.x, perpendicular.y, perpendicular.z);
  const secondAxis = {
    x: perpendicular.x / depth,
    y: perpendicular.y / depth,
    z: perpendicular.z / depth,
  };
  const points = offsets.map((v) => ({
    x: dot(v, axis) * 1000,
    y: dot(v, secondAxis) * 1000,
  }));
  const minX = Math.min(...points.map((p) => p.x)),
    maxX = Math.max(...points.map((p) => p.x));
  const minY = Math.min(...points.map((p) => p.y)),
    maxY = Math.max(...points.map((p) => p.y));
  return { points, minX, minY, width: maxX - minX, height: maxY - minY };
}

function Preparation({ plan }: { plan: ConstructionPlan }) {
  return (
    <section aria-label="Prepare the proposed pieces">
      <h4>Prepare the proposed pieces</h4>
      <p>
        Approximate model dimensions in millimeters. Check the material, size
        and fit before cutting. These face outlines are conceptual and are not
        cutting templates; connections and thickness still need checking.
      </p>
      <ol>
        {plan.piece_catalog.map((piece) => {
          const part = plan.request.target.assembly.parts.find(
            (item) => item.part_id === piece.part_id,
          );
          return (
            <li key={piece.part_id}>
              <strong>{piece.display_name}</strong>
              {piece.role ? ` · ${piece.role}` : ""}
              {part?.facets.map((facet, index) => {
                const outline = faceOutline(facet.vertices_local);
                return (
                  <div key={facet.facet_id}>
                    {part.facets.length > 1 && (
                      <p>
                        Face {index + 1} (folds and connections are not
                        specified)
                      </p>
                    )}
                    {outline ? (
                      <figure className="drawing-sheet construction-blueprint construction-preparation-sheet">
                        <figcaption className="drawing-sheet-title">
                          <strong>Proposed face</strong>
                          <span>{piece.reference}</span>
                        </figcaption>
                        <div
                          className="drawing-sheet-ticks"
                          aria-hidden="true"
                        />
                        <p className="construction-blueprint-caption">
                          Approximate face bounds:{" "}
                          {Math.round(outline.width * 10) / 10} ×{" "}
                          {Math.round(outline.height * 10) / 10} mm
                        </p>
                        <svg
                          role="img"
                          aria-label={`Approximate outline of ${piece.display_name}${part.facets.length > 1 ? ` face ${index + 1}` : ""}`}
                          viewBox={`${outline.minX - 10} ${outline.minY - 10} ${outline.width + 20} ${outline.height + 20}`}
                          className="construction-blueprint-canvas"
                        >
                          <polygon
                            points={outline.points
                              .map((point) => `${point.x},${point.y}`)
                              .join(" ")}
                            className="construction-blueprint-panel"
                            strokeWidth="2"
                            vectorEffect="non-scaling-stroke"
                          />
                        </svg>
                      </figure>
                    ) : (
                      <p>Face dimensions are unavailable.</p>
                    )}
                  </div>
                );
              })}
              {!part && <p>Face dimensions are unavailable.</p>}
              <details>
                <summary>Piece reference</summary>
                {piece.reference} · {piece.part_id}
              </details>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function ConstructionPreview({
  plan,
  approximate,
}: {
  plan: ConstructionPlan;
  approximate: boolean;
}) {
  const [index, setIndex] = useState(0);
  const [yaw, setYaw] = useState(315);
  const [pitch, setPitch] = useState(25);
  const drag = useRef<{
    x: number;
    y: number;
    yaw: number;
    pitch: number;
  } | null>(null);
  const step = plan.steps[Math.min(index, plan.steps.length - 1)];
  const numbers = new Map(plan.piece_catalog.map((p, i) => [p.part_id, i + 1]));
  const facets = projectConstructionFacets(
    step.analysis.facets,
    constructionCamera(yaw, pitch),
  );
  const { x, y } = fitConstructionProjection(facets.flatMap((f) => f.points));
  return (
    <div>
      <div className="muse-actions">
        <button
          type="button"
          disabled={index === 0}
          onClick={() => setIndex(index - 1)}
        >
          Previous step
        </button>
        <span>
          Step {index + 1} of {plan.steps.length}
        </span>
        <button
          type="button"
          disabled={index === plan.steps.length - 1}
          onClick={() => setIndex(index + 1)}
        >
          Next step
        </button>
      </div>
      <label>
        Choose a proposed step
        <select
          style={{ width: "100%", minWidth: 0, maxWidth: "100%" }}
          value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
        >
          {plan.steps.map((s, i) => (
            <option key={s.step_id} value={i}>
              {i + 1}. {constructionStepTitle(plan, s)}
            </option>
          ))}
        </select>
      </label>
      <div aria-live="polite">
        <h4>{constructionStepTitle(plan, step)}</h4>
        {approximate ? (
          <>
            <p>
              {step.action === "place"
                ? "Position the highlighted piece as shown and check how it fits."
                : step.action === "join"
                  ? "Bring the highlighted pieces together as shown. The connection method and strength still need verification."
                  : "Inspect the proposed placement and connections."}
            </p>
            <details>
              <summary>Engine step details</summary>
              {step.instruction}
            </details>
          </>
        ) : (
          <p>{step.instruction}</p>
        )}
        {step.requires_external_support && (
          <p className="notice">
            Self-support is not established at this step. Temporary support has
            not been modeled.
          </p>
        )}
        {step.unresolved_predicates.length > 0 && (
          <details
            open={!approximate}
            className="notice"
            role="note"
            aria-label="Unresolved checks for this step"
          >
            <summary>
              {approximate
                ? "Checks to review before building"
                : "Unresolved checks for this step"}
            </summary>
            <ul>
              {step.unresolved_predicates.map((v, i) => (
                <li key={i}>{v}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
      <svg
        viewBox="0 0 400 380"
        role="img"
        aria-label="Proposed construction geometry. Drag to rotate; sliders are available below."
        style={{
          width: "100%",
          maxHeight: 440,
          background: "#eef3ef",
          touchAction: "none",
        }}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          drag.current = { x: e.clientX, y: e.clientY, yaw, pitch };
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (d) {
            setYaw((((d.yaw + e.clientX - d.x) % 360) + 360) % 360);
            setPitch(
              Math.max(-80, Math.min(80, d.pitch + (e.clientY - d.y) * 0.5)),
            );
          }
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        {facets
          .sort((f, g) => f.center.depth - g.center.depth)
          .map((f) => (
            <polygon
              key={f.facet_id}
              points={f.points.map((p) => `${x(p.x)},${y(p.y)}`).join(" ")}
              fill={`hsl(${(numbers.get(f.part_id) ?? 0) * 63} 30% 76%)`}
              data-part-id={f.part_id}
              data-step-focus={step.part_ids.includes(f.part_id)}
              stroke={step.part_ids.includes(f.part_id) ? "#102c21" : "#718579"}
              strokeWidth={step.part_ids.includes(f.part_id) ? 4 : 1.5}
            />
          ))}
        {facets.map((f) => (
          <g key={`label-${f.facet_id}`}>
            <title>
              {
                plan.piece_catalog.find((p) => p.part_id === f.part_id)
                  ?.display_name
              }{" "}
              ·{" "}
              {
                plan.piece_catalog.find((p) => p.part_id === f.part_id)
                  ?.reference
              }
            </title>
            <circle
              cx={x(f.center.x)}
              cy={y(f.center.y)}
              r="11"
              fill="white"
              stroke="#35584a"
            />
            <text
              x={x(f.center.x)}
              y={y(f.center.y) + 4}
              textAnchor="middle"
              fontSize="13"
              fill="#183a30"
            >
              {numbers.get(f.part_id)}
            </text>
          </g>
        ))}
      </svg>
      <p className="help">
        Drag to turn the proposed model. A thick outline marks the pieces
        involved in this step. Camera changes do not change its physics.
      </p>
      <label>
        View angle: {Math.round(yaw)}°
        <input
          aria-label="Construction view angle"
          type="range"
          min="0"
          max="360"
          value={yaw}
          onChange={(e) => setYaw(Number(e.target.value))}
        />
      </label>
      <label>
        View tilt: {Math.round(pitch)}°
        <input
          aria-label="Construction view tilt"
          type="range"
          min="-80"
          max="80"
          value={pitch}
          onChange={(e) => setPitch(Number(e.target.value))}
        />
      </label>
      <p className="help">
        Piece references for the whole proposal. This step shows only its
        present pieces.
      </p>
      <ConstructionStepDiagrams plan={plan} step={step} />
      <ol>
        {plan.piece_catalog.map((p) => (
          <li key={p.part_id} style={{ overflowWrap: "anywhere" }}>
            {p.display_name}
            {!approximate && (
              <>
                {" "}
                · {p.reference} · {p.geometry_class.replaceAll("_", " ")}
                {p.role ? ` · proposed role: ${p.role}` : ""}
              </>
            )}
            <strong>
              {" "}
              · {constructionPiecePresence(plan, step, p.part_id)}
            </strong>
          </li>
        ))}
      </ol>
      <p className="help">
        Proposed state only. Navigation does not complete any operation.
      </p>
    </div>
  );
}

function Candidate({
  candidate,
  approximate,
  restored = false,
}: {
  candidate: MuseConstructionCandidateResult;
  approximate: boolean;
  restored?: boolean;
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  const reviewRequired = approximate || restored;
  return (
    <article className="muse-result" style={{ overflowWrap: "anywhere" }}>
      <h3>{candidate.title}</h3>
      <p>{candidate.rationale}</p>
      {(!approximate || !candidate.construction) && (
        <p>Engine result: {candidate.status.replaceAll("_", " ")}</p>
      )}
      {(!approximate || !candidate.construction) &&
        candidate.blockers.length > 0 && (
          <ul>
            {candidate.blockers.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        )}
      {reviewRequired && (
        <div>
          <h4>Review your materials</h4>
          <p>
            These sizes are approximate. Adjust them in the notes if needed, and
            check actual materials before building.
          </p>
          <ul>
            {(candidate.estimated_materials ?? []).map((m, i) => (
              <li key={i}>
                {m.label}: {m.width_mm ?? "unknown"} x{" "}
                {m.height_mm ?? "unknown"} x {m.thickness_mm ?? "unknown"} mm
              </li>
            ))}
          </ul>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />{" "}
            {restored
              ? "Review these proposed dimensions for my saved manual."
              : "Use these estimates for my manual."}
          </label>
        </div>
      )}
      {candidate.construction && (!reviewRequired || acknowledged) && (
        <>
          {reviewRequired && <Preparation plan={candidate.construction} />}
          <ConstructionPreview
            key={candidate.construction.target_hash}
            plan={candidate.construction}
            approximate={approximate}
          />
        </>
      )}
      {candidate.fabrication_report && (
        <p>
          Next fabrication operation: {candidate.fabrication_report.status};
          complete operation order: {candidate.fabrication_report.order_status}.
          This does not establish stability, joint strength or completed work.
        </p>
      )}
      <details>
        <summary>Exact engine and fabrication results</summary>
        <pre
          style={{
            whiteSpace: "pre-wrap",
            overflowWrap: "anywhere",
            maxHeight: 400,
            overflow: "auto",
          }}
        >
          {JSON.stringify(candidate, null, 2)}
        </pre>
      </details>
    </article>
  );
}

export default function MuseConstructionPanel(props: {
  approximate?: boolean;
  onBusyChange?: (busy: boolean) => void;
  onReadyChange?: (ready: boolean) => void;
  token: string;
  project: Project;
  photos: Media[];
  inventoryStale: boolean;
  disabled: boolean;
  museAvailability?: MuseAvailability;
}) {
  return (
    <ConstructionPanel
      key={JSON.stringify([props.token, props.project.id])}
      {...props}
    />
  );
}

function ConstructionPanel({
  approximate = false,
  onBusyChange,
  onReadyChange,
  token,
  project,
  photos,
  inventoryStale,
  disabled,
  museAvailability,
}: {
  approximate?: boolean;
  onBusyChange?: (busy: boolean) => void;
  onReadyChange?: (ready: boolean) => void;
  token: string;
  project: Project;
  photos: Media[];
  inventoryStale: boolean;
  disabled: boolean;
  museAvailability?: MuseAvailability;
}) {
  const [photo, setPhoto] = useState("");
  const [notes, setNotes] = useState("");
  const [consent, setConsent] = useState(false);
  const [photoConsent, setPhotoConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    onBusyChange?.(busy);
    return () => onBusyChange?.(false);
  }, [busy, onBusyChange]);
  const [proposalInFlight, setProposalInFlight] = useState(false);
  const [result, setResult] = useState<MuseConstructionResult | null>(null);
  const [restored, setRestored] = useState(false);
  useEffect(() => {
    onReadyChange?.(
      !busy &&
        result !== null &&
        result.status !== "blocked" &&
        result.candidates.some(
          (candidate) => candidate.construction !== null,
        ) &&
        !inventoryStale,
    );
    return () => onReadyChange?.(false);
  }, [busy, result, inventoryStale, onReadyChange]);
  const [error, setError] = useState<ApiError | null>(null);
  const [pending, setPending] = useState<PendingConstruction | null>(null);
  const [recoveryContext, setRecoveryContext] = useState<string | null>(null);
  const [storageBlocked, setStorageBlocked] = useState(false);
  const [serverReceipts, setServerReceipts] =
    useState<MuseConstructionReceipts | null>(null);
  const [checkingStatus, setCheckingStatus] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [savedManualError, setSavedManualError] = useState<string | null>(null);
  const [uncertainDispatch, setUncertainDispatch] = useState(false);
  const statusEpoch = useRef(0);
  const statusController = useRef<AbortController | null>(null);
  const unresolvedReceipts =
    serverReceipts?.receipts.filter(
      (receipt) => receipt.state !== "completed",
    ) ?? [];
  const blockingReceipts = blockingConstructionReceipts(
    serverReceipts?.receipts ?? [],
    pending?.payload.idempotency_key,
    project.revision_id,
  );
  const replacementSource = unresolvedReceipts.find(
    (r) =>
      r.state === "unknown" &&
      !serverReceipts?.receipts.some(
        (child) =>
          child.idempotency_key === r.replacement_idempotency_key &&
          child.replaces_idempotency_key === r.idempotency_key,
      ),
  );
  const isReplacement =
    !!pending &&
    !!serverReceipts?.receipts.some(
      (r) => r.replacement_idempotency_key === pending.payload.idempotency_key,
    );
  const replacementPrepared =
    isReplacement &&
    replacementSource?.idempotency_key !== pending?.payload.idempotency_key;
  async function checkStatus() {
    const current = ++statusEpoch.current;
    statusController.current?.abort();
    const abort = new AbortController();
    statusController.current = abort;
    setCheckingStatus(true);
    setStatusError(null);
    try {
      const value = await constructionReceipts(token, project.id, abort.signal);
      if (current !== statusEpoch.current || abort.signal.aborted) return;
      setServerReceipts(value);
      if (
        pending &&
        value.receipts.some(
          (receipt) =>
            receipt.idempotency_key === pending.payload.idempotency_key &&
            receipt.state === "completed",
        )
      )
        setUncertainDispatch(false);
    } catch {
      if (current !== statusEpoch.current || abort.signal.aborted) return;
      setServerReceipts(null);
      setStatusError(
        "Request status could not be confirmed. Generation is blocked; check request status again.",
      );
    } finally {
      if (current === statusEpoch.current && !abort.signal.aborted)
        setCheckingStatus(false);
    }
  }
  useEffect(() => {
    void checkStatus();
    return () => {
      statusEpoch.current++;
      statusController.current?.abort();
    };
  }, [token, project.id]);

  const controller = useRef<AbortController | null>(null);
  const manualController = useRef<AbortController | null>(null);
  const epoch = useRef(0);
  const photosKey = photos
    .map((p) => `${p.id}:${p.byte_count}:${p.content_type}`)
    .join(",");
  const contextIdentity = JSON.stringify([
    project.revision_id,
    project.goal,
    photosKey,
  ]);
  const currentContext = useRef(contextIdentity);
  const manualResultContext = useRef<string | null>(null);
  const manualViewContext = JSON.stringify([contextIdentity, approximate]);
  currentContext.current = contextIdentity;
  const stalePending =
    !!pending && constructionContextChanged(pending, project, photos);
  const selected = photos.find((p) => p.id === photo);
  const eligible =
    !photo ||
    (!!selected &&
      ["image/jpeg", "image/png"].includes(selected.content_type) &&
      selected.byte_count > 0 &&
      selected.byte_count <= 5_000_000);
  useEffect(() => {
    const current = ++epoch.current;
    controller.current?.abort();
    setBusy(false);
    setProposalInFlight(false);
    setResult(null);
    setConsent(false);
    setPhotoConsent(false);
    setError(null);
    setRecoveryContext(null);
    void pendingConstruction(token, project.id)
      .then((record) => {
        if (current !== epoch.current) return;
        setPending(record);
        if (record) {
          setNotes(record.payload.user_notes ?? "");
          setPhoto(record.payload.media_id ?? "");
        }
        setStorageBlocked(false);
        setRecoveryContext(contextIdentity);
      })
      .catch((failure) => {
        if (current !== epoch.current) return;
        storageFailure(failure);
      });
  }, [token, project.id, project.revision_id, project.goal, photosKey]);
  useEffect(
    () => () => {
      epoch.current++;
      controller.current?.abort();
    },
    [],
  );
  useEffect(() => {
    setResult(null);
    setConsent(false);
    setPhotoConsent(false);
  }, [approximate]);
  useEffect(() => {
    const abort = new AbortController();
    manualController.current?.abort();
    manualController.current = abort;
    const actionEpoch = epoch.current;
    setSavedManualError(null);
    if (
      inventoryStale ||
      project.active_version_id ||
      !serverReceipts ||
      blockingConstructionReceipts(
        serverReceipts.receipts,
        undefined,
        undefined,
        true,
      ).length > 0
    ) {
      setResult(null);
      return () => abort.abort();
    }
    if (
      (!result || manualResultContext.current !== manualViewContext) &&
      serverReceipts.receipts[0]?.state === "completed"
    ) {
      void savedConstruction(
        token,
        project.id,
        project.revision_id,
        abort.signal,
      )
        .then((saved) => {
          if (!abort.signal.aborted && actionEpoch === epoch.current) {
            setResult(saved);
            setRestored(saved !== null);
            manualResultContext.current = manualViewContext;
          }
        })
        .catch((failure) => {
          if (!abort.signal.aborted && actionEpoch === epoch.current) {
            setResult(null);
            setSavedManualError((failure as Error).message);
          }
        });
    }
    return () => abort.abort();
  }, [
    token,
    project.id,
    project.revision_id,
    project.active_version_id,
    inventoryStale,
    serverReceipts,
    approximate,
    photosKey,
    project.goal,
  ]);
  function changed() {
    manualController.current?.abort();
    setConsent(false);
    setPhotoConsent(false);
    setResult(null);
    setError(null);
  }
  function storageFailure(failure: unknown) {
    setStorageBlocked(true);
    setError(
      new ApiError(
        0,
        "recovery_storage",
        failure instanceof Error
          ? failure.message
          : "Browser recovery storage is unavailable. Proposal requests are blocked.",
      ),
    );
  }
  const unavailable =
    checkingStatus ||
    serverReceipts === null ||
    blockingReceipts.length > 0 ||
    uncertainDispatch ||
    disabled ||
    inventoryStale ||
    !!project.active_version_id ||
    museAvailability?.enabled === false ||
    recoveryContext !== contextIdentity ||
    storageBlocked ||
    stalePending ||
    (!!pending && Boolean(pending.payload.approximate) !== approximate);
  async function prepareReplacement() {
    if (
      !replacementSource ||
      busy ||
      checkingStatus ||
      !serverReceipts ||
      storageBlocked ||
      inventoryStale ||
      project.active_version_id ||
      !eligible ||
      (approximate && !photo)
    )
      return;
    const current = ++epoch.current;
    manualController.current?.abort();
    setBusy(true);
    setConsent(false);
    setPhotoConsent(false);
    setError(null);
    try {
      const replacementKey =
        replacementSource.replacement_expected_revision_id ===
        project.revision_id
          ? (replacementSource.replacement_idempotency_key ??
            crypto.randomUUID())
          : crypto.randomUUID();
      const authorization = await authorizeConstructionReplacement(
        token,
        project.id,
        {
          expected_revision_id: project.revision_id,
          original_idempotency_key: replacementSource.idempotency_key,
          original_digest: replacementSource.digest,
          replacement_idempotency_key: replacementKey,
          acknowledge_unknown: true,
        },
      );
      if (
        current !== epoch.current ||
        currentContext.current !== contextIdentity
      )
        return;
      const record: PendingConstruction = {
        version: 1,
        project_id: project.id,
        goal: project.goal,
        photo: selected
          ? {
              id: selected.id,
              byte_count: selected.byte_count,
              content_type: selected.content_type,
            }
          : null,
        payload: {
          ...(approximate ? { approximate: true } : {}),
          expected_revision_id: project.revision_id,
          user_notes: notes.trim() || null,
          media_id: photo || null,
          provider_context_consented: true,
          provider_transfer_consented: !!photo,
          idempotency_key: authorization.replacement_idempotency_key,
        },
      };
      const retained = await retainReplacementConstruction(
        token,
        replacementSource.idempotency_key,
        record,
      );
      if (current !== epoch.current) return;
      setPending(retained);
      setNotes(retained.payload.user_notes ?? "");
      setPhoto(retained.payload.media_id ?? "");
      setResult(null);
      setUncertainDispatch(false);
    } catch (failure) {
      if (current === epoch.current)
        setError(
          failure instanceof ApiError
            ? failure
            : new ApiError(0, "recovery_storage", (failure as Error).message),
        );
    } finally {
      if (current === epoch.current) {
        setBusy(false);
        void checkStatus();
      }
    }
  }
  async function ask() {
    if (
      unavailable ||
      busy ||
      !consent ||
      (!!photo && !photoConsent) ||
      !eligible ||
      (approximate && !photo)
    )
      return;
    const record: PendingConstruction = pending ?? {
      version: 1,
      project_id: project.id,
      goal: project.goal,
      photo: selected
        ? {
            id: selected.id,
            byte_count: selected.byte_count,
            content_type: selected.content_type,
          }
        : null,
      payload: {
        ...(approximate ? { approximate: true } : {}),
        expected_revision_id: project.revision_id,
        user_notes: notes.trim() || null,
        media_id: photo || null,
        provider_context_consented: true,
        provider_transfer_consented: !!photo,
        idempotency_key: crypto.randomUUID(),
      },
    };
    const requestedContext = contextIdentity;
    manualController.current?.abort();
    const current = ++epoch.current;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError(null);
    setResult(null);
    setConsent(false);
    setPhotoConsent(false);
    setPending(record);
    try {
      // Retain the exact paid-request identity before dispatch, including retries.
      try {
        await retainConstruction(token, record);
      } catch (failure) {
        if (current === epoch.current) storageFailure(failure);
        return;
      }
      if (
        current !== epoch.current ||
        currentContext.current !== requestedContext
      )
        return;
      setProposalInFlight(true);
      const value = await proposeConstruction(
        token,
        project.id,
        record.payload,
        abort.signal,
      );
      if (
        current !== epoch.current ||
        currentContext.current !== requestedContext
      )
        return;
      setResult(value);
      setRestored(false);
      manualResultContext.current = JSON.stringify([
        requestedContext,
        approximate,
      ]);
      void checkStatus();
    } catch (failure) {
      if (current !== epoch.current) return;
      const apiError =
        failure instanceof ApiError
          ? failure
          : new ApiError(
              0,
              "network_error",
              "The outcome is unknown. Check the original request before starting another.",
            );
      setError(apiError);
      if (uncertainConstructionOutcome(apiError.code)) {
        setUncertainDispatch(true);
        void checkStatus();
      }
    } finally {
      if (current === epoch.current) {
        controller.current = null;
        setBusy(false);
        setProposalInFlight(false);
      }
    }
  }
  async function startAnother() {
    if (
      (!result && !constructionRequestCanRestart(error?.code)) ||
      !pending ||
      busy ||
      unavailable
    )
      return;
    const current = ++epoch.current;
    manualController.current?.abort();
    setBusy(true);
    setConsent(false);
    setPhotoConsent(false);
    try {
      await clearConstruction(token, pending);
      if (current !== epoch.current) return;
      setPending(null);
      setResult(null);
      setError(null);
    } catch (failure) {
      if (current === epoch.current) storageFailure(failure);
    } finally {
      if (current === epoch.current) setBusy(false);
    }
  }
  function cancel() {
    setUncertainDispatch(true);
    epoch.current++;
    controller.current?.abort();
    setBusy(false);
    setProposalInFlight(false);
    setError(
      new ApiError(
        0,
        "cancelled",
        "Stopped waiting. MetaMuse may still be processing the original request; check its outcome before starting another.",
      ),
    );
  }
  return (
    <section className="muse-panel" aria-labelledby="muse-construction-title">
      {savedManualError && (
        <p className="notice" role="status">
          {savedManualError}
        </p>
      )}
      <h2 id="muse-construction-title">
        {approximate
          ? "Create an illustrated concept"
          : "Invent with my materials"}
      </h2>
      <p>
        {approximate
          ? "MetaMuse proposes approximate dimensions and named pieces from your photo. Review them before viewing the illustrated concept."
          : "Show MetaMuse a saved photo and describe what you want. It proposes named pieces; the engine generates steps and checks saved materials with the fabrication engine."}
      </p>
      <p>
        <strong>Saved goal:</strong> {project.goal}
      </p>
      {!approximate && (
        <div aria-label="Saved material measurements" role="group">
          <h3>Saved material measurements</h3>
          <p className="help">
            Review each physical item in the inventory above. Enter missing
            measurements, confirm values you have checked, then save the
            inventory. These are saved records; photos and proposed geometry do
            not fill in measurements.
          </p>
          {!project.inventory_confirmed && (
            <p className="notice">
              The saved inventory has not been confirmed.
            </p>
          )}
          {(project.stocks ?? []).length === 0 && (
            <p className="notice">
              No saved materials yet. Add your physical materials in the
              inventory above and save them.
            </p>
          )}
          <ul>
            {(project.stocks ?? []).map((stock, stockIndex) => (
              <li key={stock.id} style={{ overflowWrap: "anywhere" }}>
                <strong>
                  Material {stockIndex + 1} · {stock.id}
                </strong>{" "}
                · {stock.material} {stock.kind} · saved condition:{" "}
                {stock.condition}
                <ul>
                  {materialMeasurementChecklist(stock).map((m) => (
                    <li key={m.field}>
                      {m.label}:{" "}
                      {m.value === null
                        ? "missing — measure this item"
                        : `${m.value} ${m.unit} — ${m.status} (source: ${m.source.replaceAll("_", " ")})`}
                      {m.status === "unconfirmed"
                        ? "; check and confirm in inventory"
                        : ""}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
          <p className="help">
            Confirmation alone does not establish fabrication readiness. The
            engine also checks material allocation, process and joint evidence.
          </p>
        </div>
      )}
      <label htmlFor="construction-notes">What should the design do?</label>
      <textarea
        id="construction-notes"
        value={notes}
        maxLength={1000}
        disabled={busy || !!pending}
        onChange={(e) => {
          setNotes(e.target.value);
          changed();
        }}
        placeholder="For example: hold my phone upright while leaving room for its cable."
      />
      <label htmlFor="construction-photo">
        {approximate ? "Choose a material photo" : "Material photo (optional)"}
      </label>
      <select
        id="construction-photo"
        value={photo}
        disabled={busy || !!pending}
        onChange={(e) => {
          setPhoto(e.target.value);
          changed();
        }}
      >
        <option value="">
          {approximate
            ? "Select a photo"
            : "Use saved materials without a photo"}
        </option>
        {photos.map((p, i) => (
          <option
            key={p.id}
            value={p.id}
            disabled={
              !["image/jpeg", "image/png"].includes(p.content_type) ||
              p.byte_count > 5_000_000
            }
          >
            Photo {i + 1} · {p.content_type}
          </option>
        ))}
      </select>
      <p className="help">
        A photo can suggest shapes and approximate dimensions. It cannot confirm
        measurements, available quantities, safety or joint strength.
      </p>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={consent}
          disabled={busy || unavailable}
          onChange={(e) => setConsent(e.target.checked)}
        />
        Send the saved goal, materials, profiles and these notes to Meta for
        this request. Provider usage may be charged.
      </label>
      {photo && (
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={photoConsent}
            disabled={busy || unavailable}
            onChange={(e) => setPhotoConsent(e.target.checked)}
          />
          Also send the selected saved photo to Meta for this request.
        </label>
      )}
      {inventoryStale && (
        <p className="notice">
          Save or reload your material edits before asking MetaMuse.
        </p>
      )}
      {project.active_version_id && (
        <p className="notice">
          This project already has a build. Use its fabrication and repair flow
          to preserve completed work.
        </p>
      )}
      {museAvailability?.enabled === false && (
        <p className="notice">{museAvailability.reason}</p>
      )}
      {pending && Boolean(pending.payload.approximate) !== approximate && (
        <p className="notice">
          An earlier request belongs to the other entry mode. Switch modes to
          check its outcome.
        </p>
      )}
      {stalePending && (
        <p className="notice" role="alert">
          The retained request belongs to an earlier inventory, goal or selected
          photo. Its original identity is preserved. New proposals and replay
          are blocked; restore the original saved context or ask the operator to
          reconcile this request.
        </p>
      )}
      <section
        aria-label="Saved construction request status"
        aria-live="polite"
      >
        {checkingStatus && <p>Checking saved request status...</p>}
        {statusError && <p role="alert">{statusError}</p>}
        {(blockingReceipts.length > 0 || uncertainDispatch) && (
          <p className="notice">
            A prior construction request is pending or its provider outcome is
            unknown. Generation remains blocked unless a separate replacement
            identity is explicitly authorized below. Checking status reads saved
            receipts only; it cannot recover a missing provider result or resume
            provider work.
          </p>
        )}
        {unresolvedReceipts.map((receipt) => (
          <div key={receipt.digest} style={{ overflowWrap: "anywhere" }}>
            <p>
              Stored request state: {receipt.state}. Stored cause:{" "}
              {receipt.error_code ?? "not recorded"}.
              {receipt.state === "unknown" &&
                " Its completion and usage remain unknown, including after a replacement."}
            </p>
            <details>
              <summary>Original request identity</summary>
              <p>Request digest: {receipt.digest}</p>
            </details>
          </div>
        ))}
        {replacementSource && !replacementPrepared && (
          <div className="notice">
            <p>
              A replacement is a separate paid generation. The original result
              and usage will remain unknown. This action authorizes one
              replacement identity; it does not send a model request. Review the
              notes and selected photo, then give fresh sharing consent and ask
              explicitly.
            </p>
            <button
              type="button"
              disabled={
                busy ||
                checkingStatus ||
                storageBlocked ||
                inventoryStale ||
                !!project.active_version_id ||
                !eligible ||
                (approximate && !photo)
              }
              onClick={() => void prepareReplacement()}
            >
              Authorize a separate paid replacement
            </button>
          </div>
        )}
        {replacementPrepared && (
          <p className="notice">
            Replacement identity prepared. The original unknown request is
            preserved. Fresh sharing consent and an explicit Ask are required;
            no model request starts automatically.
          </p>
        )}
        <button
          type="button"
          disabled={checkingStatus || busy}
          onClick={() => void checkStatus()}
        >
          Check request status
        </button>
      </section>
      <div className="muse-actions">
        <button
          type="button"
          className="primary"
          disabled={
            unavailable ||
            busy ||
            !consent ||
            (!!photo && !photoConsent) ||
            !eligible ||
            (approximate && !photo)
          }
          onClick={() => void ask()}
        >
          {isReplacement
            ? "Ask MetaMuse for the authorized replacement"
            : pending
              ? "Check original proposal request"
              : "Ask MetaMuse for shapes and steps"}
        </button>
        {(result || constructionRequestCanRestart(error?.code)) && pending && (
          <button
            type="button"
            disabled={busy || unavailable}
            onClick={() => void startAnother()}
          >
            Start another proposal
          </button>
        )}
      </div>
      <MuseRequestStatus
        busy={busy}
        pendingMessage="MetaMuse is proposing pieces. The engine will check each candidate before showing it."
        onCancel={cancel}
        errorCode={error?.code}
        errorMessage={error?.message}
        diagnostics={
          result ? museDiagnosticsFromResult(result.diagnostics) : null
        }
      />
      <CubeLoader
        busy={proposalInFlight && !unavailable}
        succeeded={
          !unavailable &&
          result !== null &&
          result.status !== "blocked" &&
          result.candidates.some((candidate) => candidate.construction !== null)
        }
      />
      {pending && !busy && (
        <p className="help">
          The original request identity is retained in this browser across
          navigation and reload. Checking it requires fresh consent. No request
          is sent automatically.
        </p>
      )}
      {result && (
        <div aria-live="polite">
          {restored && (
            <p className="notice">
              Saved proposal restored without a model request. Its original
              entry mode is not recorded, so review its proposed dimensions
              again. This does not resolve any unknown provider outcome.
            </p>
          )}
          {approximate ? (
            <p>
              Review the proposed materials and pieces. Nothing has been built
              or physically tested.
            </p>
          ) : (
            <p>
              Proposal result: {result.status.replaceAll("_", " ")}. Nothing is
              approved, cut, joined or recorded as physically tested.
            </p>
          )}
          {result.questions.length > 0 && (
            <details open={!approximate}>
              <summary>Questions and measurements</summary>
              <ul>
                {result.questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </details>
          )}
          {approximate && (
            <p>
              To correct an estimate, choose Start another proposal and add your
              corrections to the design notes before asking again. The revised
              request will generate a new concept.
            </p>
          )}
          {result.candidates.map((c) => (
            <Candidate
              key={c.candidate_id}
              candidate={c}
              approximate={approximate}
              restored={restored}
            />
          ))}
        </div>
      )}
    </section>
  );
}
