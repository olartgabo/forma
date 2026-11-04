import { useEffect, useRef, useState } from "react";
import type { IntakeResearchRequest } from "../../lib/generated/api-contracts";
import { useMuseLanguage } from "../muse-language-provider";
import {
  type Search,
  type SearchContext,
  SynthesisRequestError,
} from "./client";
import {
  type ResearchResult,
  publicResearchBrief,
  researchApi,
  researchReceipts,
} from "./research-client";

export type ResearchAdvice = {
  candidateId: string;
  reason: string;
  source: ResearchResult["findings"][number];
};

const copy = {
  en: {
    title: "Find ideas for this build",
    intro:
      "MetaMuse looks for similar projects. FORMA checks what fits your saved stock.",
    scope:
      "This checks the stand and requirements shown below using your saved project facts. Your written goal may include other requirements.",
    useCase: "What are you making?",
    phone: "Phone stand",
    reading: "Reading stand",
    clearance: "Plug clearance is essential",
    clearanceGate: "Clear this requirement to compare stock-only designs.",
    brief: "Public brief sent to MetaMuse",
    transfer:
      "MetaMuse may also see how checked options compare in sheet and tape use or base depth. Photos and exact measurements stay in FORMA.",
    consent: "Share this brief and option comparisons with MetaMuse",
    start: "Research and check ideas",
    retry: "Retry the same research request",
    review: "Review checked designs",
    stop: "Stop waiting",
    sources: "Web references",
    working: "Researching ideas and checking saved stock…",
    pending:
      "The earlier research request is unresolved. A retry uses the same request.",
    old: "The saved research request belongs to an earlier inventory.",
    discard: "Clear the saved research request",
    storedError: "The browser could not read or save this research request.",
    failed: "Research is unavailable. You can still search your saved stock.",
    stale: "Your inventory changed. Reload it before researching again.",
    unknown: "The provider outcome is unknown. FORMA sent no new request.",
    recommendation: "Suggested by research",
    recommendationSource: "Source used for the recommendation",
    coverage: {
      complete: "Research complete",
      partial: "Research partially complete",
      no_sources: "No usable citations found",
      unavailable: "Research unavailable",
      not_run: "Research skipped",
    },
    decision: {
      eligible: "Checked designs to review",
      needs_input: "More information needed",
      blocked: "The stock check found a blocker",
      undetermined: "The check could not decide",
      unsupported: "This requirement is outside the supported checks",
    },
  },
  es: {
    title: "Buscar ideas para este proyecto",
    intro:
      "MetaMuse busca proyectos similares. FORMA comprueba qué opciones encajan con tus materiales guardados.",
    scope:
      "Esta búsqueda comprueba el soporte y los requisitos indicados abajo con los datos guardados del proyecto. Tu objetivo escrito puede incluir otros requisitos.",
    useCase: "¿Qué quieres construir?",
    phone: "Soporte para teléfono",
    reading: "Atril de lectura",
    clearance: "El espacio para el conector es imprescindible",
    clearanceGate:
      "Quita este requisito para comparar opciones basadas solo en tus materiales.",
    brief: "Descripción pública que recibirá MetaMuse",
    transfer:
      "MetaMuse también puede recibir comparaciones entre las opciones comprobadas sobre el uso de lámina y cinta o la profundidad de la base. Las fotos y las medidas exactas se quedan en FORMA.",
    consent: "Compartir esta descripción y las comparaciones con MetaMuse",
    start: "Buscar y comprobar ideas",
    retry: "Reintentar la misma solicitud",
    review: "Revisar diseños comprobados",
    stop: "Dejar de esperar",
    sources: "Referencias web",
    working: "Buscando ideas y comprobando los materiales guardados…",
    pending:
      "La solicitud anterior sigue pendiente. Se usará la misma solicitud al reintentar.",
    old: "La solicitud guardada corresponde a un inventario anterior.",
    discard: "Borrar la solicitud de investigación guardada",
    storedError: "El navegador no pudo leer o guardar esta solicitud.",
    failed:
      "La búsqueda en internet no está disponible. Puedes buscar diseños con tus materiales.",
    stale: "Tu inventario cambió. Vuelve a cargarlo antes de buscar ideas.",
    unknown:
      "Se desconoce el resultado del proveedor. FORMA no envió otra solicitud.",
    recommendation: "Sugerido por la investigación",
    recommendationSource: "Fuente usada para la recomendación",
    coverage: {
      complete: "Investigación terminada",
      partial: "Investigación parcial",
      no_sources: "No se encontraron citas utilizables",
      unavailable: "Investigación no disponible",
      not_run: "Investigación omitida",
    },
    decision: {
      eligible: "Hay diseños comprobados para revisar",
      needs_input: "Falta información",
      blocked: "Los materiales guardados impiden el diseño",
      undetermined: "La comprobación no pudo decidir",
      unsupported: "FORMA aún no comprueba este requisito",
    },
  },
};

