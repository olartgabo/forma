import type {
  DecisionRequest,
  InventoryUpdate,
  Project,
  ProjectResult,
  RecalculateRequest,
  UnavailableRequest,
} from "../../lib/generated/api-contracts";
import type {
  DecisionChange,
  MeasurementDecision,
  MeasurementQuestion,
  Stock,
} from "../../lib/generated/contracts";
// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { receipts } from "../design-candidates/pending.ts";

export type Decision = MeasurementDecision & {
  reasons: readonly string[];
  missing_capabilities: readonly string[];
  invalidated: readonly string[];
};
export type Change = Omit<DecisionChange, "after"> & { after: Decision };

const outcomes = new Set([
  "question",
  "none_needed",
  "no_feasible_candidate",
  "unsupported",
  "physical_test_required",
  "budget_exhausted",
]);
const captures = new Set([
  "inventory",
  "requirements",
  "stability_measurements",
]);
const sha256 = /^[0-9a-f]{64}$/;
const ID = /^[A-Za-z][A-Za-z0-9_-]{0,95}$/;
const KEY = /^[a-z_]+:[A-Za-z0-9_-]{1,96}:[a-z_]+$/;

function object(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}
function text(v: unknown): v is string {
  return typeof v === "string" && v.length > 0;
}
function texts(v: unknown) {
  return Array.isArray(v) && v.every(text);
}
function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}
function invalid(what: string): never {
  // A malformed 2xx may follow a completed write: keep any retained request.
  throw new MeasurementRequestError(
    `The server returned an invalid ${what}. Retry to check the saved result.`,
    true,
  );
}

function validQuestion(v: unknown): v is MeasurementQuestion {
  if (!object(v) || !object(v.target)) return false;
  const t = v.target;
  const current = v.current;
  const threshold = v.threshold;
  return (
    text(v.question_id) &&
    sha256.test(v.question_id) &&
    text(t.key) &&
    KEY.test(t.key) &&
    text(t.label) &&
    text(t.property) &&
    (t.stock_id == null || text(t.stock_id)) &&
    Array.isArray(t.pieces ?? []) &&
    ((t.pieces ?? []) as unknown[]).every(
      (p) => object(p) && text(p.display_name) && text(p.reference),
    ) &&
    text(v.method) &&
    text(v.where) &&
    text(v.why) &&
    text(v.precision_basis) &&
    captures.has(String(v.capture)) &&
    (v.required_precision == null || finite(v.required_precision)) &&
    (current == null ||
      (object(current) &&
        (current.value == null || finite(current.value)) &&
        typeof current.confirmed === "boolean" &&
        text(current.source))) &&
    (threshold == null ||
      (object(threshold) &&
        finite(threshold.lower) &&
        (threshold.upper == null || finite(threshold.upper)) &&
        text(threshold.basis))) &&
    texts(v.affected_candidate_ids ?? []) &&
    texts(v.affected_case_ids ?? [])
  );
}

/** Every field the panel renders is checked before anything is released. */
export function validateDecision(value: unknown, projectId: string): Decision {
  if (
    !object(value) ||
    !text(value.decision_id) ||
    !sha256.test(value.decision_id) ||
    !object(value.identity) ||
    value.identity.project_id !== projectId ||
    !text(value.identity.inventory_revision_id) ||
    !outcomes.has(String(value.outcome)) ||
    (value.outcome === "question") !== object(value.question) ||
    (value.question != null && !validQuestion(value.question)) ||
    !Number.isInteger(value.pending_questions) ||
    !texts(value.reasons) ||
    !texts(value.missing_capabilities ?? []) ||
    !texts(value.invalidated ?? []) ||
    !text(value.selection_rule) ||
    value.physical_verification !== "not_attempted" ||
    (value.design != null &&
      (!object(value.design) ||
        !text(value.design.status) ||
        !texts(value.design.candidate_ids))) ||
    (value.stability != null &&
      (!object(value.stability) || !text(value.stability.analysis_status)))
  )
    invalid("measurement decision");
  return {
    ...(value as unknown as MeasurementDecision),
    reasons: value.reasons as string[],
    missing_capabilities: (value.missing_capabilities ?? []) as string[],
    invalidated: (value.invalidated ?? []) as string[],
  };
}

export function validateChange(value: unknown, projectId: string): Change {
  if (
    !object(value) ||
    !text(value.before_decision_id) ||
    !text(value.after_decision_id) ||
    !texts(value.changed_facts) ||
    typeof value.decision_changed !== "boolean" ||
    !text(value.explanation)
  )
    invalid("recalculation");
  return {
    ...(value as unknown as DecisionChange),
    after: validateDecision(value.after, projectId),
  };
}

function validProject(value: unknown, projectId: string): value is Project {
  return (
    object(value) &&
    value.id === projectId &&
    text(value.revision_id) &&
    Array.isArray(value.stocks)
  );
}

/** `retry` means the server may have finished; resend the same body and key. */
export class MeasurementRequestError extends Error {
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
    "Your materials, plan or build history changed. Find the measurement again.",
  blocked: "This change is blocked by the current project state. Reload it.",
  not_found: "This project is no longer available.",
  idempotency_conflict:
    "This retry differs from the original request. Find the measurement again.",
  validation_error: "The value could not be accepted. Check it and try again.",
};
const definite = new Set(Object.keys(messages));

