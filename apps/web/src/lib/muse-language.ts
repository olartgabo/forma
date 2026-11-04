export type MuseLocale = "en" | "es";

export function normalizeMuseLocale(value: unknown): MuseLocale {
  if (typeof value !== "string") return "en";
  const normalized = value.trim().toLowerCase();
  if (normalized === "es" || normalized.startsWith("es-")) return "es";
  return "en";
}

const en = {
  language: {
    label: "Muse interface language",
    note: "This changes Muse interface copy only. Muse answers follow the language of your goal or report; the rest of FORMA stays in English.",
    english: "EN",
    spanish: "ES",
    englishName: "English",
    spanishName: "Español",
  },
  provider: {
    checking: "Checking whether Muse is configured on this server…",
    checkFailed:
      "Couldn't check whether Muse is configured on this server. Muse actions remain available; if Muse isn't configured, the request will fail.",
    notConfiguredTitle: "Muse isn't configured on this server",
    notConfiguredBody:
      "Muse actions are unavailable. Ask the project operator to configure Muse, then retry.",
    notConfiguredReason:
      "Muse isn't configured on this server, so Muse actions are unavailable. Ask the project operator to configure Muse, then retry.",
    retryCheck: "Retry Muse configuration check",
    configured: "Muse is configured on this server.",
    configuredWithModel: (model: string) =>
      `Muse is configured on this server (${model}).`,
  },
  status: {
    pending: "Waiting for Muse",
    cancelled: "Request cancelled",
    timeout: "Request timed out",
    rateLimit: "Rate limit reached",
    providerNotConfigured: "Muse is not configured",
    invalidResponse: "Unusable Muse response",
    success: "Request completed",
    failure: "Muse request failed",
  },
  usage: {
    notReported: "not reported",
    reportedPrefix: "Provider-reported usage",
    reportedUnknown: "Provider-reported usage: not reported.",
    modelCalls: "model calls",
    inputTokens: "input tokens",
    outputTokens: "output tokens",
    duration: (ms: number) => `duration: ${ms} ms`,
    durationUnknown: "duration: not reported",
    combinedPrefix: "Diagnosis + repair usage",
    combinedUnknown: "Diagnosis + repair usage: not reported.",
    combinedDuration: (ms: number) => `summed request durations: ${ms} ms`,
    combinedDurationUnknown: "summed request durations: not reported",
  },
  diagnostics: {
    label: "Request diagnostics",
    status: "status",
    model: "model",
    rounds: "rounds",
    toolCalls: "tool calls",
  },
  actions: {
    cancel: "Cancel",
    retryLoadingManual: "Retry loading manual",
  },
  intake: {
    title: "Ask Muse about this photo",
    intro:
      "Muse can suggest candidate material labels and questions from one saved photo. Suggestions are proposals only: they do not fill in inventory values, confirm measurements, create stock or show that a physical check passed.",
    saveFirst: "Save a photo in this project first, then choose it here.",
    savedPhoto: "Saved photo",
    choosePhoto: "Choose a photo…",
    photo: "Photo",
    bytes: "bytes",
    cannotSend: "(cannot be sent to Muse)",
    photoGuidance: "Photo guidance:",
    ineligibleFormat:
      "Stored as a format Muse cannot read here. Save a JPEG or PNG photo instead.",
    ineligibleSize:
      "Larger than 5,000,000 bytes. Save a smaller JPEG or PNG photo instead.",
    formatHelp:
      "Muse can only read saved JPEG or PNG photos of 5,000,000 bytes or smaller. Photos in other formats or larger than that cannot be selected; save a JPEG or PNG photo instead.",
    consent:
      "Send the selected photo and this project's saved goal to Meta's Muse service for this one request. Do not send a photo you are not allowed to share.",
    stale:
      "Save or reload the inventory first: the saved inventory is stale or has unsaved changes, so Muse is unavailable until it matches the server.",
    ask: "Ask Muse about this photo",
    pending:
      "Asking Muse… Cancel stops FORMA waiting; Muse may still process this request. FORMA sends this photo request once and does not retry it automatically. A new request needs fresh consent.",
    cancelled:
      "Cancelled. FORMA stopped waiting for Muse; Muse may already be processing the photo, so no result was shown.",
    requestFailed:
      "The request could not finish. Check the API connection and try again.",
    candidateLabels: "Candidate labels",
    noLabels: "Muse returned no candidate labels.",
    questions: "Questions to check",
    noQuestions: "Muse returned no questions.",
    measurementSource: "Measurement source:",
    measurementNote:
      "A photo does not confirm measurements; measure and confirm values yourself before using them.",
  },
  diagnosis: {
    title: "Something went wrong",
    intro:
      "Send one saved failure photo and what you noticed to Muse for a read-only diagnosis. Muse separates what is visible from possible causes and questions. This does not change your plan or materials, record damage, or start a repair.",
    unverified:
      "Muse's diagnosis is unverified. A repair is only a draft until FORMA simulates it and you approve it; starting a repair review below does not change your plan or materials.",
    saveFirst:
      "Save a photo of the problem in this project first, then choose it here.",
    savedPhoto: "Saved failure photo",
    choosePhoto: "Choose a photo…",
    photo: "Photo",
    bytes: "bytes",
    cannotSend: "(cannot be sent to Muse)",
    formatHelp:
      "Muse can only read saved JPEG or PNG photos of 5,000,000 bytes or smaller. Save a smaller JPEG or PNG photo instead.",
    problemLabel: "What went wrong?",
    problemPlaceholder: "For example: the slot tore when I inserted the tab",
    problemHelp:
      "This is your report, not something Muse has observed. Muse will keep it separate from what is visible in the photo.",
    currentStep: "Current step",
    chooseStep: "Choose the current step…",
    step: "Step",
    loadingSteps: "Loading the active manual steps…",
    photoOnly:
      "No active manual yet, so this is a photo-only diagnosis. Build progress stays unknown and Muse cannot name affected plan parts.",
    consentActive:
      "Send the selected photo, my reported problem and this project's saved materials and active step to Meta's Muse service for this one request. Do not send a photo you are not allowed to share.",
    consent:
      "Send the selected photo, my reported problem and this project's saved materials to Meta's Muse service for this one request. Do not send a photo you are not allowed to share.",
    stale:
      "Save or reload the inventory first: Muse diagnosis is unavailable while saved materials are stale or have unsaved changes.",
    ask: "Ask Muse what went wrong",
    pending:
      "Asking Muse… Cancel stops FORMA waiting; Muse may still process this request. FORMA may retry a rate limit or temporary server error once by default, within the same deadline. Timeouts, network errors and unknown outcomes are not retried automatically. A new request needs fresh consent.",
    cancelled:
      "Cancelled. FORMA stopped waiting for Muse; Muse may already be processing the photo, so no result was shown.",
    requestFailed:
      "The request could not finish. Check the API connection and try again.",
    visible: "Visible observations",
    noVisible: "Muse reported no visible observations.",
    causes: "Possible causes (hypotheses)",
    noCauses: "Muse offered no hypotheses.",
    questions: "Questions or measurements to check",
    noQuestions: "Muse asked for no further measurements.",
    failureType: "Failure type:",
    affected: "Affected plan items:",
    noAffected: "No plan items were identified.",
    noPartTarget:
      "This diagnosis identified affected plan items, but no part-level repair target. Repair review requires an affected part; FORMA will not guess a part from these items.",
    measurementNote:
      "A photo does not confirm measurements or that a physical check passed; measure and check yourself.",
    repairHelp:
      "Muse's diagnosis is unverified. Reviewing a repair only starts a draft; FORMA must simulate it and you must approve it before anything changes. Nothing is sent to any API by this action.",
    reviewRepair: "Review a repair for",
  },
  repair: {
    title: "Ask Muse for repair options",
    intro:
      "Muse can propose repair candidates from your reported problem, the Muse diagnosis (if present) and the active plan context. Proposals are unverified: they are only added to the candidate list below. Nothing is simulated or approved until you confirm remaining stock, press Simulate repairs and approve a preview yourself.",
    needsDiagnosis:
      "Repair options require a Muse diagnosis with an affected part in the active plan. Use Review a repair for that part above, then return here. FORMA will not guess a repair target.",
    sendsContext:
      "This request sends your reported problem, the Muse diagnosis from the handoff and the active plan context to Meta's Muse service for this one request.",
    problemLabel: "Reported problem",
    problemPlaceholder: "For example: the brace tore at the slot",
    consent:
      "Send my reported problem, the Muse diagnosis if present and the active plan context to Meta's Muse service for this one request.",
    ask: "Ask Muse for repair options",
    pending:
      "Asking Muse… Cancel stops FORMA waiting; Muse may still process this request. FORMA may retry a rate limit or temporary server error once by default, within the same deadline. Timeouts, network errors and unknown outcomes are not retried automatically. A new request needs fresh consent.",
    cancelled:
      "Cancelled. FORMA stopped waiting for Muse; Muse may already be processing the request, so no result was shown.",
    requestFailed:
      "The request could not finish. Check the API connection and try again.",
    addedOne: (added: number) =>
      `Added ${added} Muse proposal${added === 1 ? "" : "s"} (unverified) to the candidate list. Confirm remaining stock and press Simulate repairs to preview ${added === 1 ? "it" : "them"}.`,
    noAdded: "No candidates were added.",
    skipped: (skipped: number) =>
      ` ${skipped} proposal${skipped === 1 ? " was" : "s were"} skipped (duplicate or the 3-candidate limit was reached).`,
    noCandidates:
      "Muse returned no repair candidates. No candidates were added; add a candidate yourself or give more detail and ask again.",
    needsInfo:
      "Muse needs more information before proposing repairs. No candidates were added from these questions.",
    alsoAsked: "Muse also asked the following questions.",
    questions: "Questions from Muse",
  },
  design: {
    title: "Generate with Muse",
    intro:
      "Muse proposes up to two designs from the saved project. FORMA compiles and saves only previews that pass its checks. Generating a preview does not approve a plan, record physical work or send a photo.",
    notesLabel: "Notes for Muse (optional)",
    consent:
      "Share this project's saved goal, materials, requirements and my notes above with Meta's Muse service for this one request. No photo is sent by this action.",
    activeHelp:
      "A plan is already active for this project, so Muse generation is unavailable until a revision flow is connected.",
    generate: "Generate with Muse",
    pending:
      "Asking Muse… Cancel stops FORMA waiting; Muse may still process this request. FORMA may retry a rate limit or temporary server error once by default, within the same deadline. Timeouts, network errors and unknown outcomes are not retried automatically. A new request needs fresh consent.",
    cancelled:
      "Cancelled. FORMA stopped waiting for Muse; Muse may already be processing the request. Its outcome is unknown, so check saved previews before starting a new request.",
    newRequestNotice:
      "The previous request outcome may be unknown. Check saved previews, then consent again and use Generate with Muse to start a new request with a fresh key.",
    unknownTitle: "Generation outcome unknown",
    unknownBody:
      "The previous Muse request may already have been processed, so its outcome is unknown. Check saved previews first; checking does not start a new run. Reusing the same request will not resume provider work or start another run. To start again, explicitly start a new request: consent is reset and a fresh key is created only when you generate again.",
    checkPreviews: "Check saved previews",
    startNew: "Start a new request",
    retryTitle: "Check the generation result",
    retryBody:
      "Check saved previews first, or send the identical Muse request again. That replays a saved result or reports the request state when one is saved; it does not resume provider work. If the previous request failed before any result was saved, sending it again may start a new provider run. Consent was used by the previous request, so tick the consent box above again before retrying.",
    retrySame: "Retry same Muse request",
    requestFailed: "Could not load this plan. Try again.",
    resultTitle: "Muse design result",
    status: "Status:",
    statusNote: "Saved previews below still require separate approval.",
    questions: "Questions to answer",
    blockers: "Blockers",
    savedPreview: "saved preview",
    noPlan:
      "No compiled plan has been saved for this project yet. Your materials and requirements are saved; use Generate with Muse above to ask for compiled previews.",
  },
};

