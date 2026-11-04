import { useId } from "react";

export function WorkshopIcon({ index }: { index: number }) {
  const paths = [
    "M3 11 12 3l9 8M5 10v11h5v-7h4v7h5V10",
    "m3 8 9-5 9 5-9 5zM3 12l9 5 9-5M3 16l9 5 9-5",
    "m3 12 12-9 6 4-12 9H3zM3 12v6h6l12-9V7M9 16v2M3 21h7l11-9",
    "M2 4h3l3 12h11l3-9H6M9 21h.01M18 21h.01",
    "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Zm5-15-3 7-7 3 3-7z",
  ];
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[index]} />
    </svg>
  );
}

type Point = readonly [number, number, number];
type Finish = { face: string; edge: string; grain: string };
// One orthographic camera for all decorative models: x right, y away, z up.
// These are presentation concepts, never compiled geometry or cutting instructions.
const project = ([x, y, z]: Point) => [
  +(x * 0.88 + y * 0.58).toFixed(1),
  +(x * 0.3 - y * 0.38 - z).toFixed(1),
];
const add = (a: Point, b: Point): Point => [
  a[0] + b[0],
  a[1] + b[1],
  a[2] + b[2],
];
function outline(points: readonly Point[], radius = 2) {
  const p = points.map(project);
  const near = (a: number[], b: number[]) => {
    const t = Math.min(0.18, radius / Math.hypot(b[0] - a[0], b[1] - a[1]));
    return `${(a[0] + (b[0] - a[0]) * t).toFixed(1)},${(a[1] + (b[1] - a[1]) * t).toFixed(1)}`;
  };
  return (
    p
      .map(
        (v, i) =>
          `${i ? "L" : "M"}${near(v, p[(i + p.length - 1) % p.length])}Q${v.join(",")} ${near(v, p[(i + 1) % p.length])}`,
      )
      .join("") + "Z"
  );
}

/** A solid sheet: the same vertices produce its face, thickness and edge laminations. */
function Board({
  points,
  thickness,
  finish,
  grain = true,
}: {
  points: readonly Point[];
  thickness: Point;
  finish: Finish;
  grain?: boolean;
}) {
  const back = points.map((p) => add(p, thickness));
  const face = outline(points);
  const faceId = useId().replace(/:/g, "");
  return (
    <g stroke="#c8eeff" strokeWidth="1.2" strokeLinejoin="round">
      {points.map((p, i) => {
        const j = (i + 1) % points.length;
        const half: Point = [
          thickness[0] / 2,
          thickness[1] / 2,
          thickness[2] / 2,
        ];
        const mid = [add(p, half), add(points[j], half)];
        const corners = [p, points[j], back[j], back[i]].map(project);
        // Back-face culling avoids transparent-looking internal/hidden edge lines.
        const area = corners.reduce((sum, v, k) => {
          const next = corners[(k + 1) % corners.length];
          return sum + v[0] * next[1] - next[0] * v[1];
        }, 0);
        if (area <= 0) return null;
        return (
          <g key={i}>
            <polygon
              points={corners.map((v) => v.join(",")).join(" ")}
              fill={finish.edge}
            />
            <path
              d={`M${project(mid[0]).join(",")}L${project(mid[1]).join(",")}`}
              stroke="#82c7fb"
              strokeWidth=".55"
              opacity=".65"
            />
          </g>
        );
      })}
      <defs>
        <path id={faceId} d={face} />
      </defs>
      <use href={`#${faceId}`} fill={finish.face} />
      {grain && (
        <use
          href={`#${faceId}`}
          fill={finish.grain}
          stroke="none"
          opacity=".17"
        />
      )}
    </g>
  );
}

const top = (
  x: number,
  y: number,
  z: number,
  w: number,
  d: number,
): Point[] => [
  [x, y, z],
  [x + w, y, z],
  [x + w, y + d, z],
  [x, y + d, z],
];
const front = (
  x: number,
  y: number,
  z: number,
  w: number,
  h: number,
): Point[] => [
  [x, y, z],
  [x + w, y, z],
  [x + w, y, z + h],
  [x, y, z + h],
];
const side = (
  x: number,
  y: number,
  z: number,
  d: number,
  h: number,
): Point[] => [
  [x, y, z],
  [x, y + d, z],
  [x, y + d, z + h],
  [x, y, z + h],
];
const deck: Point[] = [
  [0, 9, 25],
  [110, 9, 25],
  [110, 62, 153],
  [0, 62, 153],
];
const brace = (x: number): Point[] => [
  [x, 16, 7],
  [x, 78, 7],
  [x, 78, 138],
  [x, 62, 153],
  [x, 9, 25],
];

