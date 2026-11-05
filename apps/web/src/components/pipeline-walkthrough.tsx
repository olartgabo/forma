"use client";

import { useEffect, useRef, useState } from "react";
import type { ManualPanel } from "../lib/generated/api-contracts";
import type { AssemblyViewResponse } from "../lib/generated/contracts";
import {
  initialCamera,
  projectFacets,
} from "../../../../packages/assembly_view/projection";
import { DeveloperOnly } from "./developer-mode";
import Diagram from "./manual-diagram";
import FormaWordmark from "./forma-wordmark";
import styles from "./pipeline-walkthrough.module.css";

type Value =
  null | boolean | number | string | Value[] | { [key: string]: Value };
type Step = {
  id: string;
  title: string;
  engine: string;
  input: Value;
  output: Value;
  status: string;
  result_status?: string;
  description?: string;
  error?: Value;
  summary?: string;
  image?: string;
};
type Snapshot = {
  schema_version: number;
  generated_at: string;
  label: string;
  source_head?: string;
  physical_verification: string;
  provider_calls: number;
  actual_usage_totals?: {
    input_tokens: number;
    output_tokens: number;
    images_processed: number;
  };
  steps: Step[];
  limitations: string[];
};

function label(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function Reply({ value, depth = 0 }: { value: Value; depth?: number }) {
  if (value === null) return <span className={styles.muted}>Not supplied</span>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (typeof value !== "object") {
    if (typeof value === "string" && value.includes("<svg"))
      return <span>Drawing available in the manual below.</span>;
    return <span className={styles.value}>{String(value)}</span>;
  }
  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index + 1), item] as const)
    : Object.entries(value);
  if (!entries.length)
    return <span className={styles.muted}>None returned</span>;
  return (
    <div className={styles.reply}>
      {entries.map(([key, item]) => {
        const complex = item !== null && typeof item === "object";
        return complex ? (
          <details key={key} open={depth < 1}>
            <summary>
              {label(key)}{" "}
              <small>
                {Array.isArray(item) ? `${item.length} items` : "Details"}
              </small>
            </summary>
            <Reply value={item} depth={depth + 1} />
          </details>
        ) : (
          <div className={styles.field} key={key}>
            <dt>{label(key)}</dt>
            <dd>
              <Reply value={item} depth={depth + 1} />
            </dd>
          </div>
        );
      })}
    </div>
  );
}

