import { InferenceMethodSelector } from "./InferenceMethodSelector";

/** Backwards-compat thin wrapper — defers to the generic selector. */
export function HuddlingMethodSelector() {
  return (
    <InferenceMethodSelector
      modelName="huddling-detector"
      title="Huddling method"
      description="Algorithm that converts bird positions into a huddling score."
    />
  );
}
