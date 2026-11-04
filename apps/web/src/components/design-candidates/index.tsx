import { useEffect, useRef, useState } from "react";
import type { StandDesign } from "../../lib/generated/contracts";
import Diagram from "../manual-diagram";
import {
  type Candidate,
  PARAMETERS,
  type Probe,
  type Search,
  type SearchContext,
  type SearchParameter,
  SynthesisRequestError,
  domainValues,
  synthesisApi,
} from "./client";

const LABELS: Record<SearchParameter, string> = {
  part_width_mm: "Panel width",
  support_length_mm: "Support length",
  footprint_depth_mm: "Base depth",
};
const STATUS_TEXT: Record<string, string> = {
  modeled_pass: "Checked by the engine",
  modeled_failure: "Fails a modeled check",
  missing_input: "Needs measurements",
  unsupported: "Not modeled",
  evidence_incompatible: "Saved measurements do not apply",
  unverified: "Not verified",
};
const SEARCH_TEXT: Record<Search["status"], string> = {
  candidates_found: "Designs that fit your saved stock",
  infeasible: "No design in the searched sizes fits your saved stock.",
  search_exhausted:
    "The search budget ran out before any design was found. This is not proof that none exists.",
  needs_input: "Some saved facts are missing, so nothing was searched.",
  active_build:
    "A build is active. New designs cannot replace it; use the repair flow.",
};

function mm(value: number | null | undefined) {
  return value == null ? "unknown" : `${Math.round(value * 10) / 10} mm`;
}
function area(value: number) {
  return `${Math.round(value / 100) / 100} dm²`;
}
function message(error: unknown) {
  return error instanceof Error ? error.message : "The request failed.";
}

function CandidateColumn({
  report,
  label,
}: {
  report: Candidate;
  label: string;
}) {
  const brace = report.pieces.find((p) => p.dependent);
  const material = report.material;
  const cut = report.construction.find((s) => s.operation_type === "cut_rect");
  return (
    <article className="design-candidate" aria-label={label}>
      <h4>{label}</h4>
      <dl className="design-candidate-facts">
        <dt>Sheet</dt>
        <dd>{report.design.sheet_stock_id}</dd>
        {PARAMETERS.map((name) => (
          <div key={name}>
            <dt>{LABELS[name]}</dt>
            <dd>{mm(report.design[name])}</dd>
          </div>
        ))}
        <dt>Brace (calculated)</dt>
        <dd>{mm(brace?.height_mm)}</dd>
        <dt>Lip / angle</dt>
        <dd>
          {mm(report.design.lip_mm)} / {report.design.support_angle_deg}°
        </dd>
        {material && (
          <>
            <dt>Sheet region used</dt>
            <dd>
              {area(material.region_area_mm2)} (panels{" "}
              {area(material.part_area_mm2)}, waste{" "}
              {area(material.unallocated_area_mm2)})
            </dd>
            <dt>Tape</dt>
            <dd>
              {mm(material.tape_length_mm)} of {material.tape_stock_id}; left
              after: {mm(material.tape_remaining_after_mm)}
            </dd>
          </>
        )}
      </dl>
      <h5>Pieces</h5>
      <ul>
        {report.pieces.map((p) => (
          <li key={p.piece.part_id}>
            <strong>{p.piece.display_name}</strong> ({p.piece.reference}):{" "}
            {mm(p.width_mm)} × {mm(p.height_mm)}. {p.derivation}
          </li>
        ))}
      </ul>
      <h5>Checks</h5>
      <ul className="design-candidate-checks">
        {report.checks.map((c) => (
          <li key={c.check_id} data-status={c.status}>
            <strong>
              {c.check_id}: {STATUS_TEXT[c.status]}
            </strong>{" "}
            {c.detail}
          </li>
        ))}
      </ul>
      <details>
        <summary>Construction steps ({report.construction.length})</summary>
        <ol>
          {report.construction.map((s) => (
            <li key={s.operation_id}>
              <strong>{s.title}.</strong> {s.instruction}
            </li>
          ))}
        </ol>
        {report.cut_layout_svg && cut && (
          <Diagram
            panel={{
              operation_id: cut.operation_id,
              part_ids: cut.part_ids,
              checkpoint_ids: [],
              dependency_hash: report.candidate_id,
              svg: report.cut_layout_svg,
              tools: [],
              instruction: cut.instruction,
            }}
          />
        )}
      </details>
    </article>
  );
}

