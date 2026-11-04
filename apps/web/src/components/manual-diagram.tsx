import { useEffect, useState } from "react";
import type { ManualPanel } from "../lib/generated/api-contracts";

export default function Diagram({ panel }: { panel: ManualPanel }) {
  const [drawing, setDrawing] = useState<{ svg: string; url: string } | null>(
    null,
  );
  const [enlarged, setEnlarged] = useState(false);
  const [blueprint, setBlueprint] = useState(true);
  useEffect(() => {
    const next = URL.createObjectURL(
      new Blob([panel.svg], { type: "image/svg+xml" }),
    );
    setDrawing({ svg: panel.svg, url: next });
    return () => URL.revokeObjectURL(next);
  }, [panel.svg]);
  return drawing?.svg === panel.svg ? (
    <figure className="drawing-sheet">
      <div className="drawing-sheet-title">
        <strong>Assembly drawing</strong>
        <span>{panel.operation_id}</span>
      </div>
      <div className="drawing-sheet-ticks" aria-hidden="true" />
      <div className="drawing-sheet-tools">
        <button
          type="button"
          aria-pressed={blueprint}
          onClick={() => setBlueprint((value) => !value)}
        >
          Blueprint colors
        </button>
        <a href={drawing.url} download={`${panel.operation_id}.svg`}>
          Download SVG
        </a>
        <button
          type="button"
          aria-expanded={enlarged}
          onClick={() => setEnlarged((value) => !value)}
        >
          {enlarged ? "Fit diagram to screen" : "Enlarge diagram"}
        </button>
      </div>
      {enlarged && (
        <p className="diagram-pan-cue" id={`${panel.operation_id}-pan-cue`}>
          The full drawing is wider than the screen. Swipe or scroll sideways to
          see every dimension; with a keyboard, focus the drawing and use the
          arrow keys.
        </p>
      )}
      <div
        className={`manual-diagram-frame${enlarged ? " enlarged" : ""}${blueprint ? " blueprint" : ""}`}
        tabIndex={enlarged ? 0 : undefined}
        role={enlarged ? "region" : undefined}
        aria-label={
          enlarged
            ? "Full-size diagram; scroll to inspect dimensions"
            : undefined
        }
        aria-describedby={
          enlarged ? `${panel.operation_id}-pan-cue` : undefined
        }
      >
        <img
          className="manual-diagram"
          src={drawing.url}
          alt={`Assembly diagram for ${panel.operation_id}. ${panel.instruction}`}
        />
      </div>
    </figure>
  ) : (
    <p>Loading diagram…</p>
  );
}
