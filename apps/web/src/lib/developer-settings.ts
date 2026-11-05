let modelKey = "";
export function setModelKey(value: string) {
  modelKey = value;
  if (typeof window !== "undefined")
    window.dispatchEvent(new Event("forma-model-key-changed"));
}
export function modelKeyHeaders(): Record<string, string> {
  return modelKey ? { "X-Forma-Model-Key": modelKey } : {};
}

export function hasModelKey() {
  return !!modelKey;
}
