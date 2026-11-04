import { useState } from "react";
import type { workbenchCopy } from "../lib/workbench-language";
import styles from "./stand-preview.module.css";

const faces = ["top", "bottom", "left", "right", "front", "rear"] as const;

export default function StandPreview({
  copy,
}: {
  copy: typeof workbenchCopy.en;
}) {
  const [back, setBack] = useState(false);
  return (
    <figure className={styles.preview}>
      <figcaption className={styles.caption}>
        <strong>{copy.stand}</strong>
        <span>{copy.example}</span>
      </figcaption>
      <div className={styles.viewport} aria-hidden="true">
        <svg className={styles.guides} viewBox="0 0 100 62">
          <path d="M5 9V5h4m82 0h4v4M5 53v4h4m82 0h4v-4" />
          <path
            d="M6 20h88M6 40h88M27 5v52M50 5v52M73 5v52"
            strokeDasharray="0.3 0.65"
            opacity=".5"
          />
          <path
            d="M10 57h80"
            strokeWidth="1.1"
            strokeDasharray="0.12 1.13"
            opacity=".55"
          />
        </svg>
        <div className={styles.turntable} data-back={back}>
          {["base", "support", "brace", "lip"].map((panel) => (
            <div className={styles.panel} data-panel={panel} key={panel}>
              {faces.map((face) => (
                <span key={face} data-face={face} />
              ))}
            </div>
          ))}
        </div>
        <svg className={styles.callouts} viewBox="0 0 100 62">
          <path d="M15 19h7l13 8M87 43h-5l-10 8" />
          <circle cx="35" cy="27" r=".42" />
          <circle cx="72" cy="51" r=".42" />
          <text x="9" y="20">
            {back ? "02" : "01"}
          </text>
          <text x="88" y="44">
            03
          </text>
        </svg>
      </div>
      <div className={styles.views} role="group" aria-label={copy.stand}>
        <button
          type="button"
          aria-pressed={!back}
          onClick={() => setBack(false)}
        >
          {copy.front}
        </button>
        <button type="button" aria-pressed={back} onClick={() => setBack(true)}>
          {copy.back}
        </button>
      </div>
      <ul className={styles.legend} aria-label={copy.stand}>
        {copy.parts.map((part, index) => (
          <li key={part}>
            <span>0{index + 1}</span> {part}
          </li>
        ))}
      </ul>
    </figure>
  );
}
