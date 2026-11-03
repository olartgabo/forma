"use client";

import { useEffect, useState } from "react";
import FormaWordmark from "./forma-wordmark";
import styles from "./forma-loader.module.css";

const shutters = [0, 1, 2, 3, 4, 5, 6];

export default function FormaLoader() {
  const [phase, setPhase] = useState<"waiting" | "playing" | "done">("waiting");

  useEffect(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduceMotion.matches) {
      setPhase("done");
      return;
    }
    setPhase("playing");
    const fallback = window.setTimeout(() => setPhase("done"), 2000);
    return () => window.clearTimeout(fallback);
  }, []);

  if (phase === "done") return null;

  return (
    <div
      className={styles.loader}
      data-playing={phase === "playing" || undefined}
      aria-hidden="true"
      onAnimationEnd={(event) => {
        if (event.target === event.currentTarget) setPhase("done");
      }}
    >
      <div className={styles.shutters}>
        {shutters.map((index) => (
          <div key={index} className={styles.shutter} />
        ))}
      </div>
      <div className={styles.artwork}>
        <div className={styles.mark}>
          <FormaWordmark />
        </div>
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
        <svg
          className={styles.registration}
          viewBox="0 0 400 240"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <path
            d="M2 18V2h16m364 0h16v16M2 222v16h16m364 0h16v-16M194 2h12m-6 0v8m-6 228h12m-6 0v-8m47-34 8-8m-5 15h12m-15 6 8 8"
            fill="none"
            stroke="currentColor"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
    </div>
  );
}