export type MuseCopy = typeof en;

const es: MuseCopy = {
  language: {
    label: "Idioma de la interfaz de Muse",
    note: "Esto cambia solo los textos de la interfaz de Muse. Las respuestas de Muse siguen el idioma de tu objetivo o informe; el resto de FORMA permanece en inglés.",
    english: "EN",
    spanish: "ES",
    englishName: "English",
    spanishName: "Español",
  },
  provider: {
    checking: "Comprobando si Muse está configurado en este servidor…",
    checkFailed:
      "No se pudo comprobar si Muse está configurado en este servidor. Las acciones de Muse siguen disponibles; si Muse no está configurado, la solicitud fallará.",
    notConfiguredTitle: "Muse no está configurado en este servidor",
    notConfiguredBody:
      "Las acciones de Muse no están disponibles. Pide al operador del proyecto que configure Muse y vuelve a intentarlo.",
    notConfiguredReason:
      "Muse no está configurado en este servidor, por lo que las acciones de Muse no están disponibles. Pide al operador del proyecto que configure Muse y vuelve a intentarlo.",
    retryCheck: "Reintentar la comprobación de Muse",
    configured: "Muse está configurado en este servidor.",
    configuredWithModel: (model: string) =>
      `Muse está configurado en este servidor (${model}).`,
  },
  status: {
    pending: "Esperando a Muse",
    cancelled: "Solicitud cancelada",
    timeout: "La solicitud agotó el tiempo",
    rateLimit: "Se alcanzó el límite de solicitudes",
    providerNotConfigured: "Muse no está configurado",
    invalidResponse: "Respuesta de Muse no utilizable",
    success: "Solicitud completada",
    failure: "La solicitud a Muse falló",
  },
  usage: {
    notReported: "no informado",
    reportedPrefix: "Uso informado por el proveedor",
    reportedUnknown: "Uso informado por el proveedor: no informado.",
    modelCalls: "llamadas al modelo",
    inputTokens: "tokens de entrada",
    outputTokens: "tokens de salida",
    duration: (ms: number) => `duración: ${ms} ms`,
    durationUnknown: "duración: no informada",
    combinedPrefix: "Uso de diagnóstico + reparación",
    combinedUnknown: "Uso de diagnóstico + reparación: no informado.",
    combinedDuration: (ms: number) =>
      `suma de duraciones de las solicitudes: ${ms} ms`,
    combinedDurationUnknown:
      "suma de duraciones de las solicitudes: no informada",
  },
  diagnostics: {
    label: "Diagnóstico de la solicitud",
    status: "estado",
    model: "modelo",
    rounds: "rondas",
    toolCalls: "llamadas a herramientas",
  },
  actions: {
    cancel: "Cancelar",
    retryLoadingManual: "Reintentar cargar el manual",
  },
  intake: {
    title: "Preguntar a Muse sobre esta foto",
    intro:
      "Muse puede sugerir etiquetas candidatas de materiales y preguntas a partir de una foto guardada. Las sugerencias son solo propuestas: no completan valores del inventario, no confirman medidas, no crean existencias ni demuestran que una comprobación física haya pasado.",
    saveFirst: "Guarda primero una foto en este proyecto y luego elígela aquí.",
    savedPhoto: "Foto guardada",
    choosePhoto: "Elige una foto…",
    photo: "Foto",
    bytes: "bytes",
    cannotSend: "(no se puede enviar a Muse)",
    photoGuidance: "Guía sobre la foto:",
    ineligibleFormat:
      "Está guardada en un formato que Muse no puede leer aquí. Guarda en su lugar una foto JPEG o PNG.",
    ineligibleSize:
      "Supera los 5,000,000 bytes. Guarda en su lugar una foto JPEG o PNG más pequeña.",
    formatHelp:
      "Muse solo puede leer fotos JPEG o PNG guardadas de 5,000,000 bytes o menos. Las fotos en otros formatos o más grandes no se pueden seleccionar; guarda en su lugar una foto JPEG o PNG.",
    consent:
      "Enviar la foto seleccionada y el objetivo guardado de este proyecto al servicio Muse de Meta solo para esta solicitud. No envíes una foto que no tengas permiso para compartir.",
    stale:
      "Guarda o recarga primero el inventario: el inventario guardado está desactualizado o tiene cambios sin guardar, por lo que Muse no estará disponible hasta que coincida con el servidor.",
    ask: "Preguntar a Muse sobre esta foto",
    pending:
      "Preguntando a Muse… Cancelar hace que FORMA deje de esperar; Muse puede seguir procesando esta solicitud. FORMA envía esta solicitud de foto una sola vez y no la reintenta automáticamente. Una nueva solicitud requiere un nuevo consentimiento.",
    cancelled:
      "Cancelado. FORMA dejó de esperar a Muse; es posible que Muse ya esté procesando la foto, por lo que no se mostró ningún resultado.",
    requestFailed:
      "La solicitud no pudo terminar. Comprueba la conexión con la API e inténtalo de nuevo.",
    candidateLabels: "Etiquetas candidatas",
    noLabels: "Muse no devolvió etiquetas candidatas.",
    questions: "Preguntas por comprobar",
    noQuestions: "Muse no devolvió preguntas.",
    measurementSource: "Fuente de la medida:",
    measurementNote:
      "Una foto no confirma las medidas; mide y confirma los valores tú mismo antes de usarlos.",
  },
  diagnosis: {
    title: "Algo salió mal",
    intro:
      "Envía a Muse una foto guardada del fallo y lo que observaste para obtener un diagnóstico de solo lectura. Muse separa lo visible de las posibles causas y preguntas. Esto no cambia tu plan ni tus materiales, no registra daños ni inicia una reparación.",
    unverified:
      "El diagnóstico de Muse no está verificado. Una reparación es solo un borrador hasta que FORMA la simule y tú la apruebes; iniciar una revisión de reparación abajo no cambia tu plan ni tus materiales.",
    saveFirst:
      "Guarda primero una foto del problema en este proyecto y luego elígela aquí.",
    savedPhoto: "Foto guardada del fallo",
    choosePhoto: "Elige una foto…",
    photo: "Foto",
    bytes: "bytes",
    cannotSend: "(no se puede enviar a Muse)",
    formatHelp:
      "Muse solo puede leer fotos JPEG o PNG guardadas de 5,000,000 bytes o menos. Guarda en su lugar una foto JPEG o PNG más pequeña.",
    problemLabel: "¿Qué salió mal?",
    problemPlaceholder:
      "Por ejemplo: la ranura se rasgó al insertar la lengüeta",
    problemHelp:
      "Este es tu informe, no algo que Muse haya observado. Muse lo mantendrá separado de lo visible en la foto.",
    currentStep: "Paso actual",
    chooseStep: "Elige el paso actual…",
    step: "Paso",
    loadingSteps: "Cargando los pasos del manual activo…",
    photoOnly:
      "Aún no hay un manual activo, por lo que este es un diagnóstico solo con foto. El progreso de la construcción sigue siendo desconocido y Muse no puede nombrar piezas del plan afectadas.",
    consentActive:
      "Enviar la foto seleccionada, el problema que informé y los materiales guardados y el paso activo de este proyecto al servicio Muse de Meta solo para esta solicitud. No envíes una foto que no tengas permiso para compartir.",
    consent:
      "Enviar la foto seleccionada, el problema que informé y los materiales guardados de este proyecto al servicio Muse de Meta solo para esta solicitud. No envíes una foto que no tengas permiso para compartir.",
    stale:
      "Guarda o recarga primero el inventario: el diagnóstico de Muse no está disponible mientras los materiales guardados estén desactualizados o tengan cambios sin guardar.",
    ask: "Preguntar a Muse qué salió mal",
    pending:
      "Preguntando a Muse… Cancelar hace que FORMA deje de esperar; Muse puede seguir procesando esta solicitud. FORMA puede reintentar una vez por defecto ante un límite de solicitudes o un error temporal del servidor, dentro del mismo plazo. No reintenta automáticamente los tiempos agotados, errores de red ni resultados desconocidos. Una nueva solicitud requiere un nuevo consentimiento.",
    cancelled:
      "Cancelado. FORMA dejó de esperar a Muse; es posible que Muse ya esté procesando la foto, por lo que no se mostró ningún resultado.",
    requestFailed:
      "La solicitud no pudo terminar. Comprueba la conexión con la API e inténtalo de nuevo.",
    visible: "Observaciones visibles",
    noVisible: "Muse no informó observaciones visibles.",
    causes: "Posibles causas (hipótesis)",
    noCauses: "Muse no ofreció hipótesis.",
    questions: "Preguntas o medidas por comprobar",
    noQuestions: "Muse no pidió más medidas.",
    failureType: "Tipo de fallo:",
    affected: "Elementos del plan afectados:",
    noAffected: "No se identificaron elementos del plan.",
    noPartTarget:
      "Este diagnóstico identificó elementos del plan afectados, pero ninguna pieza para reparar. Revisar una reparación requiere una pieza afectada; FORMA no deducirá una pieza a partir de estos elementos.",
    measurementNote:
      "Una foto no confirma las medidas ni que una comprobación física haya pasado; mide y comprueba tú mismo.",
    repairHelp:
      "El diagnóstico de Muse no está verificado. Revisar una reparación solo inicia un borrador; FORMA debe simularla y tú debes aprobarla antes de que cambie algo. Esta acción no envía nada a ninguna API.",
    reviewRepair: "Revisar una reparación para",
  },
  repair: {
    title: "Pedir opciones de reparación a Muse",
    intro:
      "Muse puede proponer reparaciones candidatas a partir del problema que informaste, el diagnóstico de Muse (si lo hay) y el contexto del plan activo. Las propuestas no están verificadas: solo se añaden a la lista de candidatas de abajo. Nada se simula ni se aprueba hasta que confirmes las existencias restantes, pulses Simular reparaciones y apruebes tú mismo una vista previa.",
    needsDiagnosis:
      "Las opciones de reparación requieren un diagnóstico de Muse con una pieza afectada del plan activo. Usa Revisar una reparación para esa pieza arriba y luego vuelve aquí. FORMA no adivinará qué pieza reparar.",
    sendsContext:
      "Esta solicitud envía el problema que informaste, el diagnóstico de Muse de la transferencia y el contexto del plan activo al servicio Muse de Meta solo para esta solicitud.",
    problemLabel: "Problema informado",
    problemPlaceholder: "Por ejemplo: el refuerzo se rasgó en la ranura",
    consent:
      "Enviar el problema que informé, el diagnóstico de Muse si lo hay y el contexto del plan activo al servicio Muse de Meta solo para esta solicitud.",
    ask: "Pedir opciones de reparación a Muse",
    pending:
      "Preguntando a Muse… Cancelar hace que FORMA deje de esperar; Muse puede seguir procesando esta solicitud. FORMA puede reintentar una vez por defecto ante un límite de solicitudes o un error temporal del servidor, dentro del mismo plazo. No reintenta automáticamente los tiempos agotados, errores de red ni resultados desconocidos. Una nueva solicitud requiere un nuevo consentimiento.",
    cancelled:
      "Cancelado. FORMA dejó de esperar a Muse; es posible que Muse ya esté procesando la solicitud, por lo que no se mostró ningún resultado.",
    requestFailed:
      "La solicitud no pudo terminar. Comprueba la conexión con la API e inténtalo de nuevo.",
    addedOne: (added: number) =>
      `Se añadió ${added === 1 ? "1 propuesta de Muse (sin verificar)" : `${added} propuestas de Muse (sin verificar)`} a la lista de candidatas. Confirma las existencias restantes y pulsa Simular reparaciones para ver la vista previa.`,
    noAdded: "No se añadieron candidatas.",
    skipped: (skipped: number) =>
      ` Se omitió ${skipped === 1 ? "1 propuesta" : `${skipped} propuestas`} (duplicada o se alcanzó el límite de 3 candidatas).`,
    noCandidates:
      "Muse no devolvió reparaciones candidatas. No se añadió ninguna; añade una candidata tú mismo o da más detalles y vuelve a preguntar.",
    needsInfo:
      "Muse necesita más información antes de proponer reparaciones. No se añadieron candidatas a partir de estas preguntas.",
    alsoAsked: "Muse también hizo las siguientes preguntas.",
    questions: "Preguntas de Muse",
  },
  design: {
    title: "Generar con Muse",
    intro:
      "Muse propone hasta dos diseños a partir del proyecto guardado. FORMA compila y guarda solo las vistas previas que superan sus comprobaciones. Generar una vista previa no aprueba un plan, no registra trabajo físico ni envía una foto.",
    notesLabel: "Notas para Muse (opcional)",
    consent:
      "Compartir el objetivo guardado, los materiales, los requisitos de este proyecto y mis notas de arriba con el servicio Muse de Meta solo para esta solicitud. Esta acción no envía ninguna foto.",
    activeHelp:
      "Ya hay un plan activo para este proyecto, por lo que la generación con Muse no está disponible hasta que se conecte un flujo de revisión.",
    generate: "Generar con Muse",
    pending:
      "Preguntando a Muse… Cancelar hace que FORMA deje de esperar; Muse puede seguir procesando esta solicitud. FORMA puede reintentar una vez por defecto ante un límite de solicitudes o un error temporal del servidor, dentro del mismo plazo. No reintenta automáticamente los tiempos agotados, errores de red ni resultados desconocidos. Una nueva solicitud requiere un nuevo consentimiento.",
    cancelled:
      "Cancelado. FORMA dejó de esperar a Muse; es posible que Muse ya esté procesando la solicitud. Su resultado es desconocido, así que comprueba las vistas previas guardadas antes de iniciar una nueva solicitud.",
    newRequestNotice:
      "El resultado de la solicitud anterior puede ser desconocido. Comprueba las vistas previas guardadas, luego da tu consentimiento de nuevo y usa Generar con Muse para iniciar una nueva solicitud con una clave nueva.",
    unknownTitle: "Resultado de la generación desconocido",
    unknownBody:
      "Es posible que la solicitud anterior a Muse ya se haya procesado, por lo que su resultado es desconocido. Comprueba primero las vistas previas guardadas; comprobar no inicia una nueva ejecución. Reutilizar la misma solicitud no reanudará el trabajo del proveedor ni iniciará otra ejecución. Para empezar de nuevo, inicia explícitamente una nueva solicitud: el consentimiento se restablece y solo se crea una clave nueva cuando vuelvas a generar.",
    checkPreviews: "Comprobar vistas previas guardadas",
    startNew: "Iniciar una nueva solicitud",
    retryTitle: "Comprobar el resultado de la generación",
    retryBody:
      "Comprueba primero las vistas previas guardadas, o envía de nuevo la misma solicitud a Muse. Eso reproduce un resultado guardado o informa del estado de la solicitud cuando hay uno guardado; no reanuda el trabajo del proveedor. Si la solicitud anterior falló antes de que se guardara algún resultado, enviarla de nuevo puede iniciar una nueva ejecución del proveedor. La solicitud anterior ya usó el consentimiento, así que marca de nuevo la casilla de consentimiento de arriba antes de reintentar.",
    retrySame: "Reintentar la misma solicitud a Muse",
    requestFailed: "No se pudo cargar este plan. Inténtalo de nuevo.",
    resultTitle: "Resultado del diseño de Muse",
    status: "Estado:",
    statusNote:
      "Las vistas previas guardadas de abajo siguen requiriendo una aprobación por separado.",
    questions: "Preguntas por responder",
    blockers: "Bloqueos",
    savedPreview: "vista previa guardada",
    noPlan:
      "Aún no se ha guardado ningún plan compilado para este proyecto. Tus materiales y requisitos están guardados; usa Generar con Muse arriba para pedir vistas previas compiladas.",
  },
};

