import { useEffect, useState } from "react";
import type { ManualPanel } from "../lib/generated/api-contracts";

export default function Diagram({ panel }: { panel: ManualPanel }) {
  const [url, setUrl] = useState<string | null>(null);
  const [enlarged, setEnlarged] = useState(false);
  useEffect(() => {
    const next = URL.createObjectURL(
      new Blob([panel.svg], { type: "image/svg+xml" }),
    );
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [panel.svg]);
  return url ? (
    <>
      <button
        type="button"
        className="quiet"
        aria-expanded={enlarged}
        onClick={() => setEnlarged((value) => !value)}
      >
        {enlarged ? "Fit diagram to screen" : "Enlarge diagram"}
      </button>
      <div
        className={`manual-diagram-frame${enlarged ? " enlarged" : ""}`}
        tabIndex={enlarged ? 0 : undefined}
        role={enlarged ? "region" : undefined}
        aria-label={
          enlarged
            ? "Full-size diagram; scroll to inspect dimensions"
            : undefined
        }
      >
        <img
          className="manual-diagram"
          src={url}
          alt={`Assembly diagram for ${panel.operation_id}. ${panel.instruction}`}
        />
      </div>
    </>
  ) : (
    <p>Loading diagram…</p>
  );
}
