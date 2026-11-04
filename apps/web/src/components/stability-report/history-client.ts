import type {
  StabilityMuseRequest,
  StabilityMuseResult,
  StabilityReportComparison,
  StabilityReportDetail,
  StabilityReportHistory,
  StabilityReportSaveResponse,
  StabilityReportSummary,
} from "../../lib/generated/api-contracts";
import type { AnalysisResponse, ExpectedContext } from "./client";
// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { validateAnalysis, validateContext } from "./client.ts";

export type SaveResult = StabilityReportSaveResponse & {
  analysis: AnalysisResponse;
};
const reportId = /^stability-report-[0-9a-f]{64}$/;
const staleReasons = new Set([
  "plan_changed",
  "inventory_changed",
  "history_changed",
  "evidence_invalidated",
]);
const outcomes = new Set([
  "not_comparable",
  "unknown",
  "first_larger_margin",
  "second_larger_margin",
  "equal_within_tolerance",
  "same_status",
  "different_status",
]);
const decisive = new Set(["modeled_pass", "modeled_fail"]);
function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function invalid(what: string): never {
  throw new Error(
    `The server returned an invalid ${what}. Reload and try again.`,
  );
}

export function validateSummary(
  value: unknown,
  expected: ExpectedContext,
): StabilityReportSummary {
  const f = object(value) ? value.freshness : null;
  if (
    !object(value) ||
    typeof value.report_id !== "string" ||
    !reportId.test(value.report_id) ||
    typeof value.plan_version_id !== "string" ||
    typeof value.created_at !== "string" ||
    Number.isNaN(Date.parse(value.created_at)) ||
    !["builder", "muse_tool"].includes(String(value.source)) ||
    !Array.isArray(value.case_ids) ||
    !object(f) ||
    typeof f.current !== "boolean" ||
    !Array.isArray(f.stale_reasons) ||
    f.stale_reasons.some((r) => !staleReasons.has(String(r))) ||
    f.current !== (f.stale_reasons.length === 0) ||
    // A report for another plan or inventory can never be current.
    (f.current &&
      (value.plan_version_id !== expected.planVersionId ||
        value.inventory_revision_id !== expected.inventoryRevisionId))
  )
    invalid("saved report summary");
  return value as StabilityReportSummary;
}

export function validateSave(
  value: unknown,
  expected: ExpectedContext,
  cursor: string | null,
): SaveResult {
  if (!object(value) || typeof value.cached !== "boolean")
    invalid("save result");
  // A replay returns the original calculation, which may predate the current
  // history; its freshness must then say so.
  const replayed = value.replayed === true;
  const original =
    replayed && object(value.analysis)
      ? ((value.analysis.last_event_id ?? null) as string | null)
      : cursor;
  const analysis = validateAnalysis(value.analysis, expected, original);
  if (value.saved == null) {
    if (analysis.report) invalid("save result");
    return value as SaveResult;
  }
  const saved = validateSummary(value.saved, expected);
  if (
    !analysis.report ||
    saved.report_id !== `stability-report-${analysis.report.cache_hash}` ||
    saved.history_cursor !== original ||
    (!replayed && !saved.freshness.current) ||
    (original !== cursor && saved.freshness.current)
  )
    invalid("save result");
  return value as SaveResult;
}

export function validateHistory(
  value: unknown,
  expected: ExpectedContext,
): StabilityReportHistory {
  if (
    !object(value) ||
    value.project_id !== expected.projectId ||
    !Array.isArray(value.reports) ||
    value.reports.length > 50
  )
    invalid("report history");
  const seen = new Set<string>();
  for (const summary of value.reports) {
    const s = validateSummary(summary, expected);
    if (seen.has(s.report_id)) invalid("report history");
    seen.add(s.report_id);
  }
  return value as StabilityReportHistory;
}

export function validateDetail(
  value: unknown,
  expected: ExpectedContext,
  id: string,
): StabilityReportDetail {
  const saved = object(value) ? value.saved : null;
  if (
    !object(value) ||
    !object(saved) ||
    saved.report_id !== id ||
    saved.project_id !== expected.projectId ||
    !object(saved.report) ||
    `stability-report-${String(saved.report.cache_hash)}` !== id ||
    !object(value.freshness) ||
    typeof value.freshness.current !== "boolean"
  )
    invalid("saved report");
  return value as StabilityReportDetail;
}

export function validateComparison(
  value: unknown,
  expected: ExpectedContext,
  first: string,
  second: string,
): StabilityReportComparison {
  if (
    !object(value) ||
    value.project_id !== expected.projectId ||
    typeof value.comparable !== "boolean" ||
    !Array.isArray(value.rows) ||
    !Array.isArray(value.mismatches) ||
    validateSummary(value.first, expected).report_id !== first ||
    validateSummary(value.second, expected).report_id !== second ||
    value.comparable === value.mismatches.length > 0
  )
    invalid("comparison");
  for (const row of value.rows) {
    if (!object(row) || !outcomes.has(String(row.outcome)))
      invalid("comparison");
    // Never accept a decisive comparison when either side is unresolved.
    if (!value.comparable && row.outcome !== "not_comparable")
      invalid("comparison");
    if (
      value.comparable &&
      row.outcome !== "unknown" &&
      (!decisive.has(String(row.first_status)) ||
        !decisive.has(String(row.second_status)))
    )
      invalid("comparison");
  }
  return value as StabilityReportComparison;
}