export const museCopy: Record<MuseLocale, MuseCopy> = { en, es };

export function museCopyFor(locale: unknown): MuseCopy {
  return museCopy[normalizeMuseLocale(locale)];
}

// Numbers keep English grouping regardless of UI locale; only labels
// are translated. This preserves values such as 12,345 after a toggle.
export function formatEnglishGroupedNumber(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return value.toLocaleString("en-US");
}

export type MuseNoticeId =
  | "intake-cancelled"
  | "diagnosis-cancelled"
  | "repair-cancelled"
  | "design-cancelled"
  | "design-new-request";

// Notices are stored by identity, not by already-translated text, so a
// retained notice renders in the locale current at render time.
export function museNoticeText(notice: unknown, locale: unknown): string {
  const copy = museCopyFor(locale);
  switch (notice) {
    case "intake-cancelled":
      return copy.intake.cancelled;
    case "diagnosis-cancelled":
      return copy.diagnosis.cancelled;
    case "repair-cancelled":
      return copy.repair.cancelled;
    case "design-cancelled":
      return copy.design.cancelled;
    case "design-new-request":
      return copy.design.newRequestNotice;
    default:
      return "";
  }
}

export type MuseFailureSection = "intake" | "diagnosis" | "repair" | "design";

export type MuseStoredFailure = {
  code?: string;
  apiMessage?: string;
  fallbackSection?: MuseFailureSection;
};