function Peg({ point }: { point: Point }) {
  const [cx, cy] = project(point);
  return (
    <g stroke="#e2f8ff" strokeWidth=".85">
      <ellipse cx={cx} cy={cy} rx="1.7" ry="2" fill="#145eaa" />
      <path d={`M${cx - 0.8} ${cy}h1.6`} />
    </g>
  );
}

function Stand({
  finish,
  exploded = false,
}: {
  finish: Finish;
  exploded?: boolean;
}) {
  return (
    <>
      <Board
        points={top(-5, 0, 7, 120, 83)}
        thickness={[0, 0, -7]}
        finish={finish}
      />
      <Board points={brace(16)} thickness={[-6, 0, 0]} finish={finish} />
      <Board points={deck} thickness={[0, 5, -2]} finish={finish} />
      <Board
        points={brace(104)}
        thickness={[-6, 0, 0]}
        finish={{ ...finish, face: finish.edge }}
      />
      <Board
        points={top(-4, -5, 27, 118, 23)}
        thickness={[0, 0, -7]}
        finish={finish}
      />
      {/* A continuous retaining rail with a centered cable opening. */}
      <Board
        points={[
          [-4, -5, 27],
          [43, -5, 27],
          [43, -5, 18],
          [67, -5, 18],
          [67, -5, 27],
          [114, -5, 27],
          [114, -5, 39],
          [-4, -5, 39],
        ]}
        thickness={[0, 6, 0]}
        finish={finish}
      />
      <Peg point={[104, 68, 24]} />
      <Peg point={[104, 68, 123]} />
      {exploded && (
        <g transform="translate(211 -35) scale(.54)">
          <g
            stroke="#a7dbff"
            strokeWidth="1"
            opacity=".65"
            strokeDasharray="4 5"
            fill="none"
          >
            <path d="M35-106V41M132-75V74M35 41l97 33" />
          </g>
          <g transform="translate(0 -32)">
            <Board points={deck} thickness={[0, 5, -2]} finish={finish} />
            <Peg point={[12, 14, 38]} />
            <Peg point={[98, 14, 38]} />
          </g>
          <g transform="translate(-19 10)">
            <Board points={brace(16)} thickness={[-6, 0, 0]} finish={finish} />
            <Peg point={[16, 68, 24]} />
            <Peg point={[16, 68, 123]} />
          </g>
          <g transform="translate(44 20)">
            <Board points={brace(104)} thickness={[-6, 0, 0]} finish={finish} />
            <Peg point={[104, 68, 24]} />
            <Peg point={[104, 68, 123]} />
          </g>
          <g transform="translate(0 52)">
            <Board
              points={top(-5, 0, 7, 120, 83)}
              thickness={[0, 0, -7]}
              finish={finish}
            />
          </g>
          <g transform="translate(-6 98)">
            <Board
              points={front(-4, -5, 27, 118, 12)}
              thickness={[0, 6, 0]}
              finish={finish}
            />
          </g>
        </g>
      )}
    </>
  );
}

function Organizer({ finish }: { finish: Finish }) {
  // Continuous bottom and back; full-depth partitions meet the bottom and back.
  const wall = (x: number): Point[] => [
    [x, 0, 7],
    [x, 86, 7],
    [x, 86, 91],
    [x, 57, 91],
    [x, 50, 83],
    [x, 50, 43],
    [x, 0, 43],
  ];
  return (
    <>
      <Board
        points={front(0, 86, 7, 158, 84)}
        thickness={[0, 6, 0]}
        finish={finish}
      />
      <Board
        points={top(0, 0, 7, 164, 92)}
        thickness={[0, 0, -7]}
        finish={finish}
      />
      <Board points={wall(6)} thickness={[-6, 0, 0]} finish={finish} />
      <Board points={wall(58)} thickness={[-5, 0, 0]} finish={finish} />
      <Board points={wall(109)} thickness={[-5, 0, 0]} finish={finish} />
      <Board
        points={wall(164)}
        thickness={[-6, 0, 0]}
        finish={{ ...finish, face: finish.edge }}
      />
      <Board
        points={front(0, 0, 7, 164, 30)}
        thickness={[0, 6, 0]}
        finish={finish}
      />
      {/* Small flush end-grain finger joints on the visible front corners. */}
      {[0, 158].map((x) => (
        <g key={x} stroke="#e5f8ff" strokeWidth="1" fill={finish.edge}>
          {[12, 25].map((z) => (
            <path key={z} d={outline(front(x, -0.15, z, 6, 5), 0.4)} />
          ))}
        </g>
      ))}
    </>
  );
}

function Materials({ finish }: { finish: Finish }) {
  return (
    <>
      {[0, 1, 2].map((n) => (
        <Board
          key={n}
          points={top(n * 7, n * 7, n * 17, 176 - n * 9, 105 - n * 10)}
          thickness={[0, 0, -8]}
          finish={finish}
        />
      ))}
    </>
  );
}