export function measurementApi(token: string, projectId: string) {
  const root = `/api/projects/${encodeURIComponent(projectId)}`;
  async function send(
    path: string,
    method: string,
    body: unknown,
    signal: AbortSignal,
  ) {
    let response: Response;
    try {
      response = await fetch(`${root}${path}`, {
        method,
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
      throw new MeasurementRequestError(
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
      throw new MeasurementRequestError(
        (Object.hasOwn(messages, code) ? messages[code] : null) ??
          (response.status === 409
            ? messages.stale_version
            : "Measurement decisions are unavailable. Try again shortly."),
        !definite.has(code),
        code === "stale_version",
      );
    }
    try {
      return (await response.json()) as unknown;
    } catch {
      throw new MeasurementRequestError(
        "The response was cut off before it could be read.",
        true,
      );
    }
  }
  return {
    async decide(body: DecisionRequest, signal: AbortSignal) {
      return validateDecision(
        await send("/measurement-decisions", "POST", body, signal),
        projectId,
      );
    },
    async unavailable(body: UnavailableRequest, signal: AbortSignal) {
      return validateDecision(
        await send("/measurement-decisions/unavailable", "POST", body, signal),
        projectId,
      );
    },
    async recalculate(body: RecalculateRequest, signal: AbortSignal) {
      return validateChange(
        await send("/measurement-decisions/recalculate", "POST", body, signal),
        projectId,
      );
    },
    /** The existing inventory confirmation; nothing else stores the value. */
    async saveInventory(body: InventoryUpdate, signal: AbortSignal) {
      const result = await send("/inventory", "PUT", body, signal);
      if (!object(result) || !validProject(result.project, projectId))
        invalid("inventory confirmation");
      return result as unknown as ProjectResult;
    },
  };
}

/**
 * The exact inventory body that confirms one answer. Every other stock and
 * value is sent unchanged; requirements are only sent for a requirement.
 */
export function answerBody(
  project: Project,
  question: MeasurementQuestion,
  value: number | null,
  key: string,
): InventoryUpdate {
  const target = question.target;
  const stocks = (project.stocks ?? []).map((stock): Stock => {
    if (target.kind !== "stock" || stock.id !== target.stock_id) return stock;
    if (target.property === "usable_region") {
      const width = stock.width_mm.value;
      const height = stock.height_mm.value;
      if (width == null || height == null)
        throw new Error("Confirm the sheet's width and height first.");
      return {
        ...stock,
        usable_regions: [
          {
            id: `${stock.id}-whole`,
            geometry: { x: 0, y: 0, width, height, rotation_deg: 0 },
          },
        ],
      };
    }
    if (value == null || !Number.isFinite(value) || value <= 0)
      throw new Error("Enter the measured value.");
    return {
      ...stock,
      [target.property]: {
        value,
        unit: "mm",
        source: "user_ruler",
        confirmed: true,
      },
    };
  });
  const body: InventoryUpdate = {
    expected_revision_id: project.revision_id,
    idempotency_key: key,
    stocks,
    user_confirmed: true,
  };
  if (target.kind !== "requirement") return body;
  const requirements = project.requirements;
  if (!requirements?.constraints)
    throw new Error("Confirm the build requirements in the inventory step.");
  if (value == null || !Number.isFinite(value) || value <= 0)
    throw new Error("Enter the measured value.");
  return {
    ...body,
    requirements: {
      ...requirements,
      constraints: {
        ...requirements.constraints,
        [target.property]: {
          value,
          unit: question.unit,
          source: "user_ruler",
          confirmed: true,
        },
      },
    },
  };
}

function validInventory(v: unknown): v is InventoryUpdate {
  return (
    object(v) &&
    text(v.expected_revision_id) &&
    ID.test(v.expected_revision_id) &&
    typeof v.idempotency_key === "string" &&
    v.idempotency_key.length >= 8 &&
    v.idempotency_key.length <= 128 &&
    Array.isArray(v.stocks) &&
    v.stocks.length > 0 &&
    v.user_confirmed === true
  );
}
function validUnavailable(v: unknown): v is UnavailableRequest {
  return (
    object(v) &&
    text(v.expected_inventory_revision_id) &&
    text(v.question_id) &&
    sha256.test(v.question_id) &&
    text(v.target_key) &&
    KEY.test(v.target_key) &&
    typeof v.idempotency_key === "string" &&
    v.idempotency_key.length >= 8 &&
    v.user_confirmed === true
  );
}
function validBaseline(v: unknown): v is MeasurementDecision {
  return object(v) && text(v.decision_id) && sha256.test(v.decision_id);
}
export const answerReceipts = receipts(
  "forma-measurement-answer-pending-v1:",
  validInventory,
  "measurement",
);
export const unavailableReceipts = receipts(
  "forma-measurement-unavailable-pending-v1:",
  validUnavailable,
  "unavailable answer",
);
/** The decision a saved answer will be compared with, kept across reloads. */
export const baselineReceipts = receipts(
  "forma-measurement-baseline-v1:",
  validBaseline,
  "earlier decision",
);
