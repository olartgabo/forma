// Safe failure metadata only: never retain provider content or server messages.
import type { IntakeValidationIssue } from "./generated/api-contracts";
const validationTypes = new Set([
  "json_invalid",
  "missing",
  "extra_forbidden",
  "string_type",
  "string_too_long",
  "string_too_short",
  "int_type",
  "int_parsing",
  "float_type",
  "float_parsing",
  "bool_type",
  "literal_error",
  "enum",
  "list_type",
  "dict_type",
  "model_type",
  "greater_than",
  "greater_than_equal",
  "less_than",
  "less_than_equal",
  "finite_number",
  "value_error",
  "other",
]);
const validationFields = new Set([
  "labels",
  "measurement_source",
  "questions",
  "items",
  "identity",
  "outcome",
  "category_id",
  "other_label",
  "alternatives",
  "visible_evidence",
  "box",
  "visibility",
  "instance",
  "x1",
  "y1",
  "x2",
  "y2",
  "<field>",
  "<index>",
]);

function safeIssues(value: unknown): IntakeValidationIssue[] {
  if (!Array.isArray(value) || value.length > 16) return [];
  return value.flatMap((issue) => {
    if (
      !record(issue) ||
      Object.keys(issue).some((key) => key !== "path" && key !== "type") ||
      typeof issue.type !== "string" ||
      !validationTypes.has(issue.type) ||
      !Array.isArray(issue.path) ||
      issue.path.length > 8 ||
      !issue.path.every((part) =>
        typeof part === "string" ? validationFields.has(part) : count(part, 24),
      )
    )
      return [];
    return [
      {
        path: [...issue.path] as (string | number)[],
        type: issue.type as IntakeValidationIssue["type"],
      },
    ];
  });
}
const reasons = {
  invalid_json: [
    "Muse's answer could not be read in the required format.",
    "La respuesta de Muse no se pudo leer en el formato necesario.",
  ],
  invalid_schema: [
    "Muse's answer was missing required information or used an unexpected format.",
    "La respuesta de Muse no incluyó la información necesaria o usó un formato inesperado.",
  ],
  refusal: [
    "Muse declined to analyze this photo.",
    "Muse no aceptó analizar esta foto.",
  ],
  incomplete_output: [
    "Muse did not finish its answer.",
    "Muse no terminó su respuesta.",
  ],
  invalid_proposal: [
    "Muse's answer did not match the required format.",
    "La respuesta de Muse no tuvo el formato necesario.",
  ],
  invalid_response: [
    "Muse returned an unreadable answer.",
    "Muse devolvió una respuesta ilegible.",
  ],
  empty_observation: [
    "Muse returned no material observations.",
    "Muse no devolvió observaciones de materiales.",
  ],
  response_too_large: [
    "Muse's answer exceeded the response limit.",
    "La respuesta de Muse superó el límite permitido.",
  ],
  timeout: [
    "Muse did not answer before the time limit.",
    "Muse no respondió dentro del tiempo permitido.",
  ],
  budget_exhausted: [
    "This request reached its time limit.",
    "Esta solicitud alcanzó su límite de tiempo.",
  ],
  network_error: [
    "The server lost its connection to Muse.",
    "El servidor perdió la conexión con Muse.",
  ],
  authentication: [
    "Muse rejected the server credential.",
    "Muse rechazó la credencial del servidor.",
  ],
  access_denied: [
    "Muse denied access to this model.",
    "Muse denegó el acceso a este modelo.",
  ],
  rate_limit: [
    "Muse reached its request limit.",
    "Muse alcanzó su límite de solicitudes.",
  ],
  provider_http_error: [
    "Muse could not complete this request.",
    "Muse no pudo completar esta solicitud.",
  ],
  round_limit: [
    "Muse reached this request's processing limit.",
    "Muse alcanzó el límite de procesamiento de esta solicitud.",
  ],
  provider_error: [
    "Muse could not complete this request.",
    "Muse no pudo completar esta solicitud.",
  ],
} as const;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function count(value: unknown, max: number): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0 &&
    value <= max
  );
}

export function parseIntakeFailureDiagnostics(value: unknown) {
  if (
    !record(value) ||
    !Object.keys(value).every((key) =>
      [
        "reason",
        "model",
        "elapsed_ms",
        "usage",
        "validation_issues",
        "finish_reason",
      ].includes(key),
    ) ||
    typeof value.reason !== "string" ||
    !Object.hasOwn(reasons, value.reason) ||
    typeof value.model !== "string" ||
    !/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$/.test(value.model) ||
    !count(value.elapsed_ms, 86_400_000) ||
    !record(value.usage) ||
    (value.finish_reason != null &&
      (typeof value.finish_reason !== "string" ||
        !/^[a-z_]{1,32}$/.test(value.finish_reason)))
  )
    return null;
  const usage = value.usage;
  if (
    !Object.keys(usage).every((key) =>
      [
        "model_calls",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
      ].includes(key),
    ) ||
    !count(usage.model_calls, 16) ||
    (usage.reasoning_tokens != null &&
      !count(usage.reasoning_tokens, 16_000_000_000)) ||
    (usage.input_tokens != null &&
      !count(usage.input_tokens, 16_000_000_000)) ||
    (usage.output_tokens != null && !count(usage.output_tokens, 16_000_000_000))
  )
    return null;
  return {
    reason: value.reason as keyof typeof reasons,
    validationIssues: safeIssues(value.validation_issues),
    model: value.model,
    elapsedMs: value.elapsed_ms,
    // Why the provider stopped generating, e.g. "length"; null if unreported.
    finishReason:
      value.finish_reason == null ? null : (value.finish_reason as string),
    usage: {
      model_calls: usage.model_calls,
      input_tokens:
        usage.input_tokens == null ? null : (usage.input_tokens as number),
      output_tokens:
        usage.output_tokens == null ? null : (usage.output_tokens as number),
      ...(usage.reasoning_tokens == null
        ? {}
        : { reasoning_tokens: usage.reasoning_tokens as number }),
    },
  };
}

export type IntakeFailureDiagnostics = NonNullable<
  ReturnType<typeof parseIntakeFailureDiagnostics>
>;

export function intakeFailureReason(
  diagnostics: IntakeFailureDiagnostics,
  locale: unknown = "en",
) {
  const base = reasons[diagnostics.reason][locale === "es" ? 1 : 0];
  const reason =
    diagnostics.finishReason === "length"
      ? `${base} ${locale === "es" ? "Se quedó sin espacio para la respuesta." : "It ran out of room for the answer."}`
      : base;
  if (!diagnostics.validationIssues.length) return reason;
  const checks = diagnostics.validationIssues
    .map(
      (issue) =>
        `${issue.path.join(".") || (locale === "es" ? "respuesta" : "answer")}: ${issue.type}`,
    )
    .join("; ");
  return `${reason} ${locale === "es" ? "Comprobaciones de la respuesta" : "Answer checks"}: ${checks}.`;
}

export function intakeFailureSummary(
  diagnostics: IntakeFailureDiagnostics | null,
) {
  return diagnostics ? { ...diagnostics, status: "failed" } : null;
}
