import { useEffect, useRef, useState } from "react";
import type {
  SynthesisMuseRequest,
  SynthesisSelectRequest,
} from "../../lib/generated/api-contracts";
import type { StandDesign } from "../../lib/generated/contracts";
import Diagram from "../manual-diagram";
import {
  type Candidate,
  type MuseResult,
  PARAMETERS,
  type Probe,
  type Search,
  type SearchContext,
  type SearchParameter,
  SynthesisRequestError,
  domainValues,
  museBody,
  museReceipts,
  selectionBody,
  selectionReceipts,
  synthesisApi,
} from "./client";
import ResearchPanel, {
  type ResearchAdvice,
  ResearchRecommendation,
} from "./research-panel";

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
  advice,
}: {
  report: Candidate;
  label: string;
  advice?: ResearchAdvice | null;
}) {
  const brace = report.pieces.find((p) => p.dependent);
  const material = report.material;
  const cut = report.construction.find((s) => s.operation_type === "cut_rect");
  return (
    <article className="design-candidate" aria-label={label}>
      <h4>{label}</h4>
      {advice && <ResearchRecommendation advice={advice} />}
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

type ProbeState = {
  candidateId: string;
  parameter: SearchParameter;
  value: number | null;
  result: Probe | null;
};

function same(a: unknown, b: unknown) {
  return JSON.stringify(a) === JSON.stringify(b);
}

export default function DesignCandidates({
  token,
  context,
  disabled,
  museEnabled,
  onSelected,
}: {
  token: string;
  context: SearchContext;
  disabled: boolean;
  museEnabled: boolean;
  onSelected: (versionId: string) => void;
}) {
  const [result, setResult] = useState<Search | null>(null);
  const [researchEpoch, setResearchEpoch] = useState(0);
  const [stockSearchBlocked, setStockSearchBlocked] = useState(true);
  const [researchAdvice, setResearchAdvice] = useState<ResearchAdvice | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [probe, setProbe] = useState<ProbeState | null>(null);
  // Sent requests whose outcome is unknown. They live in browser storage so a
  // reload retries the same key instead of saving or dispatching twice.
  const [pendingSelect, setPendingSelect] =
    useState<SynthesisSelectRequest | null>(null);
  const [pendingMuse, setPendingMuse] = useState<SynthesisMuseRequest | null>(
    null,
  );
  // Each receipt kind loads and clears on its own: an unreadable one never
  // erases or blocks the other.
  const [selectReceiptError, setSelectReceiptError] = useState("");
  const [museReceiptError, setMuseReceiptError] = useState("");
  const [saved, setSaved] = useState("");
  const [question, setQuestion] = useState("");
  const [consented, setConsented] = useState(false);
  const [muse, setMuse] = useState<MuseResult | null>(null);
  const controller = useRef<AbortController | null>(null);
  const contextKey = JSON.stringify(context);

  useEffect(() => {
    controller.current?.abort();
    setResult(null);
    setResearchAdvice(null);
    setProbe(null);
    setSaved("");
    setError("");
    setMuse(null);
    setConsented(false);
    let live = true;
    setPendingSelect(null);
    setPendingMuse(null);
    selectionReceipts.pending(token, context.projectId).then(
      (body) => {
        if (!live) return;
        setPendingSelect(body);
        setSelectReceiptError("");
      },
      (failure: unknown) => {
        if (live) setSelectReceiptError(message(failure));
      },
    );
    museReceipts.pending(token, context.projectId).then(
      (body) => {
        if (!live) return;
        setPendingMuse(body);
        setMuseReceiptError("");
      },
      (failure: unknown) => {
        if (live) setMuseReceiptError(message(failure));
      },
    );
    return () => {
      live = false;
    };
    // contextKey covers every context field.
  }, [contextKey, token]);
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
    // Unmount the research panel's current request and ignore late replies
    // when the builder switches back to ordinary stock search.
    setResearchEpoch((epoch) => epoch + 1);
    setResearchAdvice(null);
    try {
      const next = await run((signal) =>
        synthesisApi(token, context.projectId).search(context, signal),
      );
      setResult(next);
      setProbe(null);
      setSaved("");
      setMuse(null);
    } catch (failure) {
      setError(message(failure));
    }
  }

  function reviewResearch(next: Search, recommendation: ResearchAdvice | null) {
    setResult(next);
    setResearchAdvice(recommendation);
    setProbe(null);
    setSaved("");
    setMuse(null);
    setError("");
  }

  async function runProbe(candidate: Candidate) {
    if (!result || !probe || probe.value == null) return;
    const submitted = {
      candidateId: candidate.candidate_id,
      parameter: probe.parameter,
      value: probe.value,
    };
    try {
      const outcome = await run((signal) =>
        synthesisApi(token, context.projectId).probe(
          context,
          result.search_id,
          candidate.design,
          submitted.parameter,
          submitted.value,
          signal,
        ),
      );
      // Attach only to the controls that were submitted; a changed selector
      // must never display another value's result.
      setProbe((current) =>
        current &&
        current.candidateId === submitted.candidateId &&
        current.parameter === submitted.parameter &&
        current.value === submitted.value &&
        outcome.parameter === submitted.parameter &&
        outcome.value_mm === submitted.value
          ? { ...current, result: outcome }
          : current,
      );
    } catch (failure) {
      if (failure instanceof SynthesisRequestError && failure.stale)
        setResult(null);
      setError(message(failure));
    }
  }

  async function sendSelection(body: SynthesisSelectRequest) {
    try {
      await selectionReceipts.retain(token, context.projectId, body);
    } catch (failure) {
      setError(message(failure));
      return;
    }
    setPendingSelect(body);
    try {
      const outcome = await run((signal) =>
        synthesisApi(token, context.projectId).select(body, signal),
      );
      await selectionReceipts.clear(token, context.projectId, body);
      setPendingSelect(null);
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
      if (!(failure instanceof SynthesisRequestError && failure.retry)) {
        await selectionReceipts.clear(token, context.projectId, body);
        setPendingSelect(null);
      }
      if (failure instanceof SynthesisRequestError && failure.stale)
        setResult(null);
      setError(message(failure));
    }
  }

  function choose(design: StandDesign) {
    if (!result) return;
    if (pendingSelect) {
      if (
        pendingSelect.search_id === result.search_id &&
        same(pendingSelect.design, design)
      )
        return void sendSelection(pendingSelect);
      setError(
        "An earlier design choice has an unknown outcome. Retry it before choosing another.",
      );
      return;
    }
    void sendSelection(
      selectionBody(context, result.search_id, design, crypto.randomUUID()),
    );
  }

  async function sendMuse(body: SynthesisMuseRequest) {
    try {
      await museReceipts.retain(token, context.projectId, body);
    } catch (failure) {
      setError(message(failure));
      return;
    }
    setPendingMuse(body);
    try {
      const outcome = await run((signal) =>
        synthesisApi(token, context.projectId).explain(body, signal),
      );
      await museReceipts.clear(token, context.projectId, body);
      setPendingMuse(null);
      setMuse(outcome);
    } catch (failure) {
      if (!(failure instanceof SynthesisRequestError && failure.retry)) {
        await museReceipts.clear(token, context.projectId, body);
        setPendingMuse(null);
      }
      setError(message(failure));
    }
  }

  function ask() {
    if (!result || !consented) return;
    if (pendingMuse) {
      setError(
        "An earlier MetaMuse comparison has an unknown outcome. Retry it before asking again.",
      );
      return;
    }
    void sendMuse(
      museBody(
        context,
        result.search_id,
        crypto.randomUUID(),
        question.trim() || null,
      ),
    );
  }

  async function discardSelectReceipt() {
    await selectionReceipts.discard(token, context.projectId);
    setPendingSelect(null);
    setSelectReceiptError("");
  }

  async function discardMuseReceipt() {
    await museReceipts.discard(token, context.projectId);
    setPendingMuse(null);
    setMuseReceiptError("");
  }

  const candidates = result?.candidates ?? [];
  const probeBase =
    candidates.find((c) => c.candidate_id === probe?.candidateId) ?? null;
  const values =
    result && probe && probeBase
      ? domainValues(result, probeBase.design.sheet_stock_id, probe.parameter)
      : [];
  const blocked = disabled || busy || selectReceiptError !== "";
  const museBlocked = disabled || busy || museReceiptError !== "";
  // An answer recovered from an earlier search describes other designs: show
  // it as history and never offer to choose from it.
  const museCurrent = muse !== null && muse.search_id === result?.search_id;

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
        disabled={disabled || busy || stockSearchBlocked}
      >
        {busy && !result ? "Searching…" : "Search stock-feasible designs"}
      </button>
      <ResearchPanel
        key={`${contextKey}:${researchEpoch}`}
        token={token}
        context={context}
        disabled={disabled || busy}
        onInvalidate={(scope) => {
          setResearchAdvice(null);
          if (scope === "search") {
            setResult(null);
            setProbe(null);
            setMuse(null);
          }
        }}
        onStockSearchBlocked={setStockSearchBlocked}
        onReview={reviewResearch}
      />
      <div aria-live="polite">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {selectReceiptError && (
          <div className="error" role="alert">
            <p>{selectReceiptError}</p>
            <button
              type="button"
              className="secondary"
              onClick={() => void discardSelectReceipt()}
            >
              Clear the unverifiable design choice
            </button>
          </div>
        )}
        {museReceiptError && (
          <div className="error" role="alert">
            <p>{museReceiptError}</p>
            <button
              type="button"
              className="secondary"
              onClick={() => void discardMuseReceipt()}
            >
              Clear the unverifiable MetaMuse request
            </button>
          </div>
        )}
        {pendingSelect && (
          <div className="notice">
            <p>
              A design choice was sent but its result is unknown. Retrying uses
              the same request, so it cannot save a second plan.
            </p>
            <button
              type="button"
              disabled={blocked}
              onClick={() => void sendSelection(pendingSelect)}
            >
              Retry saving that design
            </button>
          </div>
        )}
        {saved && (
          <p className="success">
            Saved as a proposed plan ({saved}). Review it below and approve it
            when you are ready to build. Nothing is approved yet.
          </p>
        )}
      </div>
      {result && !stockSearchBlocked && (
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
                    advice={
                      researchAdvice?.candidateId === c.candidate_id
                        ? researchAdvice
                        : null
                    }
                  />
                  <div className="design-candidate-actions">
                    <button
                      type="button"
                      disabled={blocked}
                      onClick={() => choose(c.design)}
                    >
                      {`Use design ${String.fromCharCode(65 + index)}`}
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
              <legend>Try one size change on {probeBase.candidate_id}</legend>
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
                <ProbeOutcome
                  outcome={probe.result}
                  label="Changed design"
                  disabled={blocked}
                  onChoose={choose}
                />
              )}
            </fieldset>
          )}
          {candidates.length > 0 && museEnabled && (
            <fieldset className="design-muse">
              <legend>Ask MetaMuse to compare these designs</legend>
              <p>
                MetaMuse reads the engine&apos;s results for these designs and
                may ask the engine to check one size from the same list. Its
                words are a proposal; it cannot add measurements or approve a
                plan.
              </p>
              <label htmlFor="design-muse-question">Question (optional)</label>
              <textarea
                id="design-muse-question"
                maxLength={500}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
              />
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={consented}
                  onChange={(event) => setConsented(event.target.checked)}
                />
                Share these proposed designs (no photos) with MetaMuse
              </label>
              <button
                type="button"
                disabled={museBlocked || !consented || pendingMuse !== null}
                onClick={ask}
              >
                Ask MetaMuse
              </button>
              {pendingMuse && (
                <button
                  type="button"
                  disabled={museBlocked}
                  onClick={() => void sendMuse(pendingMuse)}
                >
                  Retry the unresolved MetaMuse request
                </button>
              )}
              {muse && (
                <article
                  className="design-muse-answer"
                  aria-label={
                    museCurrent
                      ? "MetaMuse comparison"
                      : "Earlier MetaMuse comparison"
                  }
                >
                  {!museCurrent && (
                    <p className="notice">
                      This answer is about an earlier search. The designs it
                      discusses may no longer match your saved stock, so it
                      cannot be used to choose a design. Search again and ask
                      again if you need a current comparison.
                    </p>
                  )}
                  <p>{muse.explanation.summary}</p>
                  <ul>
                    {(muse.explanation.candidate_notes ?? []).map((note) => (
                      <li key={note.candidate_id}>
                        <strong>{note.candidate_id}:</strong> {note.note}
                      </li>
                    ))}
                    {(muse.explanation.unresolved ?? []).map((text) => (
                      <li key={text}>Still unknown: {text}</li>
                    ))}
                    {(muse.explanation.questions ?? []).map((text) => (
                      <li key={text}>Question: {text}</li>
                    ))}
                  </ul>
                  {muse.engine_probe && (
                    <ProbeOutcome
                      outcome={muse.engine_probe}
                      label="Engine check requested by MetaMuse"
                      disabled={blocked}
                      onChoose={museCurrent ? choose : undefined}
                    />
                  )}
                  <p className="help">
                    Model wording is not a physical test.
                    {muse.usage.input_tokens != null &&
                      ` Reported usage: ${muse.usage.input_tokens} input and ${muse.usage.output_tokens ?? "unknown"} output tokens.`}
                  </p>
                </article>
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

function ProbeOutcome({
  outcome,
  label,
  disabled,
  onChoose,
}: {
  outcome: Probe;
  label: string;
  disabled: boolean;
  onChoose?: (design: StandDesign) => void;
}) {
  const report = outcome.report;
  return (
    <div className="design-probe-result" aria-live="polite">
      <p>
        Engine result for {LABELS[outcome.parameter]} = {outcome.value_mm} mm:{" "}
        {outcome.status === "evaluated" && report
          ? report.status === "acceptable"
            ? `still fits your stock. Recalculated pieces: ${outcome.changed_piece_ids.join(", ") || "none"}.`
            : "fails a modeled check."
          : outcome.blockers.map((b) => b.message).join(" ")}
      </p>
      {outcome.status === "evaluated" && report && (
        <>
          <CandidateColumn report={report} label={label} />
          {report.status === "acceptable" && onChoose && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => onChoose(report.design)}
            >
              Use the changed design
            </button>
          )}
        </>
      )}
    </div>
  );
}