function Riser({ finish }: { finish: Finish }) {
  return (
    <>
      <Board
        points={side(14, 7, 0, 70, 61)}
        thickness={[-7, 0, 0]}
        finish={finish}
      />
      <Board
        points={front(14, 72, 13, 157, 34)}
        thickness={[0, 6, 0]}
        finish={finish}
      />
      <Board
        points={side(171, 7, 0, 70, 61)}
        thickness={[-7, 0, 0]}
        finish={finish}
      />
      <Board
        points={top(0, 0, 68, 186, 88)}
        thickness={[0, 0, -7]}
        finish={finish}
      />
    </>
  );
}

function Repair({ finish }: { finish: Finish }) {
  return (
    <g
      stroke="#d7f4ff"
      strokeWidth="1.6"
      strokeLinejoin="round"
      strokeLinecap="round"
    >
      <g transform="rotate(-35 170 120)">
        <path
          d="M154 93c-17-8-24-30-15-47l9 21 17 5 14-11-3-23c23 11 29 37 12 55l-3 92a15 15 0 0 1-30 0z"
          fill={finish.edge}
          transform="translate(4 4)"
        />
        <path
          d="M154 93c-17-8-24-30-15-47l9 21 17 5 14-11-3-23c23 11 29 37 12 55l-3 92a15 15 0 0 1-30 0z"
          fill={finish.face}
        />
        <path d="m163 104 1 66M146 80q15 16 32 1" opacity=".6" />
        <circle cx="170" cy="185" r="5" fill="#175ea7" />
      </g>
      <g transform="rotate(36 239 129)">
        <path d="M233 40h12l-2 19h-8zM235 58h8v82h-8z" fill="#9bd9ff" />
        <path d="M224 133h30v12h-30z" fill={finish.edge} />
        <path d="M224 145h30l4 11-3 48q-16 13-32 0l-3-48z" fill={finish.face} />
        <path d="M230 157v39M239 158v42M248 157v39" opacity=".65" />
      </g>
    </g>
  );
}

/** Decorative concept models only; never project geometry or cutting instructions. */
export default function WorkshopIllustration({
  kind = "stand",
  variant = "card",
}: {
  kind?: "stand" | "materials" | "repair" | "idea" | "riser";
  variant?: "hero" | "card";
}) {
  const id = useId().replace(/:/g, "");
  const finish = {
    face: `url(#${id}-face)`,
    edge: `url(#${id}-edge)`,
    grain: `url(#${id}-grain)`,
  };
  const hero = variant === "hero" && kind === "stand";
  const cardFrames = {
    stand: "86 -16 292 303",
    idea: "58 28 260 220",
    materials: "55 74 272 164",
    repair: "87 34 224 180",
    riser: "58 55 278 192",
  };
  return (
    <svg
      viewBox={hero ? "0 0 420 270" : cardFrames[kind]}
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={`${id}-face`} x1="0" y1="0" x2=".85" y2="1">
          <stop stopColor="#62b7fa" />
          <stop offset=".5" stopColor="#3189df" />
          <stop offset="1" stopColor="#2071c7" />
        </linearGradient>
        <linearGradient id={`${id}-edge`} x2="0" y2="1">
          <stop stopColor="#2f8edc" />
          <stop offset="1" stopColor="#1258a4" />
        </linearGradient>
        <pattern
          id={`${id}-grain`}
          width="83"
          height="110"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(20)"
        >
          <g stroke="#c1ecff" strokeWidth=".65" fill="none">
            <path d="M2-5C-6 30 15 64 3 115M18-5C0 30 30 74 19 115M40-5C21 30 54 74 41 115M61-5C42 30 74 74 62 115M81-5C62 30 94 74 82 115" />
            <ellipse cx="42" cy="55" rx="5" ry="22" />
            <ellipse cx="42" cy="55" rx="1.8" ry="11" />
          </g>
        </pattern>
      </defs>
      {kind === "repair" ? (
        <Repair finish={finish} />
      ) : (
        <g
          transform={
            hero
              ? "translate(28 220) scale(1.1)"
              : kind === "stand"
                ? "translate(119 220) scale(1.25)"
                : kind === "materials"
                  ? "translate(85 159) scale(1.05)"
                  : "translate(89 179) scale(1.08)"
          }
        >
          {kind === "stand" ? (
            <Stand finish={finish} exploded={hero} />
          ) : kind === "materials" ? (
            <Materials finish={finish} />
          ) : kind === "riser" ? (
            <Riser finish={finish} />
          ) : (
            <Organizer finish={finish} />
          )}
        </g>
      )}
    </svg>
  );
}
