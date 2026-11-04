import type {
  PlanCompileResult,
  SynthesisMuseRequest,
  SynthesisMuseResult,
  SynthesisProbeRequest,
  SynthesisSearchRequest,
  SynthesisSelectRequest,
} from "../../lib/generated/api-contracts";
// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { receipts } from "./pending.ts";
import type {
  CandidateReport,
  ProbeResult,
  StandDesign,
  SynthesisResult,
} from "../../lib/generated/contracts";

export type SearchParameter = ProbeResult["parameter"];
// Validated responses: arrays with server defaults are always present.
type Present<T, K extends keyof T> = T & Required<Pick<T, K>>;
export type Candidate = Present<
  CandidateReport,
  "pieces" | "checks" | "construction" | "unresolved" | "blockers"
>;
export type Search = Omit<
  Present<SynthesisResult, "domains" | "blockers" | "rejections">,
  "candidates"
> & { candidates: readonly Candidate[] };
export type MuseResult = Omit<SynthesisMuseResult, "engine_probe"> & {
  engine_probe?: Probe | null;
};
export type Probe = Omit<
  Present<ProbeResult, "changed_piece_ids" | "blockers">,
  "report"
> & { report?: Candidate | null };

export type SearchContext = {
  projectId: string;
  inventoryRevisionId: string;
  activeVersionId: string | null;
  lastEventId: string | null;
};

const searchStatuses = new Set([
  "candidates_found",
  "infeasible",
  "search_exhausted",
  "needs_input",
  "active_build",
]);
const checkStatuses = new Set([
  "modeled_pass",
  "modeled_failure",
  "missing_input",
  "unsupported",
  "evidence_incompatible",
  "unverified",
]);
const probeStatuses = new Set([
  "evaluated",
  "outside_domain",
  "requires_repair",
  "unsupported",
]);
export const PARAMETERS: readonly SearchParameter[] = [
  "part_width_mm",
  "support_length_mm",
  "footprint_depth_mm",
];
const sha256 = /^[0-9a-f]{64}$/;

function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
function invalid(what: string): never {
  // A malformed 2xx may follow a completed write: keep any retained key.
  throw new SynthesisRequestError(
    `The server returned an invalid ${what}. Retry to check the saved result.`,
    true,
  );
}

function matchesContext(identity: unknown, expected: SearchContext) {
  return (
    object(identity) &&
    identity.project_id === expected.projectId &&
    identity.inventory_revision_id === expected.inventoryRevisionId &&
    identity.active_version_id === expected.activeVersionId &&
    identity.last_event_id === expected.lastEventId
  );
}

function validDesign(value: unknown): value is StandDesign {
  return (
    object(value) &&
    typeof value.sheet_stock_id === "string" &&
    typeof value.tape_stock_id === "string" &&
    PARAMETERS.every(
      (name) => finite(value[name]) && Number(value[name]) > 0,
    ) &&
    finite(value.lip_mm) &&
    finite(value.support_angle_deg)
  );
}

export function validateCandidate(value: unknown): CandidateReport {
  if (
    !object(value) ||
    typeof value.candidate_id !== "string" ||
    !validDesign(value.design) ||
    !["acceptable", "rejected"].includes(String(value.status)) ||
    !Array.isArray(value.checks) ||
    !value.checks.every(
      (c) =>
        object(c) &&
        typeof c.check_id === "string" &&
        checkStatuses.has(String(c.status)) &&
        typeof c.detail === "string",
    ) ||
    !Array.isArray(value.pieces) ||
    !Array.isArray(value.construction) ||
    !Array.isArray(value.unresolved) ||
    !Array.isArray(value.blockers)
  )
    invalid("design candidate");
  const failed = value.checks.some(
    (c) => object(c) && c.status === "modeled_failure",
  );
  // A modeled failure can never be presented as an acceptable proposal.
  if (value.status === "acceptable" && (failed || value.blockers.length))
    invalid("design candidate");
  return value as unknown as Candidate;
}

export function validateSearch(
  value: unknown,
  expected: SearchContext,
): Search {
  if (
    !object(value) ||
    typeof value.search_id !== "string" ||
    !sha256.test(value.search_id) ||
    !matchesContext(value.identity, expected) ||
    !searchStatuses.has(String(value.status)) ||
    !Number.isInteger(value.nodes_evaluated) ||
    !Number.isInteger(value.nodes_total) ||
    !Array.isArray(value.candidates) ||
    value.candidates.length > 2 ||
    !Array.isArray(value.domains) ||
    !Array.isArray(value.blockers) ||
    !Array.isArray(value.rejections) ||
    value.physical_verification !== "not_attempted"
  )
    invalid("design search");
  const candidates = value.candidates.map(validateCandidate);
  if (
    candidates.some((c) => c.status !== "acceptable") ||
    (value.status === "candidates_found") !== candidates.length > 0 ||
    (value.status === "search_exhausted" && !value.exhausted)
  )
    invalid("design search");
  return value as unknown as Search;
}

