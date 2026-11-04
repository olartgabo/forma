"use client";

import { useEffect, useState, type CSSProperties } from "react";
import styles from "./cube-loader.module.css";

const showAfterMs = 10_000;
const finishDurationMs = 800;

const faces = [
  { name: "front", axis: 2, side: 1 },
  { name: "back", axis: 2, side: -1 },
  { name: "right", axis: 0, side: 1 },
  { name: "left", axis: 0, side: -1 },
  { name: "top", axis: 1, side: -1 },
  { name: "bottom", axis: 1, side: 1 },
] as const;

type Position = readonly [number, number, number];
const coordinates = [-1, 0, 1];
const cubies = coordinates.flatMap((x) =>
  coordinates.flatMap((y) =>
    coordinates
      .filter((z) => x !== 0 || y !== 0 || z !== 0)
      .map((z) => makeCubie([x, y, z])),
  ),
);

function makeCubie(position: Position) {
  const [x, y, z] = position;

  // Scramble the right, top and front layers in that order. Each turn
  // changes which cubies are in the next layer.
  const turnX = x === 1;
  const afterX: Position = turnX ? [x, -z, y] : position;
  const turnY = afterX[1] === -1;
  const afterY: Position = turnY ? [afterX[2], afterX[1], -afterX[0]] : afterX;
  const turnZ = afterY[2] === 1;

  // Keep the transform lists in the same order so CSS can undo each turn
  // around the cube's center, including the cubie's translated position.
  const pose = (rx: boolean, ry: boolean, rz: boolean) =>
    `rotateZ(${rz ? 90 : 0}deg) rotateY(${ry ? 90 : 0}deg) rotateX(${rx ? 90 : 0}deg) translate3d(${x * 20}px, ${y * 20}px, ${z * 20}px)`;

  return {
    id: position.join(","),
    style: {
      "--scrambled": pose(turnX, turnY, turnZ),
      "--front-undone": pose(turnX, turnY, false),
      "--top-undone": pose(turnX, false, false),
      "--solved": pose(false, false, false),
    } as CSSProperties,
    faces: faces.map(({ name, axis, side }) => ({
      name,
      sticker: position[axis] === side,
    })),
  };
}

export default function CubeLoader({
  busy,
  succeeded,
}: {
  busy: boolean;
  succeeded: boolean;
}) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (busy) {
      setVisible(false);
      const timer = window.setTimeout(() => setVisible(true), showAfterMs);
      return () => window.clearTimeout(timer);
    }
    if (succeeded) {
      const timer = window.setTimeout(
        () => setVisible(false),
        finishDurationMs,
      );
      return () => window.clearTimeout(timer);
    }
    setVisible(false);
  }, [busy, succeeded]);

  if (!visible || (!busy && !succeeded)) return null;

  return (
    <div
      className={styles.loader}
      style={{ "--finish-duration": `${finishDurationMs}ms` } as CSSProperties}
      data-cube-state={busy ? "waiting" : "solving"}
      aria-hidden="true"
    >
      <div className={styles.cube}>
        {cubies.map((cubie) => (
          <div key={cubie.id} className={styles.cubie} style={cubie.style}>
            {cubie.faces.map(({ name, sticker }) => (
              <span
                key={name}
                className={`${styles.face} ${styles[name]}`}
                data-sticker={sticker ? "" : undefined}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