export default function ResearchPanel({
  token,
  context,
  disabled,
  onInvalidate,
  onStockSearchBlocked,
  onReview,
}: {
  token: string;
  context: SearchContext;
  disabled: boolean;
  onInvalidate: (scope: "recommendation" | "search") => void;
  onStockSearchBlocked: (blocked: boolean) => void;
  onReview: (search: Search, recommendation: ResearchAdvice | null) => void;
}) {
  const { locale } = useMuseLanguage();
  const labels = copy[locale];
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [receiptLoaded, setReceiptLoaded] = useState(false);
  const [useCase, setUseCase] =
    useState<IntakeResearchRequest["use_case"]>("phone_stand");
  const [clearance, setClearance] = useState(false);
  const [consented, setConsented] = useState(false);
  const [pending, setPending] = useState<IntakeResearchRequest | null>(null);
  const [receiptError, setReceiptError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<"failed" | "stale" | "unknown" | null>(
    null,
  );
  const [result, setResult] = useState<ResearchResult | null>(null);
  const dispatch = useRef<AbortController | null>(null);
  const { projectId, inventoryRevisionId } = context;
  const needsClearance = pending?.needs_plug_clearance ?? clearance;

  useEffect(() => {
    onStockSearchBlocked(!receiptLoaded || needsClearance);
  }, [receiptLoaded, needsClearance, onStockSearchBlocked]);

  useEffect(() => {
    const load = new AbortController();
    setEnabled(null);
    setReceiptLoaded(false);
    setPending(null);
    setReceiptError(false);
    setConsented(false);
    setResult(null);
    setFailure(null);
    setBusy(false);
    async function initialize() {
      const api = researchApi(token, {
        projectId,
        inventoryRevisionId,
        activeVersionId: null,
        lastEventId: null,
      });
      try {
        const retained = await researchReceipts.pending(token, projectId);
        if (load.signal.aborted) return;
        setPending(retained);
        if (retained?.expected_inventory_revision_id === inventoryRevisionId) {
          setUseCase(retained.use_case);
          setClearance(retained.needs_plug_clearance);
        }
      } catch {
        if (!load.signal.aborted) setReceiptError(true);
      }
      if (load.signal.aborted) return;
      setReceiptLoaded(true);
      const available = await api.enabled(load.signal).catch(() => false);
      if (!load.signal.aborted) setEnabled(available);
    }
    void initialize();
    return () => {
      load.abort();
      dispatch.current?.abort();
      dispatch.current = null;
    };
  }, [token, projectId, inventoryRevisionId]);

  function stop() {
    dispatch.current?.abort();
    dispatch.current = null;
    setBusy(false);
    setConsented(false);
  }

  function reviseBrief(needsPlugClearance: boolean) {
    onInvalidate(needsPlugClearance ? "search" : "recommendation");
    setConsented(false);
    setResult(null);
    setFailure(null);
  }

  const old =
    pending !== null &&
    pending.expected_inventory_revision_id !== inventoryRevisionId;
  const brief = publicResearchBrief(
    pending?.use_case ?? useCase,
    needsClearance,
  );

  async function investigate() {
    if (
      !enabled ||
      disabled ||
      !consented ||
      dispatch.current ||
      old ||
      receiptError
    )
      return;
    const request: IntakeResearchRequest = pending ?? {
      expected_inventory_revision_id: inventoryRevisionId,
      idempotency_key: crypto.randomUUID(),
      consented: true,
      use_case: useCase,
      needs_plug_clearance: clearance,
    };
    const active = new AbortController();
    dispatch.current = active;
    setPending(request);
    setBusy(true);
    onInvalidate(request.needs_plug_clearance ? "search" : "recommendation");
    setResult(null);
    setFailure(null);
    try {
      await researchReceipts.retain(token, projectId, request);
      if (active.signal.aborted) return;
      let response;
      try {
        response = await researchApi(token, context).investigate(
          request,
          active.signal,
        );
      } catch (error) {
        if (active.signal.aborted) return;
        if (error instanceof SynthesisRequestError && error.stale)
          onInvalidate("search");
        if (error instanceof SynthesisRequestError && !error.retry) {
          await researchReceipts.clear(token, projectId, request);
          if (!active.signal.aborted) setPending(null);
        }
        if (!active.signal.aborted)
          setFailure(
            error instanceof SynthesisRequestError && error.stale
              ? "stale"
              : error instanceof Error &&
                  error.message === "generation_outcome_unknown"
                ? "unknown"
                : "failed",
          );
        return;
      }
      if (active.signal.aborted) return;
      await researchReceipts.clear(token, projectId, request);
      if (active.signal.aborted) return;
      setPending(null);
      setResult(response);
    } catch {
      if (!active.signal.aborted) setReceiptError(true);
    } finally {
      if (dispatch.current === active) {
        dispatch.current = null;
        setBusy(false);
        setConsented(false);
      }
    }
  }

  async function discard() {
    try {
      await researchReceipts.discard(token, projectId);
      setPending(null);
      if (!enabled) setClearance(false);
      setReceiptError(false);
      setConsented(false);
    } catch {
      setReceiptError(true);
    }
  }

  if (!enabled) {
    if (!needsClearance) return null;
    return (
      <fieldset className="design-muse" lang={locale}>
        <legend>{labels.title}</legend>
        <p>{labels.clearance}</p>
        <p className="help">{labels.clearanceGate}</p>
        {enabled === false && (
          <p role="status">{labels.coverage.unavailable}</p>
        )}
        {receiptError && <p role="alert">{labels.storedError}</p>}
        <button
          type="button"
          disabled={disabled}
          onClick={() => void discard()}
        >
          {labels.discard}
        </button>
      </fieldset>
    );
  }
  return (
    <fieldset className="design-muse" lang={locale}>
      <legend>{labels.title}</legend>
      <p>{labels.intro}</p>
      <p className="help">{labels.scope}</p>
      <label>
        {labels.useCase}
        <select
          value={pending?.use_case ?? useCase}
          disabled={disabled || busy || pending !== null}
          onChange={(event) => {
            setUseCase(
              event.target.value === "reading_stand"
                ? "reading_stand"
                : "phone_stand",
            );
            reviseBrief(clearance);
          }}
        >
          <option value="phone_stand">{labels.phone}</option>
          <option value="reading_stand">{labels.reading}</option>
        </select>
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={needsClearance}
          disabled={disabled || busy || pending !== null}
          onChange={(event) => {
            setClearance(event.target.checked);
            reviseBrief(event.target.checked);
          }}
        />
        {labels.clearance}
      </label>
      {needsClearance && <p className="help">{labels.clearanceGate}</p>}
      <p>
        <strong>{labels.brief}</strong>
      </p>
      <p lang="en">{brief}</p>
      <p className="help">{labels.transfer}</p>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={consented}
          disabled={disabled || busy || old || receiptError}
          onChange={(event) => setConsented(event.target.checked)}
        />
        {labels.consent}
      </label>
      {busy ? (
        <>
          <p className="help" role="status">
            {labels.working}
          </p>
          <button type="button" className="secondary" onClick={stop}>
            {labels.stop}
          </button>
        </>
      ) : (
        <>
          {pending && (
            <p className="notice">{old ? labels.old : labels.pending}</p>
          )}
          {receiptError && (
            <p className="error" role="alert">
              {labels.storedError}
            </p>
          )}
          {old || receiptError ? (
            <button
              type="button"
              className="secondary"
              disabled={disabled}
              onClick={() => void discard()}
            >
              {labels.discard}
            </button>
          ) : (
            <button
              type="button"
              disabled={disabled || !consented}
              onClick={() => void investigate()}
            >
              {pending ? labels.retry : labels.start}
            </button>
          )}
        </>
      )}
      {failure && (
        <p className="error" role="alert">
          {labels[failure]}
        </p>
      )}
      {result && (
        <div className="design-muse-answer" aria-live="polite">
          <p className="help">{labels.coverage[result.coverage]}</p>
          <p>
            <strong>{labels.decision[result.decision]}</strong>
          </p>
          <p>{result.reason}</p>
          {result.question && <p>{result.question}</p>}
          {result.findings.length > 0 && (
            <>
              <h4>{labels.sources}</h4>
              <ul>
                {result.findings.map((finding, index) => (
                  <li key={JSON.stringify(finding)}>
                    {result.recommendation_source_index === index && (
                      <p className="help">{labels.recommendationSource}</p>
                    )}
                    <a
                      href={finding.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {finding.title}
                    </a>
                    <p>{finding.claim}</p>
                  </li>
                ))}
              </ul>
            </>
          )}
          {result.search && result.decision === "eligible" && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => {
                if (!result.search) return;
                const index = result.recommendation_source_index;
                const candidateId = result.recommended_candidate_id;
                const source =
                  index == null ? undefined : result.findings[index];
                onReview(
                  result.search,
                  candidateId && source
                    ? { candidateId, reason: result.reason, source }
                    : null,
                );
              }}
            >
              {labels.review}
            </button>
          )}
        </div>
      )}
    </fieldset>
  );
}

export function ResearchRecommendation({ advice }: { advice: ResearchAdvice }) {
  const { locale } = useMuseLanguage();
  const labels = copy[locale];
  return (
    <div className="notice" lang={locale}>
      <p>
        <strong>{labels.recommendation}</strong>
      </p>
      <p lang="en">{advice.reason}</p>
      <p>
        {labels.recommendationSource}{" "}
        <a href={advice.source.url} target="_blank" rel="noopener noreferrer">
          {advice.source.title}
        </a>
      </p>
      <p>{advice.source.claim}</p>
    </div>
  );
}