export function validateProbe(
  value: unknown,
  expected: SearchContext,
  searchId: string,
): Probe {
  if (
    !object(value) ||
    value.search_id !== searchId ||
    !matchesContext(value.identity, expected) ||
    !probeStatuses.has(String(value.status)) ||
    !PARAMETERS.includes(value.parameter as SearchParameter) ||
    !Array.isArray(value.changed_piece_ids) ||
    !Array.isArray(value.blockers) ||
    value.physical_verification !== "not_attempted"
  )
    invalid("design probe");
  if (value.status === "evaluated") validateCandidate(value.report);
  if (value.status === "requires_repair" && !object(value.repair))
    invalid("design probe");
  return value as unknown as Probe;
}

export function validateSelection(value: unknown): PlanCompileResult {
  if (
    !object(value) ||
    !["accepted", "blocked", "needs_measurement", "unsupported"].includes(
      String(value.status),
    ) ||
    (value.status === "accepted" &&
      (!object(value.version) || typeof value.version.version_id !== "string"))
  )
    invalid("design selection");
  return value as unknown as PlanCompileResult;
}

/** `retry` means the server may have finished; reuse the same key. */
export class SynthesisRequestError extends Error {
  readonly retry: boolean;
  readonly stale: boolean;
  constructor(message: string, retry: boolean, stale = false) {
    super(message);
    this.retry = retry;
    this.stale = stale;
  }
}

const messages: Record<string, string> = {
  stale_version:
    "Your materials, plan or build history changed. Search again before continuing.",
  blocked:
    "This request is blocked by the current project state. Reload to see the saved plans.",
  not_found: "This project is no longer available.",
  idempotency_conflict:
    "This retry differs from the original request. Search again and try once more.",
  consent_required: "Confirm sharing the proposed designs with MetaMuse first.",
  provider_not_configured: "MetaMuse is not configured on this server.",
  invalid_response:
    "MetaMuse returned an answer the engine could not verify; nothing was saved.",
  generation_in_progress: "A MetaMuse comparison is already running.",
  generation_outcome_unknown:
    "The previous MetaMuse outcome is unknown. Nothing new was sent.",
};
// Only these refusals are definite: the server finished nothing for the key,
// so a retained request may be released. Anything else keeps it for a retry.
const definite = new Set([
  "stale_version",
  "blocked",
  "not_found",
  "idempotency_conflict",
  "consent_required",
  "provider_not_configured",
  "invalid_response",
]);

export function synthesisApi(token: string, projectId: string) {
  const root = `/api/projects/${encodeURIComponent(projectId)}/synthesis`;
  async function post(path: string, body: unknown, signal: AbortSignal) {
    let response: Response;
    try {
      response = await fetch(`${root}/${path}`, {
        method: "POST",
        body: JSON.stringify(body),
        signal,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        cache: "no-store",
        credentials: "omit",
      });
    } catch {
      throw new SynthesisRequestError(
        signal.aborted
          ? "Request stopped or timed out."
          : "The connection failed before a response arrived.",
        true,
      );
    }
    if (!response.ok) {
      const parsed = (await response.json().catch(() => null)) as unknown;
      const code =
        object(parsed) && typeof parsed.code === "string" ? parsed.code : "";
      throw new SynthesisRequestError(
        (Object.hasOwn(messages, code) ? messages[code] : null) ??
          (response.status === 409
            ? messages.stale_version
            : "Design search is unavailable. Try again shortly."),
        !definite.has(code),
        code === "stale_version",
      );
    }
    try {
      return (await response.json()) as unknown;
    } catch {
      throw new SynthesisRequestError(
        "The response was cut off before it could be read.",
        true,
      );
    }
  }
  function identity(context: SearchContext) {
    return {
      expected_inventory_revision_id: context.inventoryRevisionId,
      expected_active_version_id: context.activeVersionId,
      expected_last_event_id: context.lastEventId,
    };
  }
  return {
    async search(context: SearchContext, signal: AbortSignal) {
      const body: SynthesisSearchRequest = identity(context);
      return validateSearch(await post("search", body, signal), context);
    },
    async probe(
      context: SearchContext,
      searchId: string,
      design: StandDesign | null,
      parameter: SearchParameter,
      value: number,
      signal: AbortSignal,
    ) {
      const body: SynthesisProbeRequest = {
        ...identity(context),
        search_id: searchId,
        design,
        parameter,
        value_mm: value,
      };
      return validateProbe(
        await post("probe", body, signal),
        context,
        searchId,
      );
    },
    /** Sends a retained body unchanged, so a retry reuses its key. */
    async select(body: SynthesisSelectRequest, signal: AbortSignal) {
      return validateSelection(await post("select", body, signal));
    },
    async explain(body: SynthesisMuseRequest, signal: AbortSignal) {
      return validateMuse(
        await post("muse-explanations", body, signal),
        projectId,
        body,
      );
    },
  };
}