export function validateMuse(
  value: unknown,
  expected: ExpectedContext,
): StabilityMuseResult {
  const explanation = object(value) ? value.explanation : null;
  if (
    !object(value) ||
    value.project_id !== expected.projectId ||
    value.physical_status !== "not_verified" ||
    !object(explanation) ||
    typeof explanation.summary !== "string"
  )
    invalid("MetaMuse explanation");
  const report = validateSummary(value.report, expected);
  if (explanation.report_id !== report.report_id)
    invalid("MetaMuse explanation");
  return value as StabilityMuseResult;
}

/** A failed request; `ambiguous` means the server may have completed it. */
export class StabilityRequestError extends Error {
  readonly ambiguous: boolean;
  constructor(message: string, ambiguous: boolean) {
    super(message);
    this.ambiguous = ambiguous;
  }
}
// Codes whose request may still have run (or is running) on the server.
const ambiguousCodes = new Set([
  "generation_in_progress",
  "generation_outcome_unknown",
]);
const messages: Record<string, string> = {
  consent_required:
    "Confirm sharing this stability report with MetaMuse first.",
  blocked: "No stability report is available yet. Record measurements first.",
  stale_version: "The project changed. Reload before trying again.",
  generation_in_progress: "A MetaMuse explanation is already running.",
  generation_outcome_unknown:
    "The previous MetaMuse outcome is unknown. Nothing new was sent.",
  not_found: "That saved report is no longer available.",
};

export function stabilityApi(token: string, projectId: string) {
  const root = `/api/projects/${encodeURIComponent(projectId)}/stability`;
  async function json(
    url: string,
    signal: AbortSignal,
    init: RequestInit = {},
  ) {
    let response: Response;
    try {
      response = await fetch(url, {
        ...init,
        signal,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        cache: "no-store",
      });
    } catch {
      // No response: a sent request may still have completed on the server.
      throw new StabilityRequestError(
        signal.aborted
          ? "Request stopped or timed out."
          : "The connection failed before a response arrived.",
        true,
      );
    }
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as unknown;
      const code = object(body) ? String(body.code) : "";
      throw new StabilityRequestError(
        messages[code] ??
          (response.status === 409
            ? "The project changed. Reload before trying again."
            : "Saved stability reports are unavailable. Try again when ready."),
        ambiguousCodes.has(code) || !code,
      );
    }
    try {
      return (await response.json()) as unknown;
    } catch {
      throw new StabilityRequestError(
        "The response was cut off before it could be read.",
        true,
      );
    }
  }
  async function context(expected: ExpectedContext, signal: AbortSignal) {
    return validateContext(
      await json(
        `${root}/context?plan_version_id=${encodeURIComponent(expected.planVersionId)}`,
        signal,
      ),
      expected,
    );
  }
  function identity(expected: ExpectedContext, cursor: string | null) {
    return {
      plan_version_id: expected.planVersionId,
      expected_inventory_revision_id: expected.inventoryRevisionId,
      expected_last_event_id: cursor,
    };
  }
  return {
    async save(expected: ExpectedContext, key: string, signal: AbortSignal) {
      const current = await context(expected, signal);
      return validateSave(
        await json(`${root}/reports`, signal, {
          method: "POST",
          body: JSON.stringify({
            ...identity(expected, current.last_event_id),
            idempotency_key: key,
          }),
        }),
        expected,
        current.last_event_id,
      );
    },
    async history(expected: ExpectedContext, signal: AbortSignal) {
      return validateHistory(await json(`${root}/reports`, signal), expected);
    },
    async detail(expected: ExpectedContext, id: string, signal: AbortSignal) {
      return validateDetail(
        await json(`${root}/reports/${encodeURIComponent(id)}`, signal),
        expected,
        id,
      );
    },
    async compare(
      expected: ExpectedContext,
      first: string,
      second: string,
      signal: AbortSignal,
    ) {
      const query = new URLSearchParams({ first, second });
      return validateComparison(
        await json(`${root}/report-comparison?${query}`, signal),
        expected,
        first,
        second,
      );
    },
    /** The exact request body; retain it before sending. */
    async prepareMuse(
      expected: ExpectedContext,
      request: {
        key: string;
        reportId: string | null;
        question: string;
        consented: boolean;
      },
      signal: AbortSignal,
    ): Promise<StabilityMuseRequest> {
      const current = await context(expected, signal);
      return {
        ...identity(expected, current.last_event_id),
        idempotency_key: request.key,
        mode: request.reportId ? "explain_report" : "analyze_current",
        report_id: request.reportId,
        question: request.question.trim() || null,
        provider_context_consented: request.consented,
      };
    },
    /** Send a prepared body unchanged; a retry replays a completed request. */
    async sendMuse(
      expected: ExpectedContext,
      body: StabilityMuseRequest,
      signal: AbortSignal,
    ) {
      return validateMuse(
        await json(`${root}/muse-explanations`, signal, {
          method: "POST",
          body: JSON.stringify(body),
        }),
        expected,
      );
    },
  };
}