export default function DesignCandidates({
  token,
  context,
  disabled,
  onSelected,
}: {
  token: string;
  context: SearchContext;
  disabled: boolean;
  onSelected: (versionId: string) => void;
}) {
  const [result, setResult] = useState<Search | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [probe, setProbe] = useState<{
    candidateId: string;
    parameter: SearchParameter;
    value: number | null;
    result: Probe | null;
  } | null>(null);
  // An ambiguous choice keeps its key so a retry cannot save a second preview.
  const [pending, setPending] = useState<{
    key: string;
    design: StandDesign;
    searchId: string;
  } | null>(null);
  const [saved, setSaved] = useState("");
  const controller = useRef<AbortController | null>(null);
  const contextKey = JSON.stringify(context);

  useEffect(() => {
    controller.current?.abort();
    setResult(null);
    setProbe(null);
    setPending(null);
    setSaved("");
    setError("");
  }, [contextKey]);
  useEffect(() => () => controller.current?.abort(), []);

  async function run<T>(work: (signal: AbortSignal) => Promise<T>) {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setBusy(true);
    setError("");
    try {
      return await work(next.signal);
    } finally {
      if (controller.current === next) setBusy(false);
    }
  }

  async function search() {
    try {
      const next = await run((signal) =>
        synthesisApi(token, context.projectId).search(context, signal),
      );
      setResult(next);
      setProbe(null);
      setSaved("");
    } catch (failure) {
      setError(message(failure));
    }
  }

  async function runProbe(candidate: Candidate) {
    if (!result || !probe || probe.value == null) return;
    const { parameter, value } = probe;
    try {
      const outcome = await run((signal) =>
        synthesisApi(token, context.projectId).probe(
          context,
          result.search_id,
          candidate.design,
          parameter,
          value,
          signal,
        ),
      );
      setProbe((current) => current && { ...current, result: outcome });
    } catch (failure) {
      if (failure instanceof SynthesisRequestError && failure.stale)
        setResult(null);
      setError(message(failure));
    }
  }

  async function choose(design: StandDesign) {
    if (!result) return;
    const attempt =
      pending &&
      pending.searchId === result.search_id &&
      JSON.stringify(pending.design) === JSON.stringify(design)
        ? pending
        : { key: crypto.randomUUID(), design, searchId: result.search_id };
    setPending(attempt);
    try {
      const outcome = await run((signal) =>
        synthesisApi(token, context.projectId).select(
          context,
          attempt.searchId,
          attempt.design,
          attempt.key,
          signal,
        ),
      );
      setPending(null);
      if (outcome.status === "accepted" && outcome.version) {
        setSaved(outcome.version.version_id);
        onSelected(outcome.version.version_id);
      } else {
        setError(
          (outcome.blockers ?? []).map((b) => b.message).join(" ") ||
            "This design could not be saved.",
        );
      }
    } catch (failure) {
      if (!(failure instanceof SynthesisRequestError && failure.retry))
        setPending(null);
      if (failure instanceof SynthesisRequestError && failure.stale)
        setResult(null);
      setError(message(failure));
    }
  }

  const candidates = result?.candidates ?? [];
  const probeBase =
    candidates.find((c) => c.candidate_id === probe?.candidateId) ?? null;
  const values =
    result && probe && probeBase
      ? domainValues(result, probeBase.design.sheet_stock_id, probe.parameter)
      : [];

  return (
    <section
      className="design-candidates"
      aria-labelledby="design-search-title"
    >
      <h3 id="design-search-title">Search designs from your saved stock</h3>
      <p>
        FORMA tries a limited set of sizes for the supported three-panel stand,
        using only the stock you saved. Searching and trying changes save
        nothing. Results are proposals, not tested builds.
      </p>
      <button
        type="button"
        onClick={() => void search()}
        disabled={disabled || busy}
      >
        {busy && !result ? "Searching…" : "Search stock-feasible designs"}
      </button>
      <div aria-live="polite">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {saved && (
          <p className="success">
            Saved as a proposed plan ({saved}). Review it below and approve it
            when you are ready to build. Nothing is approved yet.
          </p>
        )}
      </div>
      {result && (
        <div className="design-search-result">
          <p>
            <strong>{SEARCH_TEXT[result.status]}</strong> Checked{" "}
            {result.nodes_evaluated} of {result.nodes_total} size combinations.
            {result.exhausted &&
              ` The ${result.exhausted === "node_budget" ? "step" : "time"} budget ran out before every combination was checked.`}
          </p>
          {result.blockers.length > 0 && (
            <ul>
              {result.blockers.map((b, index) => (
                <li key={`${b.code}-${index}`}>{b.message}</li>
              ))}
            </ul>
          )}
          {candidates.length > 0 && (
            <div className="design-candidate-grid">
              {candidates.map((c, index) => (
                <div key={c.candidate_id}>
                  <CandidateColumn
                    report={c}
                    label={`Design ${String.fromCharCode(65 + index)}`}
                  />
                  <div className="design-candidate-actions">
                    <button
                      type="button"
                      disabled={disabled || busy}
                      onClick={() => void choose(c.design)}
                    >
                      {pending &&
                      JSON.stringify(pending.design) ===
                        JSON.stringify(c.design)
                        ? "Retry saving this design"
                        : `Use design ${String.fromCharCode(65 + index)}`}
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      onClick={() =>
                        setProbe({
                          candidateId: c.candidate_id,
                          parameter: "footprint_depth_mm",
                          value: null,
                          result: null,
                        })
                      }
                    >
                      Try a size change
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          {probe && probeBase && (
            <fieldset className="design-probe">
              <legend>
                Try one size change
                {` on ${probeBase.candidate_id}`}
              </legend>
              <label htmlFor="probe-parameter">Dimension</label>
              <select
                id="probe-parameter"
                value={probe.parameter}
                onChange={(event) =>
                  setProbe({
                    ...probe,
                    parameter: event.target.value as SearchParameter,
                    value: null,
                    result: null,
                  })
                }
              >
                {PARAMETERS.map((name) => (
                  <option key={name} value={name}>
                    {LABELS[name]}
                  </option>
                ))}
              </select>
              <label htmlFor="probe-value">New value</label>
              <select
                id="probe-value"
                value={probe.value ?? ""}
                onChange={(event) =>
                  setProbe({
                    ...probe,
                    value: event.target.value
                      ? Number(event.target.value)
                      : null,
                    result: null,
                  })
                }
              >
                <option value="">Choose a value</option>
                {values.map((v) => (
                  <option key={v} value={v}>
                    {v} mm
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={busy || probe.value == null}
                onClick={() => void runProbe(probeBase)}
              >
                Check this change
              </button>
              {probe.result && (
                <div className="design-probe-result" aria-live="polite">
                  {probe.result.status === "evaluated" &&
                    probe.result.report && (
                      <>
                        <p>
                          {probe.result.report.status === "acceptable"
                            ? "This change still fits your stock. "
                            : "This change fails a modeled check. "}
                          Recalculated pieces:{" "}
                          {probe.result.changed_piece_ids.join(", ") || "none"}.
                        </p>
                        <CandidateColumn
                          report={probe.result.report}
                          label="Changed design"
                        />
                        {probe.result.report.status === "acceptable" && (
                          <button
                            type="button"
                            disabled={disabled || busy}
                            onClick={() =>
                              probe.result?.report &&
                              void choose(probe.result.report.design)
                            }
                          >
                            Use the changed design
                          </button>
                        )}
                      </>
                    )}
                  {probe.result.status !== "evaluated" && (
                    <p>
                      {probe.result.blockers.map((b) => b.message).join(" ")}
                    </p>
                  )}
                </div>
              )}
            </fieldset>
          )}
          <details>
            <summary>How designs are chosen and what is not checked</summary>
            <p>{result.ranking}</p>
            <ul>
              {result.limitations.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </section>
  );
}
