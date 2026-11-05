// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { modelKeyHeaders } from "../../lib/developer-settings.ts";
import type {
  IntakeResearchRequest,
  IntakeResearchResult,
} from "../../lib/generated/api-contracts";
// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { SynthesisRequestError, validateSearch, type Search, type SearchContext } from "./client.ts";
// prettier-ignore
// @ts-expect-error -- Node tests import TypeScript directly.
import { receipts } from "./pending.ts";

export type ResearchResult = Omit<IntakeResearchResult, "search"> & {
  findings: NonNullable<IntakeResearchResult["findings"]>;
  recommendation_source_index: number | null;
  search: Search | null;
};

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown, limit: number): value is string {
  return (
    typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= limit
  );
}

function safeLink(value: unknown): boolean {
  if (!text(value, 2048) || !value.startsWith("https://")) return false;
  try {
    const url = new URL(value);
    return Boolean(url.hostname) && !url.username && !url.password;
  } catch {
    return false;
  }
}

const coverage = new Set([
  "complete",
  "partial",
  "no_sources",
  "unavailable",
  "not_run",
]);
const decisions = new Set([
  "eligible",
  "needs_input",
  "blocked",
  "undetermined",
  "unsupported",
]);

export function validateResearch(
  value: unknown,
  context: SearchContext,
): ResearchResult {
  const invalid = () =>
    new SynthesisRequestError(
      "The research response could not be verified.",
      true,
    );
  if (
    !object(value) ||
    value.project_id !== context.projectId ||
    value.inventory_revision_id !== context.inventoryRevisionId ||
    typeof value.coverage !== "string" ||
    !coverage.has(value.coverage) ||
    typeof value.decision !== "string" ||
    !decisions.has(value.decision) ||
    !text(value.reason, 2000) ||
    !(value.question == null || text(value.question, 2000)) ||
    !(value.replayed === undefined || typeof value.replayed === "boolean") ||
    !Array.isArray(value.findings) ||
    value.findings.length > 4 ||
    !value.findings.every(
      (finding: unknown) =>
        object(finding) &&
        text(finding.claim, 2000) &&
        text(finding.title, 300) &&
        safeLink(finding.url),
    )
  )
    throw invalid();

  const search =
    value.search == null ? null : validateSearch(value.search, context);
  const recommendation = value.recommended_candidate_id ?? null;
  const sourceIndex = value.recommendation_source_index ?? null;
  if (
    (value.decision === "eligible") !==
      (search?.status === "candidates_found") ||
    (recommendation === null) !== (sourceIndex === null) ||
    (sourceIndex !== null &&
      (typeof sourceIndex !== "number" ||
        !Number.isInteger(sourceIndex) ||
        sourceIndex < 0 ||
        sourceIndex >= value.findings.length)) ||
    (recommendation !== null &&
      (value.decision !== "eligible" ||
        !search?.candidates.some(
          (candidate) => candidate.candidate_id === recommendation,
        )))
  )
    throw invalid();
  return {
    ...(value as unknown as ResearchResult),
    recommendation_source_index: sourceIndex,
    search,
  };
}

function validRequest(value: unknown): value is IntakeResearchRequest {
  return (
    object(value) &&
    Object.keys(value).length === 5 &&
    typeof value.expected_inventory_revision_id === "string" &&
    /^[A-Za-z][A-Za-z0-9_-]{0,95}$/.test(
      value.expected_inventory_revision_id,
    ) &&
    typeof value.idempotency_key === "string" &&
    value.idempotency_key.length >= 8 &&
    value.idempotency_key.length <= 128 &&
    value.consented === true &&
    (value.use_case === "phone_stand" || value.use_case === "reading_stand") &&
    typeof value.needs_plug_clearance === "boolean"
  );
}

export const researchReceipts = receipts(
  "forma-intake-research-pending-v1:",
  validRequest,
  "research request",
);

export function publicResearchBrief(
  useCase: IntakeResearchRequest["use_case"],
  needsPlugClearance: boolean,
) {
  const stand = useCase === "phone_stand" ? "phone" : "reading";
  return (
    "Research a low-risk cardboard tabletop " +
    stand +
    " stand made with tape and no glue." +
    (needsPlugClearance ? " Plug clearance is essential." : "")
  );
}

const definiteRefusals = new Set([
  "stale_version",
  "not_found",
  "idempotency_conflict",
  "consent_required",
  "validation_error",
  "blocked",
  "feature_disabled",
  "provider_not_configured",
]);

export function researchApi(token: string, context: SearchContext) {
  const path = `/api/projects/${encodeURIComponent(context.projectId)}/synthesis/research`;
  const headers = { Authorization: `Bearer ${token}` };
  return {
    async enabled(signal: AbortSignal) {
      const response = await fetch(path, {
        signal,
        headers,
        cache: "no-store",
        credentials: "omit",
      });
      if (!response.ok) return false;
      const value: unknown = await response.json();
      return object(value) && value.enabled === true;
    },
    async investigate(body: IntakeResearchRequest, signal: AbortSignal) {
      let response: Response;
      try {
        response = await fetch(path, {
          method: "POST",
          body: JSON.stringify(body),
          headers: {
            ...headers,
            ...modelKeyHeaders(),
            "Content-Type": "application/json",
          },
          signal: AbortSignal.any([signal, AbortSignal.timeout(35_000)]),
          cache: "no-store",
          credentials: "omit",
        });
      } catch {
        throw new SynthesisRequestError("network_error", true);
      }
      if (!response.ok) {
        const value: unknown = await response.json().catch(() => null);
        const code =
          object(value) && typeof value.code === "string"
            ? value.code
            : "provider_error";
        throw new SynthesisRequestError(
          code,
          !definiteRefusals.has(code),
          code === "stale_version",
        );
      }
      try {
        return validateResearch(await response.json(), context);
      } catch {
        throw new SynthesisRequestError("invalid_response", true);
      }
    },
  };
}
