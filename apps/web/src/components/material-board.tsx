"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { RecognizedItem, Stock } from "../lib/generated/contracts";
import { materialArt, toolArt } from "../lib/material-art";
import styles from "./material-board.module.css";
import CubeLoader from "./cube-loader";

type Entry = {
  id: string;
  name: string;
  target: string;
  art: ReturnType<typeof materialArt>;
  tool?: boolean;
};

// Visual anchors for the supplied narrow tool cutouts, not measured geometry.
function leaderEndpoint(entry: Entry, compact: boolean) {
  if (entry.art?.label === "Scissors") return compact ? 100 : 70;
  if (entry.art?.label === "Utility knife") return compact ? 90 : 75;
  if (entry.art?.label === "Duct tape") return 22;
  return 43;
}

function Cutout({ entry }: { entry: Entry }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [entry.art?.src]);
  return entry.art && !failed ? (
    <img
      src={entry.art.src}
      alt=""
      width="720"
      height="720"
      decoding="async"
      onError={() => setFailed(true)}
    />
  ) : (
    <span className={styles.unknown} aria-hidden="true">
      ?
    </span>
  );
}

export default function MaterialBoard({
  items,
  stocks,
  tools = [],
  status,
  designReady = false,
  designBusy = false,
  onReview,
}: {
  items: readonly RecognizedItem[];
  stocks: readonly Stock[];
  tools?: readonly string[];
  status: string | null;
  designReady?: boolean;
  designBusy?: boolean;
  onReview: (target?: string) => void;
}) {
  const board = useRef<HTMLElement>(null);
  useEffect(() => {
    if (designBusy) board.current?.scrollIntoView({ block: "start" });
  }, [designBusy]);
  const [compact, setCompact] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 600px)");
    const sync = () => setCompact(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);
  const entries: Entry[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    const category =
      item.identity.outcome === "catalog" ? item.identity.category_id : null;
    const group = category || item.id;
    if (seen.has(group)) continue;
    seen.add(group);
    entries.push({
      id: `item-${item.id}`,
      name: item.name,
      target: `item-${item.id}`,
      art: category ? materialArt(category) : null,
    });
  }
  for (const stock of stocks) {
    if (items.some((item) => item.stock_id === stock.id)) continue;
    // Generic tape has no known subtype. Never illustrate it as confirmed duct tape.
    const category =
      stock.material === "cardboard"
        ? "corrugated_cardboard"
        : stock.material === "paperboard"
          ? "thin_packaging_card"
          : stock.kind === "cord"
            ? "string_twine"
            : null;
    if (category && seen.has(category)) continue;
    if (category) seen.add(category);
    entries.push({
      id: `stock-${stock.id}`,
      name: stock.name || stock.material,
      target: `card-${stock.id}`,
      art: category ? materialArt(category) : null,
    });
  }
  for (const name of new Set(tools))
    entries.push({
      id: `tool-${name}`,
      name,
      target: "tools",
      art: toolArt(name),
      tool: true,
    });
  const shown = entries.slice(0, compact ? 3 : 6);
  return (
    <section
      ref={board}
      className={styles.board}
      aria-label="Your materials so far"
    >
      <header className={styles.header}>
        <svg
          className={styles.cat}
          viewBox="320 264 280 254"
          aria-hidden="true"
        >
          <path
            fill="currentColor"
            fillRule="evenodd"
            d="M350 369 397 272 459 322 520 266 548 332 514 335 506 344 511 350 502 352 493 336 451 341 408 303 383 360 390 382 428 350 443 380 459 387 502 379 512 369 520 380 531 384 585 374 581 387 564 391 575 412 592 420 579 481 462 515 369 496 380 470 338 470 364 437 326 421 365 396Z M401 476 463 496 565 467 573 430 556 419 546 393 527 394 511 384 502 395 450 403 434 395 425 382 377 418 399 427 382 448 411 451Z"
          />
          <path
            fill="currentColor"
            d="m443 354 40-7 11 18-4 6-36 5zm78-9 39-4 10 18-3 6-33 4-7-6z"
          />
          <path
            fill="none"
            stroke="currentColor"
            strokeWidth="8"
            d="M462 441q16-26 35-6m28-1q14-26 31-7m-73 24q10 18 23 5l6-10q11 19 23 4l3-8m-113 11 39-3m-35 21 36-10m88-22 24-5m-23 15 20 1"
          />
        </svg>
        <div>
          <p className={styles.eyebrow}>FORMA / MATERIAL STUDY</p>
          <h3>
            Your materials
            <br />
            so far…
          </h3>
        </div>
      </header>
      <div className={styles.status} role="status">
        {status ||
          (entries.length
            ? "A starting point. Make it yours."
            : "Your next idea starts with what you have.")}
      </div>
      <CubeLoader
        busy={Boolean(status)}
        succeeded={!status && entries.length > 0}
      />
      {shown.length ? (
        <div
          className={styles.collage}
          data-count={shown.length}
          style={{ "--count": shown.length } as CSSProperties}
        >
          {shown.map((entry, index) => (
            <button
              type="button"
              className={styles.cutout}
              data-slot={index}
              data-selected={selected === entry.id || undefined}
              style={
                {
                  "--tilt": `${shown.length === 1 ? 0 : -14 + (28 * index) / (shown.length - 1)}deg`,
                } as CSSProperties
              }
              key={entry.id}
              onClick={() => {
                setSelected(entry.id);
                onReview(entry.target);
              }}
              aria-label={`Review ${entry.name}`}
            >
              <Cutout entry={entry} />
              <svg
                className={styles.leader}
                viewBox="0 0 100 100"
                aria-hidden="true"
              >
                <path d={`M8 8 H64 L${leaderEndpoint(entry, compact)} 83`} />
                <circle cx={leaderEndpoint(entry, compact)} cy="83" r="3" />
              </svg>
              <span className={styles.label}>{entry.name}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className={styles.empty}>
          {status
            ? "We’ll pin the results here when they arrive."
            : "Add a photo or a material below to start your board."}
        </div>
      )}
      <footer className={styles.footer}>
        <span className={styles.note}>
          {entries.length
            ? "Tap an object to check it ↗"
            : "Nothing spotted yet ↗"}
        </span>
        <button
          type="button"
          onClick={() => onReview()}
          className={styles.review}
        >
          See all & edit materials →
          {entries.length > shown.length && (
            <small> +{entries.length - shown.length} more on your board</small>
          )}
        </button>
      </footer>
      {designReady && (
        <button
          type="button"
          className={styles.design}
          onClick={() => onReview("design")}
        >
          View your design →
        </button>
      )}
      <p className={styles.caption}>
        Representative pictures. Check the suggestions; sizes and quantities
        still need your confirmation.
      </p>
    </section>
  );
}
