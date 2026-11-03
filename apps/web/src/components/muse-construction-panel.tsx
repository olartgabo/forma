"use client";

import { useEffect, useRef, useState } from "react";
import type {
  Media,
  Project,
  MuseConstructionResult,
  MuseConstructionCandidateResult,
} from "../lib/generated/api-contracts";
import type { ConstructionPlan } from "../lib/generated/contracts";
import type { MuseAvailability } from "../lib/muse-provider";
import { ApiError } from "../lib/api";
import { proposeConstruction } from "../lib/muse-construction-client";
import {
  pendingConstruction,
  retainConstruction,
  clearConstruction,
  constructionContextChanged,
  constructionRequestCanRestart,
  type PendingConstruction,
} from "../lib/muse-construction-pending";
import { museDiagnosticsFromResult } from "../lib/provider-usage";
import MuseRequestStatus from "./muse-request-status";
import {
  constructionStepTitle,
  constructionPiecePresence,
  materialMeasurementChecklist,
} from "../lib/muse-construction-guidance";

function ConstructionPreview({ plan }: { plan: ConstructionPlan }) {
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
  const a = (yaw * Math.PI) / 180,
    b = (pitch * Math.PI) / 180;
  function project(p: { x: number; y: number; z: number }) {
    const x = p.x * Math.cos(a) - p.y * Math.sin(a);
    const y = p.x * Math.sin(a) + p.y * Math.cos(a);
    return {
      x,
      y: -(y * Math.sin(b) + p.z * Math.cos(b)),
      depth: y * Math.cos(b) - p.z * Math.sin(b),
    };
  }
  const facets = step.analysis.facets.map((f) => ({
    ...f,
    points: f.vertices.map(project),
    center: project(f.centroid),
  }));
  const points = facets.flatMap((f) => f.points);
  const minX = Math.min(0, ...points.map((p) => p.x)),
    maxX = Math.max(0, ...points.map((p) => p.x));
  const minY = Math.min(0, ...points.map((p) => p.y)),
    maxY = Math.max(0, ...points.map((p) => p.y));
  const scale = 310 / Math.max(maxX - minX, maxY - minY, 0.01);
  const x = (v: number) => 200 + (v - (minX + maxX) / 2) * scale;
  const y = (v: number) => 190 + (v - (minY + maxY) / 2) * scale;
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
        <p>{step.instruction}</p>
        {step.requires_external_support && (
          <p className="notice">
            Self-support is not established at this step. Temporary support has
            not been modeled.
          </p>
        )}
        {step.unresolved_predicates.length > 0 && (
          <div
            className="notice"
            role="note"
            aria-label="Unresolved checks for this step"
          >
            <strong>Unresolved checks for this step</strong>
            <ul>
              {step.unresolved_predicates.map((v, i) => (
                <li key={i}>{v}</li>
              ))}
            </ul>
          </div>
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
              stroke="#35584a"
              strokeWidth="1.5"
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
        Drag to turn the proposed model. Camera changes do not change its
        physics.
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
      <ol>
        {plan.piece_catalog.map((p) => (
          <li key={p.part_id} style={{ overflowWrap: "anywhere" }}>
            {p.display_name} · {p.reference} ·{" "}
            {p.geometry_class.replaceAll("_", " ")}
            {p.role ? ` · proposed role: ${p.role}` : ""}
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
}: {
  candidate: MuseConstructionCandidateResult;
}) {
  return (
    <article className="muse-result" style={{ overflowWrap: "anywhere" }}>
      <h3>{candidate.title}</h3>
      <p>{candidate.rationale}</p>
      <p>Engine result: {candidate.status.replaceAll("_", " ")}</p>
      {candidate.blockers.length > 0 && (
        <ul>
          {candidate.blockers.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}
      {candidate.construction && (
        <ConstructionPreview
          key={candidate.construction.target_hash}
          plan={candidate.construction}
        />
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
  token,
  project,
  photos,
  inventoryStale,
  disabled,
  museAvailability,
}: {
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
  const [result, setResult] = useState<MuseConstructionResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [pending, setPending] = useState<PendingConstruction | null>(null);
  const [recoveryContext, setRecoveryContext] = useState<string | null>(null);
  const [storageBlocked, setStorageBlocked] = useState(false);
  const controller = useRef<AbortController | null>(null);
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
  function changed() {
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
    disabled ||
    inventoryStale ||
    !!project.active_version_id ||
    museAvailability?.enabled === false ||
    recoveryContext !== contextIdentity ||
    storageBlocked ||
    stalePending;
  async function ask() {
    if (
      unavailable ||
      busy ||
      !consent ||
      (!!photo && !photoConsent) ||
      !eligible
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
        expected_revision_id: project.revision_id,
        user_notes: notes.trim() || null,
        media_id: photo || null,
        provider_context_consented: true,
        provider_transfer_consented: !!photo,
        idempotency_key: crypto.randomUUID(),
      },
    };
    const requestedContext = contextIdentity;
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
    } finally {
      if (current === epoch.current) {
        controller.current = null;
        setBusy(false);
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
    epoch.current++;
    controller.current?.abort();
    setBusy(false);
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
      <h2 id="muse-construction-title">Invent with my materials</h2>
      <p>
        Show MetaMuse a saved photo and describe what you want. It proposes
        named pieces; the engine generates steps and checks the saved materials
        with the fabrication engine.
      </p>
      <p>
        <strong>Saved goal:</strong> {project.goal}
      </p>
      <div aria-label="Saved material measurements" role="group">
        <h3>Saved material measurements</h3>
        <p className="help">
          Review each physical item in the inventory above. Enter missing
          measurements, confirm values you have checked, then save the
          inventory. These are saved records; photos and proposed geometry do
          not fill in measurements.
        </p>
        {!project.inventory_confirmed && (
          <p className="notice">The saved inventory has not been confirmed.</p>
        )}
        {(project.stocks ?? []).length === 0 && (
          <p className="notice">
            No saved materials yet. Add your physical materials in the inventory
            above and save them.
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
      <label htmlFor="construction-photo">Material photo (optional)</label>
      <select
        id="construction-photo"
        value={photo}
        disabled={busy || !!pending}
        onChange={(e) => {
          setPhoto(e.target.value);
          changed();
        }}
      >
        <option value="">Use saved materials without a photo</option>
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
        A photo can suggest shapes and labels. It cannot confirm dimensions,
        available quantities or joint strength. Save measured materials above;
        missing facts remain questions or blockers.
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
      {stalePending && (
        <p className="notice" role="alert">
          The retained request belongs to an earlier inventory, goal or selected
          photo. Its original identity is preserved. New proposals and replay
          are blocked; restore the original saved context or ask the operator to
          reconcile this request.
        </p>
      )}
      <div className="muse-actions">
        <button
          type="button"
          className="primary"
          disabled={
            unavailable ||
            busy ||
            !consent ||
            (!!photo && !photoConsent) ||
            !eligible
          }
          onClick={() => void ask()}
        >
          {pending
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
      {pending && !busy && (
        <p className="help">
          The original request identity is retained in this browser across
          navigation and reload. Checking it requires fresh consent. No request
          is sent automatically.
        </p>
      )}
      {result && (
        <div aria-live="polite">
          <p>
            Proposal result: {result.status.replaceAll("_", " ")}. Nothing is
            approved, cut, joined or recorded as physically tested.
          </p>
          {result.questions.length > 0 && (
            <>
              <h3>Questions and measurements</h3>
              <ul>
                {result.questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </>
          )}
          {result.candidates.map((c) => (
            <Candidate key={c.candidate_id} candidate={c} />
          ))}
        </div>
      )}
    </section>
  );
}
