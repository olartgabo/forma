import { useEffect, useRef, useState } from "react";
import type {
  InventoryUpdate,
  Project,
  UnavailableRequest,
} from "../../lib/generated/api-contracts";
import type { MeasurementDecision } from "../../lib/generated/contracts";
import {
  type Baseline,
  type Change,
  type Decision,
  MeasurementRequestError,
  answerBody,
  answerReceipts,
  baselineAfterSave,
  baselineForAnswer,
  baselineForStand,
  baselineReceipts,
  measurementApi,
  unavailableReceipts,
} from "./client";

const HEADINGS: Record<Decision["outcome"], string> = {
  question: "Measure this next",
  none_needed: "No further measurement is needed",
  no_feasible_candidate: "No design fits the confirmed stock",
  unsupported: "A measurement here cannot settle this",
  physical_test_required: "A build or physical test is needed next",
  budget_exhausted: "The design search ran out of budget",
};
const UNITS: Record<string, string> = {
  mm: "millimetres (mm)",
  g: "grams (g)",
  deg: "degrees",
  batch: "grams and millimetres, in the measurement form",
};

function message(error: unknown) {
  return error instanceof Error ? error.message : "The request failed.";
}

export default function ActiveMeasurement({
  token,
  project,
  disabled,
  onSaved,
}: {
  token: string;
  project: Project;
  disabled: boolean;
  onSaved: () => void;
}) {
  const [decision, setDecision] = useState<Decision | null>(null);
  const [change, setChange] = useState<Change | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // The typed value and confirmation belong to one question only. A different
  // question (after deciding, declining or recalculating) starts empty.
  const [answer, setAnswer] = useState({
    questionId: "",
    value: "",
    measured: false,
  });
  // Sent requests with unknown outcomes, and the decision a saved answer is
  // compared with. Each kind is kept, checked and cleared on its own.
  const [pendingAnswer, setPendingAnswer] = useState<InventoryUpdate | null>(
    null,
  );
  const [savedAnswerKey, setSavedAnswerKey] = useState<string | null>(null);
  const [pendingUnavailable, setPendingUnavailable] =
    useState<UnavailableRequest | null>(null);
  const [baseline, setBaseline] = useState<Baseline | null>(null);
  const [receiptErrors, setReceiptErrors] = useState<Record<string, string>>(
    {},
  );
  const controller = useRef<AbortController | null>(null);
  const api = measurementApi(token, project.id);
  const identity = {
    expected_inventory_revision_id: project.revision_id,
    expected_active_version_id: project.active_version_id ?? null,
  };
  const contextKey = `${project.id}:${project.revision_id}:${project.active_version_id}`;

  useEffect(() => {
    controller.current?.abort();
    setDecision(null);
    setError("");
    setAnswer({ questionId: "", value: "", measured: false });
  }, [contextKey, token]);

  // Receipt state belongs to the owner/project, not an inventory revision.
  // A refresh after a confirmed save must not replace it with stale storage.
  useEffect(() => {
    setSavedAnswerKey(null);
    let live = true;
    const load = <T,>(
      name: string,
      promise: Promise<T | null>,
      set: (value: T | null) => void,
    ) =>
      promise.then(
        (found) => {
          if (!live) return;
          set(found);
          setReceiptErrors((current) => ({ ...current, [name]: "" }));
        },
        (failure: unknown) => {
          if (live)
            setReceiptErrors((current) => ({
              ...current,
              [name]: message(failure),
            }));
        },
      );
    load("answer", answerReceipts.pending(token, project.id), setPendingAnswer);
    load(
      "unavailable",
      unavailableReceipts.pending(token, project.id),
      setPendingUnavailable,
    );
    load("baseline", baselineReceipts.pending(token, project.id), setBaseline);
    return () => {
      live = false;
    };
  }, [token, project.id]);
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

  async function keepBaseline(next: Baseline | null) {
    if (next) await baselineReceipts.replace(token, project.id, next);
    else await baselineReceipts.discard(token, project.id);
    setBaseline(next);
  }

  /** Show a decision; a built-stand question becomes the comparison point. */
  async function show(next: Decision, from: Baseline | null = baseline) {
    setDecision(next);
    const kept = baselineForStand(from, next);
    if (kept !== from) {
      try {
        await keepBaseline(kept);
      } catch (failure) {
        setError(message(failure));
      }
    }
  }

  async function decide() {
    try {
      const next = await run((signal) => api.decide(identity, signal));
      setChange(null);
      await show(next);
    } catch (failure) {
      setError(message(failure));
    }
  }

  async function sendAnswer(
    body: InventoryUpdate,
    before: MeasurementDecision | null,
  ) {
    const kept = baselineForAnswer(baseline, before);
    try {
      // Keep the comparison point first, then the exact request.
      if (kept !== baseline) await keepBaseline(kept);
      await answerReceipts.retain(token, project.id, body);
    } catch (failure) {
      setError(message(failure));
      return;
    }
    setPendingAnswer(body);
    try {
      await run((signal) => api.saveInventory(body, signal));
    } catch (failure) {
      if (!(failure instanceof MeasurementRequestError && failure.retry)) {
        // A definite refusal saved nothing: say so, and drop the comparison
        // point unless an earlier answer was saved.
        await answerReceipts.clear(token, project.id, body);
        setPendingAnswer(null);
        await keepBaseline(baselineAfterSave(kept, false)).catch(() => {});
        setError(`The measurement was not saved. ${message(failure)}`);
        return;
      }
      setError(message(failure));
      return;
    }

    // The server confirmed the save. Local receipt failures cannot change that
    // outcome or prevent the workbench from fetching the saved inventory.
    const saved = baselineAfterSave(kept, true);
    setSavedAnswerKey(body.idempotency_key);
    setBaseline(saved);
    setAnswer({ questionId: "", value: "", measured: false });
    try {
      // Keep the exact retry until the saved comparison point is durable too.
      await keepBaseline(saved);
      await answerReceipts.clear(token, project.id, body);
      setPendingAnswer(null);
    } catch (failure) {
      setError(
        `The measurement was saved, but its local recovery record could not be updated. ${message(failure)}`,
      );
    }
    onSaved();
  }

  function saveAnswer() {
    const question = decision?.question;
    if (!decision || !question) return;
    if (pendingAnswer) {
      setError(
        "An earlier measurement has an unknown outcome. Retry it first.",
      );
      return;
    }
    let body: InventoryUpdate;
    try {
      body = answerBody(
        project,
        question,
        question.target.property === "usable_region" ? null : Number(value),
        crypto.randomUUID(),
      );
    } catch (failure) {
      setError(message(failure));
      return;
    }
    void sendAnswer(body, decision);
  }

  async function sendUnavailable(body: UnavailableRequest) {
    try {
      await unavailableReceipts.retain(token, project.id, body);
    } catch (failure) {
      setError(message(failure));
      return;
    }
    setPendingUnavailable(body);
    try {
      const next = await run((signal) => api.unavailable(body, signal));
      await unavailableReceipts.clear(token, project.id, body);
      setPendingUnavailable(null);
      setChange(null);
      await show(next);
    } catch (failure) {
      if (!(failure instanceof MeasurementRequestError && failure.retry)) {
        await unavailableReceipts.clear(token, project.id, body);
        setPendingUnavailable(null);
      }
      setError(message(failure));
    }
  }

  function markUnavailable() {
    const question = decision?.question;
    if (!decision || !question || pendingUnavailable) return;
    void sendUnavailable({
      ...identity,
      expected_last_event_id: decision.identity.last_event_id ?? null,
      question_id: question.question_id,
      target_key: question.target.key,
      idempotency_key: crypto.randomUUID(),
      user_confirmed: true,
    });
  }

  async function recalculate() {
    if (!baseline) return;
    try {
      const next = await run((signal) =>
        api.recalculate({ ...identity, baseline: baseline.decision }, signal),
      );
      setChange(next);
      await keepBaseline(null);
      await show(next.after, null);
    } catch (failure) {
      setError(message(failure));
    }
  }

  async function discard(name: "answer" | "unavailable" | "baseline") {
    const store = {
      answer: answerReceipts,
      unavailable: unavailableReceipts,
      baseline: baselineReceipts,
    }[name];
    await store.discard(token, project.id);
    if (name === "answer") setPendingAnswer(null);
    if (name === "unavailable") setPendingUnavailable(null);
    if (name === "baseline") setBaseline(null);
    setReceiptErrors((current) => ({ ...current, [name]: "" }));
  }

  const question = decision?.question ?? null;
  const current =
    question !== null && answer.questionId === question.question_id
      ? answer
      : { questionId: question?.question_id ?? "", value: "", measured: false };
  const value = current.value;
  const measured = current.measured;
  const blocked =
    disabled || busy || Object.values(receiptErrors).some(Boolean);
  const numeric =
    question !== null &&
    question.capture !== "stability_measurements" &&
    question.target.property !== "usable_region";

  return (
    <section
      className="active-measurement"
      aria-labelledby="active-measurement-title"
    >
      <h3 id="active-measurement-title">The measurement that matters next</h3>
      <p>
        FORMA asks only for a confirmed measurement that can change which
        designs fit or whether a built stand can be checked. It never fills in a
        value for you, and finding a question saves nothing.
      </p>
      <button
        type="button"
        disabled={disabled || busy}
        onClick={() => void decide()}
      >
        Find the measurement that matters
      </button>
      <div aria-live="polite">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {Object.entries(receiptErrors)
          .filter(([, text]) => text)
          .map(([name, text]) => (
            <div className="error" role="alert" key={name}>
              <p>{text}</p>
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  void discard(name as "answer" | "unavailable" | "baseline")
                }
              >
                Clear this unverifiable record
              </button>
            </div>
          ))}
        {pendingAnswer && (
          <div className="notice">
            <p>
              {savedAnswerKey === pendingAnswer.idempotency_key
                ? "The measurement was saved, but its local recovery record still needs updating."
                : "A measurement was sent but its result is unknown."}{" "}
              Retrying sends the same request, so it cannot be saved twice.
            </p>
            <button
              type="button"
              disabled={blocked}
              onClick={() =>
                void sendAnswer(pendingAnswer, baseline?.decision ?? null)
              }
            >
              Retry saving the measurement
            </button>
          </div>
        )}
        {pendingUnavailable && (
          <button
            type="button"
            disabled={blocked}
            onClick={() => void sendUnavailable(pendingUnavailable)}
          >
            Retry marking the measurement unavailable
          </button>
        )}
        {baseline && !pendingAnswer && (
          <div className="notice">
            <p>
              {baseline.state === "saved"
                ? "A measurement was saved. Recalculate to see what changed and whether any decision changed."
                : baseline.state === "external"
                  ? "After you record the assembled-stand measurements in the stability panel, recalculate here to compare with this question."
                  : "An earlier measurement was sent, but whether it was saved is unknown. Recalculate to compare the current saved values with the earlier decision."}{" "}
              Nothing is approved or built by this.
            </p>
            <button
              type="button"
              disabled={blocked}
              onClick={() => void recalculate()}
            >
              Recalculate
            </button>
          </div>
        )}
      </div>
      {change && (
        <article className="measurement-change" aria-label="What changed">
          <h4>
            {change.decision_changed
              ? "The decision changed"
              : "The decision did not change"}
          </h4>
          <p>{change.explanation}</p>
          {change.changed_facts.length > 0 && (
            <ul>
              {change.changed_facts.map((fact) => (
                <li key={fact}>{fact}</li>
              ))}
            </ul>
          )}
        </article>
      )}
      {decision && (
        <article
          className="measurement-decision"
          aria-label="Measurement decision"
        >
          <h4>{HEADINGS[decision.outcome]}</h4>
          {question && (
            <>
              <p>
                <strong>{question.target.label}</strong>
              </p>
              <dl className="design-candidate-facts">
                <dt>Where</dt>
                <dd>{question.where}</dd>
                <dt>How</dt>
                <dd>{question.method}</dd>
                <dt>Units</dt>
                <dd>{UNITS[question.unit]}</dd>
                {question.threshold && (
                  <>
                    <dt>Decides</dt>
                    <dd>
                      {question.threshold.comparison === "within"
                        ? `Between ${question.threshold.lower} and ${question.threshold.upper} ${question.threshold.unit}`
                        : `At least ${question.threshold.lower} ${question.threshold.unit}`}
                      . {question.threshold.basis}
                    </dd>
                  </>
                )}
                <dt>Precision</dt>
                <dd>{question.precision_basis}</dd>
                {question.current && question.current.value != null && (
                  <>
                    <dt>Saved now</dt>
                    <dd>
                      {question.current.value} {question.current.unit}
                      {question.current.confirmed
                        ? ""
                        : " (an unconfirmed estimate; it is not used)"}
                    </dd>
                  </>
                )}
                {(question.target.pieces ?? []).length > 0 && (
                  <>
                    <dt>Pieces</dt>
                    <dd>
                      {(question.target.pieces ?? [])
                        .map((p) => `${p.display_name} (${p.reference})`)
                        .join(", ")}
                    </dd>
                  </>
                )}
                {(question.affected_candidate_ids ?? []).length > 0 && (
                  <>
                    <dt>Could change</dt>
                    <dd>
                      {(question.affected_candidate_ids ?? []).join(", ")}
                    </dd>
                  </>
                )}
                {(question.affected_case_ids ?? []).length > 0 && (
                  <>
                    <dt>Cases</dt>
                    <dd>{(question.affected_case_ids ?? []).join(", ")}</dd>
                  </>
                )}
              </dl>
              <p>
                <strong>Why it matters:</strong> {question.why}
              </p>
              {question.capture === "stability_measurements" ? (
                <p className="help">
                  Record these values with{" "}
                  <strong>Record assembled-stand measurements</strong> in the
                  stability panel of the active manual, then recalculate here.
                </p>
              ) : (
                <div className="measurement-answer">
                  {numeric && (
                    <>
                      <label htmlFor="measurement-value">
                        Measured value ({question.unit})
                      </label>
                      <input
                        id="measurement-value"
                        inputMode="decimal"
                        value={value}
                        onChange={(event) =>
                          setAnswer({ ...current, value: event.target.value })
                        }
                      />
                    </>
                  )}
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={measured}
                      onChange={(event) =>
                        setAnswer({
                          ...current,
                          measured: event.target.checked,
                        })
                      }
                    />
                    {numeric
                      ? "I measured this myself; it is not a photo estimate"
                      : "I checked that the whole measured sheet is flat and usable"}
                  </label>
                  <button
                    type="button"
                    disabled={
                      blocked ||
                      !measured ||
                      (numeric && !value) ||
                      pendingAnswer !== null
                    }
                    onClick={saveAnswer}
                  >
                    Save measurement
                  </button>
                </div>
              )}
              <button
                type="button"
                className="secondary"
                disabled={blocked || pendingUnavailable !== null}
                onClick={markUnavailable}
              >
                I can&apos;t measure this
              </button>
              {decision.pending_questions > 0 && (
                <p className="help">
                  {decision.pending_questions} more measurement(s) could also
                  matter; FORMA asks one at a time.
                </p>
              )}
            </>
          )}
          <ul>
            {decision.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
          {decision.missing_capabilities.length > 0 && (
            <>
              <h5>Not supported yet</h5>
              <ul>
                {decision.missing_capabilities.map((gap) => (
                  <li key={gap}>{gap}</li>
                ))}
              </ul>
            </>
          )}
          {decision.settings.length > 0 && (
            <>
              <h5>Design settings</h5>
              <ul>
                {decision.settings.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </>
          )}
          {decision.invalidated.length > 0 && (
            <ul>
              {decision.invalidated.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
          <details>
            <summary>How the question is chosen</summary>
            <p>{decision.selection_rule}</p>
          </details>
        </article>
      )}
    </section>
  );
}
