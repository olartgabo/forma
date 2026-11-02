import type { BuildRequirements } from "../lib/generated/api-contracts";
import { constraintFields, editConstraint } from "../lib/build-requirements";

export default function BuildRequirementsFields({
  value,
  onChange,
}: {
  value: BuildRequirements;
  onChange: (next: BuildRequirements) => void;
}) {
  return (
    <section
      className="build-requirements"
      aria-labelledby="requirements-title"
    >
      <h3 id="requirements-title">Tools and the space you need</h3>
      <p className="help">
        Leave unknown measurements blank. These details guide the design; fit
        and stability still need physical checks.
      </p>
      <label htmlFor="available-tools">Available tools, one per line</label>
      <textarea
        id="available-tools"
        rows={3}
        maxLength={2591}
        aria-describedby="tools-help"
        value={(value.tools ?? []).join("\n")}
        onChange={(event) =>
          onChange({ ...value, tools: event.target.value.split("\n") })
        }
      />
      <p id="tools-help" className="help">
        List only tools you have, such as a ruler, scissors or a cutting mat. Up
        to 32 tools.
      </p>
      <label htmlFor="device-description">What will the stand hold?</label>
      <textarea
        id="device-description"
        rows={2}
        maxLength={2000}
        value={value.device_description ?? ""}
        onChange={(event) =>
          onChange({ ...value, device_description: event.target.value || null })
        }
      />
      <div className="measurement-grid">
        {constraintFields.map(({ field, label, unit }) => {
          const measurement = value.constraints[field];
          return (
            <div className="measurement" key={field}>
              <label htmlFor={`constraint-${field}`}>
                {label} <span>({unit})</span>
              </label>
              <input
                id={`constraint-${field}`}
                type="number"
                step="any"
                min="0"
                max={field === "support_angle_deg" ? "90" : undefined}
                value={measurement.value ?? ""}
                onChange={(event) =>
                  onChange({
                    ...value,
                    constraints: editConstraint(
                      value.constraints,
                      field,
                      event.target.value,
                    ),
                  })
                }
              />
              {measurement.value !== null && (
                <>
                  <label htmlFor={`source-${field}`}>Measurement source</label>
                  <select
                    id={`source-${field}`}
                    value={measurement.source}
                    onChange={(event) =>
                      onChange({
                        ...value,
                        constraints: {
                          ...value.constraints,
                          [field]: {
                            ...measurement,
                            source:
                              event.target.value === "known_reference"
                                ? "known_reference"
                                : "user_ruler",
                            confirmed: false,
                            evidence_ids: [],
                          },
                        },
                      })
                    }
                  >
                    <option value="user_ruler">Measured directly</option>
                    <option value="known_reference">
                      Known device or reference specification
                    </option>
                    {measurement.source === "calculated" && (
                      <option value="calculated">Calculated</option>
                    )}
                  </select>
                </>
              )}
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  disabled={measurement.value === null}
                  checked={measurement.confirmed}
                  aria-label={`${label} checked`}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      constraints: {
                        ...value.constraints,
                        [field]: {
                          ...measurement,
                          confirmed: event.target.checked,
                        },
                      },
                    })
                  }
                />
                Checked against my measurement or reference
              </label>
              {measurement.value === null && (
                <span className="unknown-note">Unknown</span>
              )}
            </div>
          );
        })}
      </div>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={value.constraints.allow_purchases ?? false}
          onChange={(event) =>
            onChange({
              ...value,
              constraints: {
                ...value.constraints,
                allow_purchases: event.target.checked,
              },
            })
          }
        />
        I am willing to get additional materials if needed
      </label>
    </section>
  );
}
