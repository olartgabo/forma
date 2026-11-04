"use client";

// Identified-item cards (#177 follow-up): what each visible object probably
// is, where it is, whether build rules exist and what a photo can measure.
// Every value is an editable proposal; nothing here confirms stock.
import { useState } from "react";
import type { Media } from "../../lib/generated/api-contracts";
import type {
  ItemIdentity,
  RecognizedItem,
  Stock,
} from "../../lib/generated/contracts";
import PhotoCanvas from "./photo-canvas";
import {
  CAPABILITY_TEXT,
  CATEGORIES,
  GROUP_LABEL,
  capability,
  category,
  correctIdentity,
  identityLabel,
  linkFits,
  renameItem,
  setInstance,
  setVisibility,
  support,
} from "./recognized";

const OTHER = "__other";
const UNSURE = "__uncertain";
const GROUPS = Object.keys(GROUP_LABEL) as (keyof typeof GROUP_LABEL)[];

function selectValue(identity: ItemIdentity) {
  if (identity.outcome === "catalog") return identity.category_id ?? UNSURE;
  return identity.outcome === "other" ? OTHER : UNSURE;
}

export default function IdentifiedItems({
  token,
  projectId,
  items,
  photos,
  stocks,
  problems,
  locked,
  onChange,
  onRemove,
  onUseAsMaterial,
}: {
  token: string;
  projectId: string;
  items: readonly RecognizedItem[];
  photos: readonly Media[];
  stocks: readonly Stock[];
  problems: Readonly<Record<string, readonly string[]>>;
  locked: boolean;
  onChange: (
    id: string,
    update: (item: RecognizedItem) => RecognizedItem,
  ) => void;
  onRemove: (id: string) => void;
  onUseAsMaterial: (item: RecognizedItem) => void;
}) {
  const [names, setNames] = useState<Record<string, string>>({});
  const [others, setOthers] = useState<Record<string, string>>({});
  if (!items.length) return null;

  function commitName(item: RecognizedItem) {
    const name = names[item.id];
    setNames(({ [item.id]: _, ...rest }) => rest);
    if (name !== undefined) onChange(item.id, (i) => renameItem(i, name));
  }
  function commitOther(item: RecognizedItem) {
    const label = (others[item.id] ?? "").trim().slice(0, 80);
    if (!label) return;
    onChange(item.id, (i) =>
      correctIdentity(i, { outcome: "other", other_label: label }),
    );
  }
  function choose(item: RecognizedItem, value: string) {
    if (value === OTHER) {
      setOthers((o) => ({ ...o, [item.id]: o[item.id] ?? "" }));
      const label = item.identity.other_label ?? "";
      if (label)
        onChange(item.id, (i) =>
          correctIdentity(i, { outcome: "other", other_label: label }),
        );
      return;
    }
    setOthers(({ [item.id]: _, ...rest }) => rest);
    // Keep the look-alikes as alternatives so the choice stays visible.
    const alternatives = [
      ...(item.identity.alternatives ?? []),
      ...(item.identity.category_id ? [item.identity.category_id] : []),
    ].filter((a, i, all) => a !== value && all.indexOf(a) === i);
    onChange(item.id, (i) =>
      correctIdentity(
        i,
        value === UNSURE
          ? { outcome: "uncertain", alternatives: alternatives.slice(0, 3) }
          : {
              outcome: "catalog",
              category_id: value as NonNullable<ItemIdentity["category_id"]>,
              alternatives: alternatives.slice(0, 3),
            },
      ),
    );
  }

  return (
    <section className="identified-items" aria-labelledby="identified-heading">
      <h3 id="identified-heading">Identified items</h3>
      <p className="help">
        What Muse thinks each object is. These are suggestions, not proof of
        what it is made of, how strong or thick it is, or how much is left.
        Correct anything that is wrong; your corrections are kept.
      </p>
      <ol className="identified-list">
        {items.map((item) => {
          const info =
            item.identity.outcome === "catalog"
              ? category(item.identity.category_id)
              : null;
          const s = support(item.identity);
          const cap = capability(item.identity);
          const photo = photos.find((p) => p.id === item.media_id);
          const linked = stocks.find((st) => st.id === item.stock_id);
          const value =
            others[item.id] !== undefined ? OTHER : selectValue(item.identity);
          return (
            <li
              key={item.id}
              className="identified-card"
              id={`item-${item.id}`}
            >
              <div className="material-card-head">
                <label className="material-name">
                  <span className="visually-hidden">Item name</span>
                  <input
                    aria-label="Item name"
                    value={names[item.id] ?? item.name}
                    disabled={locked}
                    maxLength={80}
                    onChange={(e) =>
                      setNames((n) => ({ ...n, [item.id]: e.target.value }))
                    }
                    onBlur={() => commitName(item)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitName(item);
                    }}
                  />
                </label>
                <button
                  type="button"
                  className="quiet danger"
                  disabled={locked}
                  onClick={() => onRemove(item.id)}
                >
                  Remove
                </button>
              </div>
              <p className="help">
                {item.identity_source === "user"
                  ? "You chose what this is."
                  : "Muse suggestion."}{" "}
                {item.instance === "group_count_unknown"
                  ? "A group; how many is not counted."
                  : ""}
                {item.visibility === "partial"
                  ? " Partly hidden or cut off."
                  : ""}
              </p>
              <div className="field-row">
                <label>
                  What is it?
                  <select
                    value={value}
                    disabled={locked}
                    onChange={(e) => choose(item, e.target.value)}
                  >
                    <option value={UNSURE}>Not sure</option>
                    {GROUPS.map((group) => (
                      <optgroup key={group} label={GROUP_LABEL[group]}>
                        {CATEGORIES.filter((c) => c.group === group).map(
                          (c) => (
                            <option key={c.id} value={c.id}>
                              {c.label}
                            </option>
                          ),
                        )}
                      </optgroup>
                    ))}
                    <option value={OTHER}>Something else…</option>
                  </select>
                </label>
                {value === OTHER && (
                  <label>
                    Describe it
                    <input
                      value={others[item.id] ?? item.identity.other_label ?? ""}
                      disabled={locked}
                      maxLength={80}
                      onChange={(e) =>
                        setOthers((o) => ({ ...o, [item.id]: e.target.value }))
                      }
                      onBlur={() => commitOther(item)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitOther(item);
                      }}
                    />
                  </label>
                )}
                <label>
                  In the photo
                  <select
                    value={item.visibility ?? "unclear"}
                    disabled={locked}
                    onChange={(e) =>
                      onChange(item.id, (i) =>
                        setVisibility(
                          i,
                          e.target.value as NonNullable<
                            RecognizedItem["visibility"]
                          >,
                        ),
                      )
                    }
                  >
                    <option value="full">Fully visible</option>
                    <option value="partial">Partly hidden or cut off</option>
                    <option value="unclear">Not sure</option>
                  </select>
                </label>
                <label>
                  How many
                  <select
                    value={item.instance ?? "single"}
                    disabled={locked}
                    onChange={(e) =>
                      onChange(item.id, (i) =>
                        setInstance(
                          i,
                          e.target.value as NonNullable<
                            RecognizedItem["instance"]
                          >,
                        ),
                      )
                    }
                  >
                    <option value="single">One object</option>
                    <option value="group_count_unknown">
                      A group (not counted)
                    </option>
                  </select>
                </label>
              </div>
              {(item.identity.alternatives ?? []).length > 0 && (
                <p className="help">
                  Could also be:{" "}
                  {(item.identity.alternatives ?? []).map((a, index) => (
                    <span key={a}>
                      {index > 0 && ", "}
                      <button
                        type="button"
                        className="link"
                        disabled={locked}
                        onClick={() => choose(item, a)}
                      >
                        {category(a)?.label ?? a}
                      </button>
                    </span>
                  ))}
                </p>
              )}
              <dl className="identified-facts">
                <div>
                  <dt>Identified as</dt>
                  <dd>
                    {identityLabel(item.identity)}
                    {info
                      ? `; material family: ${info.material_family}${info.composition_unknown ? " (exact composition unknown)" : ""}`
                      : ""}
                  </dd>
                </div>
                <div>
                  <dt>Build rules</dt>
                  <dd>
                    {s.state === "available"
                      ? `Available as a ${s.material === "other_supported" ? "" : s.material + " "}${s.kind}.${s.note ? " " + s.note : ""}`
                      : s.reason}
                  </dd>
                </div>
                <div>
                  <dt>From a photo</dt>
                  <dd>
                    {cap
                      ? CAPABILITY_TEXT[cap]
                      : "Choose what it is to see what a photo can measure."}{" "}
                    Thickness, strength and hidden sizes stay unknown.
                  </dd>
                </div>
              </dl>
              {(problems[item.id] ?? []).map((p) => (
                <p key={p} className="warning">
                  {p}
                </p>
              ))}
              {linked && !linkFits(item, [linked]) && (
                <p className="warning">
                  This no longer matches the saved material &ldquo;
                  {linked.name ?? linked.id}&rdquo;. Remove that material, or
                  change this item back.
                </p>
              )}
              {s.state === "available" &&
                (linked ? (
                  <p className="help">
                    Saved as the material “{linked.name ?? linked.id}”.
                  </p>
                ) : (
                  <button
                    type="button"
                    className="secondary"
                    disabled={locked}
                    onClick={() => onUseAsMaterial(item)}
                  >
                    Use as a material
                  </button>
                ))}
              {photo && item.box && (
                <PhotoCanvas
                  token={token}
                  projectId={projectId}
                  photo={photo}
                  label={`Where ${item.name} is in the photo (${item.box_source === "muse_approximate" ? "approximate, from Muse" : item.box_source === "sam" ? "from SAM" : "drawn by you"})`}
                  box={{
                    x1: item.box.x1 * photo.width_px,
                    y1: item.box.y1 * photo.height_px,
                    x2: item.box.x2 * photo.width_px,
                    y2: item.box.y2 * photo.height_px,
                  }}
                  mode={{ kind: "view" }}
                />
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
