"use client";
// Photo with an editable overlay. Coordinates are stored-media pixels.
import { useEffect, useRef, useState, type PointerEvent } from "react";
import { fetchPhoto } from "../../lib/api";
import { loadPhotoPreview } from "../../lib/photo-preview-loader";
import type { Media } from "../../lib/generated/api-contracts";
import type { Box, Point } from "./model";

export type Mode =
  | { kind: "view" }
  | { kind: "box"; onBox: (box: Box) => void }
  | { kind: "add-points"; limit: number; onAdd: (p: Point) => void };

export default function PhotoCanvas({
  token,
  projectId,
  photo,
  label,
  box,
  outline,
  reference,
  editable,
  onMove,
  mode,
}: {
  token: string;
  projectId: string;
  photo: Media;
  label: string;
  box?: Box | null;
  outline?: readonly Point[];
  reference?: readonly Point[];
  // Which point list the handles edit, if any.
  editable?: "outline" | "reference" | null;
  onMove?: (index: number, point: Point) => void;
  mode: Mode;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [draft, setDraft] = useState<Box | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    let dispose: (() => void) | undefined;
    setUrl(null);
    setFailed(false);
    void loadPhotoPreview(
      () => fetchPhoto(token, projectId, photo.id, controller.signal),
      controller.signal,
    )
      .then((preview) => {
        if (controller.signal.aborted) return preview.dispose();
        dispose = preview.dispose;
        setUrl(preview.url);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => {
      controller.abort();
      dispose?.();
    };
  }, [token, projectId, photo.id, attempt]);

  const w = photo.width_px;
  const h = photo.height_px;
  const handle = Math.max(w, h) / 90;
  function toImage(
    event: PointerEvent<SVGSVGElement | SVGCircleElement>,
  ): Point {
    const rect = svg.current!.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * w;
    const y = ((event.clientY - rect.top) / rect.height) * h;
    return {
      x: Math.min(w - 1, Math.max(0, x)),
      y: Math.min(h - 1, Math.max(0, y)),
    };
  }
  const points = editable === "reference" ? reference : outline;

  return (
    <div className="guided-canvas">
      {url ? (
        <div
          className="guided-canvas-frame"
          style={{ aspectRatio: `${w} / ${h}` }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={url} alt={label} />
          <svg
            ref={svg}
            viewBox={`0 0 ${w} ${h}`}
            preserveAspectRatio="none"
            className={mode.kind === "view" ? "" : "drawing"}
            aria-hidden={mode.kind === "view" && !editable}
            onPointerDown={(event) => {
              if (mode.kind === "box") {
                const p = toImage(event);
                svg.current?.setPointerCapture(event.pointerId);
                setDraft({ x1: p.x, y1: p.y, x2: p.x, y2: p.y });
              } else if (mode.kind === "add-points") {
                mode.onAdd(toImage(event));
              }
            }}
            onPointerMove={(event) => {
              if (mode.kind === "box" && draft) {
                const p = toImage(event);
                setDraft({ ...draft, x2: p.x, y2: p.y });
              } else if (dragging !== null && onMove) {
                onMove(dragging, toImage(event));
              }
            }}
            onPointerUp={() => {
              if (mode.kind === "box" && draft) {
                mode.onBox(draft);
                setDraft(null);
              }
              setDragging(null);
            }}
          >
            {reference && reference.length > 0 && (
              <polygon
                className="overlay-reference"
                points={reference
                  .slice(0, 4)
                  .map((p) => `${p.x},${p.y}`)
                  .join(" ")}
              />
            )}
            {(draft ?? box) && (
              <rect
                className="overlay-box"
                x={Math.min((draft ?? box)!.x1, (draft ?? box)!.x2)}
                y={Math.min((draft ?? box)!.y1, (draft ?? box)!.y2)}
                width={Math.abs((draft ?? box)!.x2 - (draft ?? box)!.x1)}
                height={Math.abs((draft ?? box)!.y2 - (draft ?? box)!.y1)}
              />
            )}
            {outline && outline.length > 2 && (
              <polygon
                className="overlay-outline"
                points={outline.map((p) => `${p.x},${p.y}`).join(" ")}
              />
            )}
            {editable &&
              points?.map((p, index) => (
                <circle
                  key={index}
                  className="overlay-handle"
                  cx={p.x}
                  cy={p.y}
                  r={handle}
                  tabIndex={0}
                  role="slider"
                  aria-label={`${editable === "reference" ? "Reference corner" : "Outline point"} ${index + 1}. Arrow keys move it; hold Shift for larger steps.`}
                  aria-valuetext={`${Math.round(p.x)}, ${Math.round(p.y)} pixels`}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    svg.current?.setPointerCapture(event.pointerId);
                    setDragging(index);
                  }}
                  onKeyDown={(event) => {
                    const step = event.shiftKey ? 10 : 1;
                    const move: Record<string, [number, number]> = {
                      ArrowLeft: [-step, 0],
                      ArrowRight: [step, 0],
                      ArrowUp: [0, -step],
                      ArrowDown: [0, step],
                    };
                    const delta = move[event.key];
                    if (!delta || !onMove) return;
                    event.preventDefault();
                    onMove(index, {
                      x: Math.min(w - 1, Math.max(0, p.x + delta[0])),
                      y: Math.min(h - 1, Math.max(0, p.y + delta[1])),
                    });
                  }}
                />
              ))}
          </svg>
        </div>
      ) : failed ? (
        <button
          type="button"
          className="secondary"
          onClick={() => setAttempt((v) => v + 1)}
        >
          Retry photo
        </button>
      ) : (
        <p className="help">Loading photo…</p>
      )}
    </div>
  );
}
