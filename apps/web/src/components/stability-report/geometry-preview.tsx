import type { CanonicalGeometryPreview } from "../../lib/generated/contracts";

const number = (value: number) => Number(value.toPrecision(5)).toString();

export default function GeometryPreview({
  geometry,
}: {
  geometry: CanonicalGeometryPreview;
}) {
  const points = geometry.facets.flatMap((facet) => facet.vertices);
  const minY = Math.min(...points.map((point) => point.y));
  const maxY = Math.max(...points.map((point) => point.y));
  const minZ = Math.min(...points.map((point) => point.z));
  const maxZ = Math.max(...points.map((point) => point.z));
  const scale = 240 / Math.max(maxY - minY, maxZ - minZ, 0.001);
  const xy = (point: { y: number; z: number }) =>
    `${30 + (point.y - minY) * scale},${270 - (point.z - minZ) * scale}`;
  return (
    <figure style={{ marginInline: 0 }}>
      <figcaption>
        Nominal assembly —{" "}
        {geometry.stage === "planned_preview"
          ? "planned preview"
          : "user-reported assembled stage"}
      </figcaption>
      <p>
        Plan geometry only. This is not a measured shape, a center-of-mass
        result, or a physical stability pass.
      </p>
      <svg
        viewBox="0 0 320 310"
        role="img"
        aria-label="Nominal assembly side view with numbered facets"
        style={{ width: "100%", maxWidth: 420 }}
      >
        <text x="10" y="16">
          Side view: y rearward, z upward (m)
        </text>
        {geometry.facets.map((facet, index) => (
          <g key={facet.facet_id}>
            <polygon
              points={facet.vertices.map(xy).join(" ")}
              fill="none"
              stroke="#334155"
              strokeWidth="3"
            />
            <text
              x={30 + (facet.centroid.y - minY) * scale + 5}
              y={270 - (facet.centroid.z - minZ) * scale - 8}
              fill="#111827"
              fontSize="14"
            >
              {index + 1}
            </text>
          </g>
        ))}
      </svg>
      <p>
        Depth span: {number(maxY - minY)} m. Height span: {number(maxZ - minZ)}{" "}
        m.
      </p>
      <ol>
        {geometry.facets.map((facet) => (
          <li key={facet.facet_id} style={{ overflowWrap: "anywhere" }}>
            {facet.facet_id} · source part {facet.part_id}
          </li>
        ))}
      </ol>
      <details>
        <summary>Geometry assumptions and source</summary>
        <ul>
          {geometry.assumptions.map((assumption) => (
            <li key={assumption}>{assumption}</li>
          ))}
        </ul>
        <p style={{ overflowWrap: "anywhere" }}>
          Geometry version: {geometry.producer_version}. Geometry hash:{" "}
          {geometry.geometry_hash}.
        </p>
      </details>
    </figure>
  );
}