function fallbackText(section: unknown, locale: unknown): string {
  const copy = museCopyFor(locale);
  switch (section) {
    case "diagnosis":
      return copy.diagnosis.requestFailed;
    case "repair":
      return copy.repair.requestFailed;
    case "design":
      return copy.design.requestFailed;
    default:
      return copy.intake.requestFailed;
  }
}

// API-provided (already sanitized) messages stay verbatim; only the
// generic local fallback is derived from the current locale.
export function museFailureText(failure: unknown, locale: unknown): string {
  if (typeof failure !== "object" || failure === null) return "";
  const stored = failure as Record<string, unknown>;
  if (typeof stored.apiMessage === "string" && stored.apiMessage)
    return stored.apiMessage;
  return fallbackText(stored.fallbackSection, locale);
}

export function museStoredFailure(input: {
  apiMessage?: unknown;
  code?: unknown;
  fallbackSection: MuseFailureSection;
}): MuseStoredFailure {
  return {
    ...(typeof input.code === "string" ? { code: input.code } : {}),
    ...(typeof input.apiMessage === "string" && input.apiMessage
      ? { apiMessage: input.apiMessage }
      : { fallbackSection: input.fallbackSection }),
  };
}

// For string state owned by helpers that cannot retain an object (the
// diagnosis plan loader), a stored English generic fallback is re-derived
// in the current locale, while any other (API-provided) text is verbatim.
export function resolveStoredFailureText(
  text: unknown,
  fallbackSection: MuseFailureSection,
  locale: unknown,
): string {
  if (typeof text !== "string") return "";
  if (text === fallbackText(fallbackSection, "en"))
    return fallbackText(fallbackSection, locale);
  return text;
}
