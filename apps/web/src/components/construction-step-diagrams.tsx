import type {
  ConstructionPlan,
  ConstructionStep,
} from "../lib/generated/contracts";
import { orthographicConstruction } from "../lib/construction-projection";

export default function ConstructionStepDiagrams({
  plan,
  step,
}: {
  plan: ConstructionPlan;
  step: ConstructionStep;
}) {
  const views = ["top", "front", "side"] as const;
  return (
    <section aria-label="Proposed step diagrams">
      <h4>Step-by-step blueprints</h4>
      <p className="help">
        Top, front and side views of the same proposed step. Labels show
        projected bounds in millimeters, not measured material sizes or cutting
        dimensions. Edge-on panels appear as lines. Pink, thick outlines mark
        this step’s pieces.
      </p>
      <div className="construction-blueprints">
        {views.map((view) => {
          const { facets, fit } = orthographicConstruction(
            step.analysis.facets,
            view,
          );
          const screen = facets.flatMap((facet) =>
            facet.points.map((p) => ({ x: fit.x(p.x), y: fit.y(p.y) })),
          );
          const left = Math.min(...screen.map((p) => p.x)),
            right = Math.max(...screen.map((p) => p.x));
          const top = Math.min(...screen.map((p) => p.y)),
            bottom = Math.max(...screen.map((p) => p.y));
          const widthMm = Math.round(fit.width * 10000) / 10;
          const heightMm = Math.round(fit.height * 10000) / 10;
          return (
            <figure key={view} className="drawing-sheet construction-blueprint">
              <figcaption className="drawing-sheet-title">
                <strong>
                  Step {step.index + 1} / {view}
                </strong>
                <span>
                  {view === "top"
                    ? "X / Y"
                    : view === "front"
                      ? "X / Z"
                      : "Y / Z"}
                </span>
              </figcaption>
              <div className="drawing-sheet-ticks" aria-hidden="true" />
              <svg
                viewBox="0 0 400 410"
                role="img"
                aria-label={`${view} diagram for ${step.step_id}`}
                className="construction-blueprint-canvas"
              >
                {facets
                  .sort((a, b) => a.center.depth - b.center.depth)
                  .map((facet) => {
                    const number =
                      plan.piece_catalog.findIndex(
                        (p) => p.part_id === facet.part_id,
                      ) + 1;
                    const piece = plan.piece_catalog[number - 1];
                    const focus = step.part_ids.includes(facet.part_id);
                    return (
                      <g key={facet.facet_id}>
                        <title>
                          {piece?.display_name ?? facet.part_id} ·{" "}
                          {piece?.reference ?? facet.part_id}
                        </title>
                        <polygon
                          data-part-id={facet.part_id}
                          data-facet-id={facet.facet_id}
                          data-step-focus={focus}
                          className="construction-blueprint-panel"
                          points={facet.points
                            .map((p) => `${fit.x(p.x)},${fit.y(p.y)}`)
                            .join(" ")}
                          strokeWidth={focus ? 4 : 1.5}
                        />
                        <text
                          x={fit.x(facet.center.x)}
                          y={fit.y(facet.center.y) + 4}
                          textAnchor="middle"
                          className="construction-blueprint-number"
                        >
                          {number}
                        </text>
                      </g>
                    );
                  })}
                {widthMm > 0 && (
                  <g
                    className="construction-blueprint-dimension"
                    data-dimension="width"
                  >
                    <path
                      d={`M ${left} ${bottom + 6} V 376 M ${right} ${bottom + 6} V 376 M ${left} 366 H ${right}`}
                    />
                    <path
                      d={`M ${left + Math.min(6, (right - left) / 4)} 362 L ${left} 366 L ${left + Math.min(6, (right - left) / 4)} 370 M ${right - Math.min(6, (right - left) / 4)} 362 L ${right} 366 L ${right - Math.min(6, (right - left) / 4)} 370`}
                    />
                    <text x={(left + right) / 2} y={392} textAnchor="middle">
                      {widthMm} mm
                    </text>
                  </g>
                )}
                {heightMm > 0 && (
                  <g
                    className="construction-blueprint-dimension"
                    data-dimension="height"
                  >
                    <path
                      d={`M ${left - 6} ${top} H 19 M ${left - 6} ${bottom} H 19 M 25 ${top} V ${bottom}`}
                    />
                    <path
                      d={`M 21 ${top + Math.min(6, (bottom - top) / 4)} L 25 ${top} L 29 ${top + Math.min(6, (bottom - top) / 4)} M 21 ${bottom - Math.min(6, (bottom - top) / 4)} L 25 ${bottom} L 29 ${bottom - Math.min(6, (bottom - top) / 4)}`}
                    />
                    <text
                      transform={`translate(12 ${(top + bottom) / 2}) rotate(-90)`}
                      textAnchor="middle"
                    >
                      {heightMm} mm
                    </text>
                  </g>
                )}
              </svg>
              <p className="construction-blueprint-caption">
                Proposed bounds {widthMm} × {heightMm} mm · reference only
              </p>
            </figure>
          );
        })}
      </div>
      <p className="help">
        Supported planar-panel proposals only. These diagrams do not establish
        stability, connector strength, fabrication readiness or completed work.
      </p>
    </section>
  );
}