export function selectionBody(
  context: SearchContext,
  searchId: string,
  design: StandDesign,
  key: string,
): SynthesisSelectRequest {
  return {
    expected_inventory_revision_id: context.inventoryRevisionId,
    expected_active_version_id: context.activeVersionId,
    expected_last_event_id: context.lastEventId,
    search_id: searchId,
    design,
    idempotency_key: key,
    user_selected: true,
  };
}

export function museBody(
  context: SearchContext,
  searchId: string,
  key: string,
  question: string | null,
): SynthesisMuseRequest {
  return {
    expected_inventory_revision_id: context.inventoryRevisionId,
    expected_active_version_id: context.activeVersionId,
    expected_last_event_id: context.lastEventId,
    search_id: searchId,
    idempotency_key: key,
    question,
    provider_context_consented: true,
  };
}

const IDENTITY = [
  "expected_inventory_revision_id",
  "expected_active_version_id",
  "expected_last_event_id",
  "search_id",
  "idempotency_key",
];
function id(value: unknown) {
  return (
    typeof value === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,95}$/.test(value)
  );
}
function validIdentity(v: Record<string, unknown>, fields: string[]) {
  return (
    Object.keys(v).length === fields.length &&
    fields.every((k) => Object.hasOwn(v, k)) &&
    id(v.expected_inventory_revision_id) &&
    (v.expected_active_version_id === null ||
      id(v.expected_active_version_id)) &&
    (v.expected_last_event_id === null || id(v.expected_last_event_id)) &&
    typeof v.search_id === "string" &&
    sha256.test(v.search_id) &&
    typeof v.idempotency_key === "string" &&
    v.idempotency_key.length >= 8 &&
    v.idempotency_key.length <= 128
  );
}
export function validSelectRequest(v: unknown): v is SynthesisSelectRequest {
  return (
    object(v) &&
    validIdentity(v, [...IDENTITY, "design", "user_selected"]) &&
    validDesign(v.design) &&
    v.user_selected === true
  );
}
export function validMuseRequest(v: unknown): v is SynthesisMuseRequest {
  return (
    object(v) &&
    validIdentity(v, [...IDENTITY, "question", "provider_context_consented"]) &&
    (v.question === null ||
      (typeof v.question === "string" &&
        v.question.length >= 1 &&
        v.question.length <= 500)) &&
    v.provider_context_consented === true
  );
}
export const selectionReceipts = receipts(
  "forma-design-select-pending-v1:",
  validSelectRequest,
  "design choice",
);
export const museReceipts = receipts(
  "forma-design-muse-pending-v1:",
  validMuseRequest,
  "MetaMuse comparison",
);

export function validateMuse(
  value: unknown,
  projectId: string,
  body: SynthesisMuseRequest,
): MuseResult {
  const explanation = object(value) ? value.explanation : null;
  if (
    !object(value) ||
    value.project_id !== projectId ||
    value.search_id !== body.search_id ||
    value.tool_name !== "compare_stand_designs" ||
    value.physical_status !== "not_verified" ||
    !object(value.usage) ||
    !object(explanation) ||
    explanation.search_id !== body.search_id ||
    typeof explanation.summary !== "string" ||
    !Array.isArray(explanation.candidate_notes ?? []) ||
    !Array.isArray(explanation.unresolved ?? []) ||
    !Array.isArray(explanation.questions ?? [])
  )
    invalid("MetaMuse comparison");
  const probe = value.engine_probe;
  if (
    probe != null &&
    (!object(probe) ||
      !probeStatuses.has(String(probe.status)) ||
      (probe.status === "evaluated" && !object(probe.report)))
  )
    invalid("MetaMuse comparison");
  if (probe != null && probe.status === "evaluated")
    validateCandidate(probe.report);
  return value as unknown as MuseResult;
}

/** Finite domain values, recomputed exactly as the server enumerates them. */
export function domainValues(
  result: Search,
  sheetId: string,
  parameter: SearchParameter,
): number[] {
  const domain = result.domains.find(
    (d) => d.sheet_stock_id === sheetId && d.parameter === parameter,
  );
  if (!domain) return [];
  return Array.from(
    { length: domain.count },
    (_, k) => Math.round((domain.lower_mm + k * domain.step_mm) * 1e6) / 1e6,
  );
}
