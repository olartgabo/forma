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
      <h4>Step diagrams</h4>
      <p className="help">
        Top, front and side views of the same proposed step. Labels show
        projected bounds in millimeters, not measured material sizes or cutting
        dimensions. Edge-on panels appear as lines. Thick outlines mark this
        step’s pieces.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {views.map((view) => {
          const { facets, fit } = orthographicConstruction(
            step.analysis.facets,
            view,
          );
          return (
            <figure
              key={view}
              style={{ flex: "1 1 210px", margin: 0, minWidth: 0 }}
            >
              <figcaption>
                {view[0].toUpperCase() + view.slice(1)} (
                {view === "top"
                  ? "X / Y"
                  : view === "front"
                    ? "X / Z"
                    : "Y / Z"}
                ) · proposed bounds {Math.round(fit.width * 10000) / 10} ×{" "}
                {Math.round(fit.height * 10000) / 10} mm
              </figcaption>
              <svg
                viewBox="0 0 400 380"
                role="img"
                aria-label={`${view} diagram for ${step.step_id}`}
                style={{ width: "100%", maxHeight: 230, background: "#eef3ef" }}
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
                          points={facet.points
                            .map((p) => `${fit.x(p.x)},${fit.y(p.y)}`)
                            .join(" ")}
                          fill={`hsl(${number * 63} 30% 76%)`}
                          stroke={focus ? "#102c21" : "#718579"}
                          strokeWidth={focus ? 4 : 1.5}
                        />
                        <text
                          x={fit.x(facet.center.x)}
                          y={fit.y(facet.center.y) + 4}
                          textAnchor="middle"
                          fontSize="16"
                          fill="#183a30"
                          stroke="white"
                          strokeWidth="3"
                          paintOrder="stroke"
                        >
                          {number}
                        </text>
                      </g>
                    );
                  })}
              </svg>
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