function UserFindings({ value }: { value: Value }) {
  const findings = new Set<string>();
  function visit(item: Value) {
    if (!item || typeof item !== "object") return;
    if (Array.isArray(item)) {
      item.forEach(visit);
      return;
    }
    for (const [key, child] of Object.entries(item)) {
      if (
        [
          "blockers",
          "questions",
          "explanation",
          "reason",
          "reasons",
          "missing_capabilities",
          "question",
          "unresolved_predicates",
        ].includes(key)
      ) {
        if (typeof child === "string") findings.add(child);
        if (Array.isArray(child)) {
          child.forEach((text) => {
            if (typeof text === "string") findings.add(text);
          });
        }
      }
      visit(child);
    }
  }
  visit(value);
  if (!findings.size) return null;
  return (
    <section aria-label="Questions and checks">
      <h3>Questions and checks</h3>
      <ul>
        {[...findings].slice(0, 12).map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </section>
  );
}

function panelsIn(value: Value): ManualPanel[] {
  if (!value || typeof value !== "object") return [];
  if (
    !Array.isArray(value) &&
    typeof value.svg === "string" &&
    typeof value.operation_id === "string"
  )
    return [value as unknown as ManualPanel];
  return Object.values(value).flatMap(panelsIn);
}

function statusText(status: string) {
  const labels: Record<string, string> = {
    needs_measurement: "Needs measurements",
    modeled_pass: "Modeled pass · synthetic",
    not_started: "Physical work not started",
    accepted: "Accepted by compiler",
    feasible: "Simulation feasible",
    candidates_found: "Options found",
  };
  if (labels[status]) return labels[status];
  if (status === "returned") return "Reply saved";
  if (["ok", "success", "passed", "completed"].includes(status))
    return "Reply saved";
  if (["blocked", "unsupported", "error", "failed"].includes(status))
    return "Needs attention";
  return label(status);
}

function SavedAssembly({ response }: { response: AssemblyViewResponse }) {
  const [camera, setCamera] = useState(initialCamera);
  const [part, setPart] = useState("");
  const geometry = response.geometry;
  if (!geometry?.facets.length) return null;
  const facets = projectFacets(geometry.facets, camera);
  const colors = ["#5c91bb", "#9bbdd4", "#cfdfeb"];
  const parts = [...new Set(facets.map((facet) => facet.part_id))];
  return (
    <section className={styles.assembly} aria-label="Saved assembly preview">
      <div>
        <p className={styles.eyebrow}>ENGINE-GENERATED GEOMETRY</p>
        <h3>Turn it around.</h3>
        <p>
          Inspect the planned shape and select a part. Rotation changes the view
          only.
        </p>
      </div>
      <svg
        viewBox="0 0 480 360"
        role="img"
        aria-label="Synthetic recipe-card stand assembly"
      >
        <path
          d="M30 285H450M240 36V330"
          stroke="#b8cbda"
          strokeDasharray="3 7"
        />
        {facets.map((facet) => (
          <polygon
            key={facet.facet_id}
            points={facet.points
              .map((point) => `${point.x},${point.y}`)
              .join(" ")}
            fill={
              part === facet.part_id
                ? "#edbe6a"
                : colors[parts.indexOf(facet.part_id) % colors.length]
            }
            stroke="#274e6e"
            strokeWidth="1.3"
            onClick={() => setPart(facet.part_id)}
          >
            <title>{facet.part_id}</title>
          </polygon>
        ))}
      </svg>
      <div className={styles.panelButtons}>
        {parts.map((id) => (
          <button
            key={id}
            aria-pressed={part === id}
            onClick={() => setPart(id)}
          >
            {id.replace("stand-", "")}
          </button>
        ))}
      </div>
      <label>
        Rotation{" "}
        <input
          type="range"
          min="-180"
          max="180"
          value={camera.yaw}
          onChange={(event) =>
            setCamera({ ...camera, yaw: Number(event.target.value) })
          }
        />
      </label>
      <label>
        Tilt{" "}
        <input
          type="range"
          min="-70"
          max="70"
          value={camera.pitch}
          onChange={(event) =>
            setCamera({ ...camera, pitch: Number(event.target.value) })
          }
        />
      </label>
      <button
        onClick={() => {
          setCamera(initialCamera);
          setPart("");
        }}
      >
        Reset view
      </button>
    </section>
  );
}

export default function PipelineWalkthrough() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [failure, setFailure] = useState("");
  const [current, setCurrent] = useState(0);
  const [panelIndex, setPanelIndex] = useState(0);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [noteStatus, setNoteStatus] = useState("");
  const titleRef = useRef<HTMLHeadingElement>(null);
  const railRef = useRef<HTMLElement>(null);
  const allSteps = useRef<Step[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/walkthrough/project.json", { signal: controller.signal })
      .then((response) => {
        if (!response.ok)
          throw new Error("The saved walkthrough could not be loaded.");
        return response.json() as Promise<Snapshot>;
      })
      .then((snapshot) => {
        if (controller.signal.aborted) return;
        if (snapshot.schema_version !== 1 || !snapshot.steps?.length)
          throw new Error("The saved walkthrough is incomplete.");
        allSteps.current = snapshot.steps;
        const index = snapshot.steps.findIndex(
          (step) => step.id === location.hash.slice(1),
        );
        setCurrent(index < 0 ? 0 : index);
        setData(snapshot);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setFailure(
            error instanceof Error
              ? error.message
              : "Could not load the walkthrough.",
          );
      });
    try {
      const stored: unknown = JSON.parse(
        localStorage.getItem("forma-walkthrough-notes-v1") ?? "{}",
      );
      if (stored && typeof stored === "object" && !Array.isArray(stored))
        setNotes(
          Object.fromEntries(
            Object.entries(stored).filter(
              ([, value]) => typeof value === "string",
            ),
          ),
        );
    } catch {
      /* Notes are optional when browser storage is unavailable. */
    }
    function restore() {
      const index = allSteps.current.findIndex(
        (step) => step.id === location.hash.slice(1),
      );
      setCurrent(Math.max(0, index));
      setPanelIndex(0);
    }
    window.addEventListener("popstate", restore);
    window.addEventListener("hashchange", restore);
    return () => {
      controller.abort();
      window.removeEventListener("popstate", restore);
      window.removeEventListener("hashchange", restore);
    };
  }, []);

  useEffect(() => {
    railRef.current
      ?.querySelector('[aria-current="step"]')
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [current]);

  function go(index: number) {
    if (!data || index < 0 || index >= data.steps.length) return;
    setCurrent(index);
    setPanelIndex(0);
    setNoteStatus("");
    history.pushState(null, "", `#${data.steps[index].id}`);
    titleRef.current?.focus();
    titleRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  const step = data?.steps[current];
  const panels = step ? panelsIn(step.output) : [];
  const selectedPanel = panels[Math.min(panelIndex, panels.length - 1)];

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <a href="/" aria-label="FORMA home" className="wordmark">
          <FormaWordmark />
        </a>
        <span>THE WHOLE PROJECT</span>
        <a href="/">Open your workbench ↗</a>
      </header>
      <div className={styles.hero}>
        <p className={styles.eyebrow}>
          A FILLED-IN PROJECT / SYNTHETIC EXAMPLE
        </p>
        <h1>
          A little stand.
          <br />
          The entire journey.
        </h1>
        <p>
          Explore a recipe-card stand from the first materials to the final
          review. Every stage is saved. Move freely, read the replies, and leave
          notes on what needs to feel better.
        </p>
        <div className={styles.notice}>
          <strong>Synthetic materials and assumptions.</strong> Engine replies
          come from the recorded run. Physical construction and testing remain
          unperformed. Browsing this project makes no AI requests.
        </div>
      </div>
      {failure && (
        <p role="alert">
          {failure}{" "}
          <button onClick={() => location.reload()}>Reload walkthrough</button>
        </p>
      )}
      {!data && !failure && <p role="status">Opening the saved project…</p>}
      {data && step && (
        <div className={styles.layout}>
          <nav
            ref={railRef}
            className={styles.rail}
            aria-label="Pipeline stages"
          >
            <p className={styles.eyebrow}>PROJECT JOURNEY</p>
            {data.steps.map((item, index) => (
              <button
                key={item.id}
                aria-current={index === current ? "step" : undefined}
                onClick={() => go(index)}
              >
                <span className={styles.number}>
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span>
                  {item.title}
                  <small>{statusText(item.result_status ?? item.status)}</small>
                </span>
              </button>
            ))}
            <DeveloperOnly>
              <a
                className={styles.download}
                href="/walkthrough/project.json"
                download="forma-synthetic-project.json"
              >
                Download all saved replies ↓
              </a>
            </DeveloperOnly>
          </nav>
          <article className={styles.stage}>
            <div className={styles.stageTop}>
              <span>
                STAGE {String(current + 1).padStart(2, "0")} /{" "}
                {data.steps.length}
              </span>
              <span className={styles.badge}>
                {statusText(step.result_status ?? step.status)}
              </span>
            </div>
            <h2 ref={titleRef} tabIndex={-1}>
              {step.title}
            </h2>
            {step.description && (
              <p className={styles.description}>{step.description}</p>
            )}
            {step.summary && <p className={styles.outcome}>{step.summary}</p>}
            <UserFindings value={step.output} />
            {step.error && <UserFindings value={step.error} />}
            <DeveloperOnly>
              <p className={styles.engine}>Run by {step.engine}</p>
            </DeveloperOnly>
            {step.id === "assembly-view" && (
              <SavedAssembly
                response={step.output as unknown as AssemblyViewResponse}
              />
            )}
            {step.image && (
              <figure className={styles.reference}>
                <img
                  src={step.image}
                  alt="Generated synthetic reference used for this stage"
                />
                <figcaption>Synthetic reference image</figcaption>
              </figure>
            )}
            <DeveloperOnly>
              <details
                key={step.id}
                className={styles.result}
                open={step.id.startsWith("muse-") || step.id.startsWith("sam-")}
                aria-label="Saved reply"
              >
                <summary>Read the saved reply</summary>
                <Reply value={step.output} />
                {step.error && (
                  <div role="note">
                    <h4>Why this stage needs attention</h4>
                    <Reply value={step.error} />
                  </div>
                )}
              </details>
            </DeveloperOnly>
            {selectedPanel && (
              <section className={styles.manual} aria-label="Assembly manual">
                <h3>The illustrated manual</h3>
                <div className={styles.panelButtons} aria-label="Manual steps">
                  {panels.map((panel, index) => (
                    <button
                      key={`${panel.operation_id}-${index}`}
                      aria-pressed={index === panelIndex}
                      onClick={() => setPanelIndex(index)}
                    >
                      {index + 1}
                    </button>
                  ))}
                </div>
                <h4>
                  Step {panelIndex + 1} of {panels.length}
                </h4>
                <p>{selectedPanel.instruction}</p>
                <Diagram panel={selectedPanel} />
                <div className={styles.pager}>
                  <button
                    disabled={panelIndex === 0}
                    onClick={() => setPanelIndex((value) => value - 1)}
                  >
                    ← Previous instruction
                  </button>
                  <button
                    disabled={panelIndex >= panels.length - 1}
                    onClick={() => setPanelIndex((value) => value + 1)}
                  >
                    Next instruction →
                  </button>
                </div>
              </section>
            )}
            <DeveloperOnly>
              <details className={styles.inspector}>
                <summary>Inspect the input and complete reply</summary>
                <h3>Input</h3>
                <pre>{JSON.stringify(step.input, null, 2)}</pre>
                <h3>Complete reply</h3>
                <pre>
                  {JSON.stringify(
                    {
                      status: step.status,
                      output: step.output,
                      ...(step.error ? { error: step.error } : {}),
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
              <section
                className={styles.notes}
                aria-label="Interaction review notes"
              >
                <label htmlFor="review-note">
                  What would you improve here?
                </label>
                <p>
                  Private notes stay in this browser. They survive moving
                  between stages and reloading.
                </p>
                <textarea
                  id="review-note"
                  rows={3}
                  maxLength={5000}
                  placeholder="For example: I don't understand what to do next…"
                  value={notes[step.id] ?? ""}
                  onChange={(event) => {
                    const next = { ...notes, [step.id]: event.target.value };
                    setNotes(next);
                    try {
                      localStorage.setItem(
                        "forma-walkthrough-notes-v1",
                        JSON.stringify(next),
                      );
                      setNoteStatus("Saved in this browser.");
                    } catch {
                      setNoteStatus(
                        "Browser storage unavailable; keep this page open or download your notes.",
                      );
                    }
                  }}
                />
                <p role="status">{noteStatus}</p>
                <button
                  onClick={() => {
                    const url = URL.createObjectURL(
                      new Blob(
                        [
                          JSON.stringify(
                            { project: data.label, notes },
                            null,
                            2,
                          ),
                        ],
                        { type: "application/json" },
                      ),
                    );
                    const anchor = document.createElement("a");
                    anchor.href = url;
                    anchor.download = "forma-interaction-notes.json";
                    anchor.click();
                    setTimeout(() => URL.revokeObjectURL(url), 1000);
                  }}
                >
                  Download my review notes
                </button>
              </section>
            </DeveloperOnly>
            <footer className={styles.pager}>
              <button disabled={current === 0} onClick={() => go(current - 1)}>
                ← Previous stage
              </button>
              <span>
                {current + 1} / {data.steps.length}
              </span>
              <button
                disabled={current === data.steps.length - 1}
                onClick={() => go(current + 1)}
              >
                Next stage →
              </button>
            </footer>
            {current === data.steps.length - 1 && (
              <section className={styles.end}>
                <h3>You’ve reached the final review.</h3>
                <p>
                  You can revisit any stage. The walkthrough is complete;
                  physical verification is still{" "}
                  {label(data.physical_verification).toLowerCase()}.
                </p>
                <button onClick={() => go(0)}>Back to the beginning ↺</button>
              </section>
            )}
          </article>
        </div>
      )}
      {data && (
        <footer className={styles.provenance}>
          <DeveloperOnly>
            <p>
              Saved {data.generated_at} · {data.provider_calls} recorded
              provider calls
              {data.source_head
                ? ` · Source ${data.source_head.slice(0, 8)}`
                : ""}
            </p>
            {data.actual_usage_totals && (
              <p>
                Provider-reported usage:{" "}
                {data.actual_usage_totals.input_tokens.toLocaleString()} input
                tokens ·{" "}
                {data.actual_usage_totals.output_tokens.toLocaleString()} output
                tokens · {data.actual_usage_totals.images_processed} SAM image.
                No monetary amount was reported.
              </p>
            )}
          </DeveloperOnly>
          <details>
            <summary>Scope and current limitations</summary>
            <ul>
              {data.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </details>
        </footer>
      )}
    </main>
  );
}
