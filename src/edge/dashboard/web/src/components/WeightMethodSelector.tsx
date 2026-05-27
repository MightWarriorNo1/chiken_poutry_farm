import { InferenceMethodSelector } from "./InferenceMethodSelector";

/** Thin wrapper — defers to the generic selector for the weight-estimator. */
export function WeightMethodSelector() {
  return (
    <InferenceMethodSelector
      modelName="weight-estimator"
      title="Weight estimation method"
      description="Algorithm that converts each detected chicken's pixel footprint into a weight estimate."
    />
  );
}
