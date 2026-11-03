"use client";

import { useEffect, useRef, useState } from "react";
import type {
  StabilityMuseResult,
  StabilityReportComparison,
  StabilityReportDetail,
  StabilityReportSummary,
} from "../../lib/generated/api-contracts";
import type { ExpectedContext } from "./client";
import { stabilityApi, type SaveResult } from "./history-client";

const label = (value: string) => value.replaceAll("_", " ");
const number = (value: number) => Number(value.toPrecision(5)).toString();
const shortId = (id: string) => id.slice("stability-report-".length, 29);
const staleText: Record<string, string> = {
  plan_changed: "the active plan changed",
  inventory_changed: "the inventory changed",
  history_changed: "build history or measurements changed",
  evidence_invalidated: "its measurement evidence was invalidated",
};
function freshness(summary: StabilityReportSummary) {
  return summary.freshness.current
    ? "Current"
    : `Stale — ${(summary.freshness.stale_reasons ?? []).map((r) => staleText[r]).join("; ")}`;
}
function newKey() {
  return `stability-${crypto.randomUUID()}`;
}

export default function ReportHistory({
  token,
  expected,
  disabled = false,
}: {
  token: string;
  expected: ExpectedContext;
  disabled?: boolean;
}) {
  const api = stabilityApi(token, expected.projectId);
  const mounted = useRef(true);
  const controller = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastSave, setLastSave] = useState<SaveResult | null>(null);
  const [reports, setReports] = useState<readonly StabilityReportSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<readonly string[]>([]);
  const [detail, setDetail] = useState<StabilityReportDetail | null>(null);
  const [comparison, setComparison] =
    useState<StabilityReportComparison | null>(null);
  const [consent, setConsent] = useState(false);
  const [question, setQuestion] = useState("");
  const [muse, setMuse] = useState<StabilityMuseResult | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);

  async function run<T>(
    name: string,
    work: (signal: AbortSignal) => Promise<T>,
  ) {
    controller.current?.abort();
    const own = new AbortController();
    controller.current = own;
    const timeout = setTimeout(() => own.abort(), 60000);
    setBusy(name);
    setError(null);
    try {
      const value = await work(own.signal);
      return mounted.current && !own.signal.aborted ? value : null;
    } catch (e) {
      if (mounted.current)
        setError(
          own.signal.aborted
            ? "Request stopped or timed out. Nothing was changed by this page."
            : e instanceof Error
              ? e.message
              : "Request failed.",
        );
      return null;
    } finally {
      clearTimeout(timeout);
      if (mounted.current && controller.current === own) setBusy(null);
    }
  }
  async function refresh(signal: AbortSignal) {
    const history = await api.history(expected, signal);
    if (!signal.aborted && mounted.current) {
      setReports(history.reports);
      setLoaded(true);
      setSelected((ids) =>
        ids.filter((id) => history.reports.some((r) => r.report_id === id)),
      );
    }
  }
  async function save() {
    const result = await run("save", async (signal) => {
      const saved = await api.save(expected, newKey(), signal);
      await refresh(signal);
      return saved;
    });
    if (result) setLastSave(result);
  }
  async function view(id: string) {
    const result = await run("view", (signal) =>
      api.detail(expected, id, signal),
    );
    if (result) {
      setDetail(result);
      setComparison(null);
    }
  }
  async function compare() {
    const [first, second] = selected;
    const result = await run("compare", (signal) =>
      api.compare(expected, first, second, signal),
    );
    if (result) {
      setComparison(result);
      setDetail(null);
    }
  }
  async function askMuse() {
    const reportId = selected.length === 1 ? selected[0] : null;
    const result = await run("muse", async (signal) => {
      const answer = await api.askMuse(
        expected,
        { key: newKey(), reportId, question, consented: consent },
        signal,
      );
      await refresh(signal);
      return answer;
    });
    if (result) setMuse(result);
  }
  function toggle(id: string) {
    setSelected((ids) =>
      ids.includes(id)
        ? ids.filter((x) => x !== id)
        : ids.length < 2
          ? [...ids, id]
          : ids,
    );
  }
  const locked = disabled || !!busy || !token;
  return (
    <section aria-label="Saved stability reports">
      <h4>Saved reports</h4>
      <p>
        Saved reports are immutable modeled calculations. They are not physical
        tests, and they become stale when the plan, inventory, build history or
        measurements change.
      </p>
      <button type="button" disabled={locked} onClick={save}>
        {busy === "save" ? "Saving report…" : "Save current calculation"}
      </button>{" "}
      <button
        type="button"
        disabled={locked}
        onClick={() => run("history", refresh)}
      >
        {busy === "history" ? "Loading reports…" : "Load report history"}
      </button>
      {busy && (
        <button type="button" onClick={() => controller.current?.abort()}>
          Stop
        </button>
      )}
      {error && <p role="alert">{error}</p>}
      {lastSave && (
        <p role="status">
          {lastSave.saved
            ? `${lastSave.cached ? "Already saved" : "Saved"} report ${shortId(lastSave.saved.report_id)} — ${label(lastSave.saved.report_status)}.`
            : `Nothing saved: ${label(lastSave.analysis.status)}. ${lastSave.analysis.blockers.join(" ")}`}
        </p>
      )}
      {loaded && !reports.length && <p>No saved reports yet.</p>}
      {!!reports.length && (
        <ul aria-label="Report history">
          {reports.map((r) => (
            <li key={r.report_id}>
              <label>
                <input
                  type="checkbox"
                  checked={selected.includes(r.report_id)}
                  disabled={
                    locked ||
                    (!selected.includes(r.report_id) && selected.length >= 2)
                  }
                  onChange={() => toggle(r.report_id)}
                />{" "}
                Report {shortId(r.report_id)} ·{" "}
                {new Date(r.created_at).toLocaleString()} ·{" "}
                {label(r.report_status)} ·{" "}
                {r.source === "muse_tool" ? "via MetaMuse tool" : "builder"}
              </label>{" "}
              <strong>{freshness(r)}</strong>{" "}
              <button
                type="button"
                disabled={locked}
                onClick={() => view(r.report_id)}
              >
                View report {shortId(r.report_id)}
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        disabled={locked || selected.length !== 2}
        onClick={compare}
      >
        {busy === "compare" ? "Comparing…" : "Compare two selected reports"}
      </button>
      {detail && (
        <article aria-label="Saved report detail">
          <h5>Report {shortId(detail.saved.report_id)}</h5>
          <p>
            {detail.freshness.current
              ? "Current for this plan, inventory and history."
              : `Historical report — stale because ${(
                  detail.freshness.stale_reasons ?? []
                )
                  .map((r) => staleText[r])
                  .join("; ")}. Shown read-only.`}
          </p>
          <p>
            Modeled status: {label(detail.saved.report.status)}. Coverage:{" "}
            {label(detail.saved.report.coverage)}. Required margin:{" "}
            {number(detail.saved.report.policy.required_margin_m)} m. Engine{" "}
            {detail.saved.dependencies.engine}.
          </p>
          <ul>
            {detail.saved.report.results?.map((r) => (
              <li key={`${r.case_id}/${r.check_type}`}>
                {r.case_id} — {label(r.check_type)}: {label(r.status)}.{" "}
                {r.explanation}
              </li>
            ))}
          </ul>
          {detail.saved.report.overlays?.map((o) => (
            <p key={o.case_id}>
              {o.case_id}: signed margin {number(o.signed_margin_m)} m.
            </p>
          ))}
        </article>
      )}
      {comparison && (
        <article aria-label="Report comparison">
          <h5>
            Comparison of {shortId(comparison.first.report_id)} and{" "}
            {shortId(comparison.second.report_id)}
          </h5>
          {comparison.comparable ? (
            <p>Same policy and load cases; compared check by check only.</p>
          ) : (
            <p role="status">
              Not comparable: {(comparison.mismatches ?? []).join("; ")}.
            </p>
          )}
          <ul>
            {(comparison.rows ?? []).map((row) => (
              <li key={`${row.case_id}/${row.check_type}`}>
                {row.case_id} — {label(row.check_type)}:{" "}
                {label(row.first_status ?? "missing")} vs{" "}
                {label(row.second_status ?? "missing")}
                {row.first_margin_m != null && row.second_margin_m != null
                  ? ` (margins ${number(row.first_margin_m)} m vs ${number(row.second_margin_m)} m)`
                  : ""}
                : {label(row.outcome)}.
              </li>
            ))}
          </ul>
        </article>
      )}
      <fieldset>
        <legend>Ask MetaMuse</legend>
        <p>
          {selected.length === 1
            ? "MetaMuse will explain the inputs of the selected saved report."
            : "MetaMuse will run the stability tool on the current plan and save that report."}{" "}
          It can only read server data; it cannot add measurements or approve
          anything.
        </p>
        <label>
          <input
            type="checkbox"
            checked={consent}
            disabled={locked}
            onChange={(e) => setConsent(e.target.checked)}
          />{" "}
          Share this stability report (no photos) with MetaMuse
        </label>
        <label>
          Question (optional)
          <input
            type="text"
            maxLength={500}
            value={question}
            disabled={locked}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={locked || !consent || selected.length > 1}
          onClick={askMuse}
        >
          {busy === "muse" ? "Asking MetaMuse…" : "Ask MetaMuse to explain"}
        </button>
      </fieldset>
      {muse && (
        <article aria-label="MetaMuse stability explanation">
          <h5>
            MetaMuse explanation of report {shortId(muse.report.report_id)}
          </h5>
          <p>
            Model explanation of a modeled result; physical stability is not
            verified. {freshness(muse.report)}.
          </p>
          <p>{muse.explanation.summary}</p>
          <ul>
            {muse.explanation.case_notes?.map((n, i) => (
              <li key={i}>
                {n.case_id}: {n.note}
              </li>
            ))}
          </ul>
          {!!muse.explanation.missing_inputs?.length && (
            <p>Missing inputs: {muse.explanation.missing_inputs.join("; ")}</p>
          )}
          <p>
            Provider calls: {muse.usage.model_calls}. Tokens in/out:{" "}
            {muse.usage.input_tokens ?? "unknown"} /{" "}
            {muse.usage.output_tokens ?? "unknown"}.
          </p>
        </article>
      )}
    </section>
  );
}
