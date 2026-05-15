import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Settings2,
} from "lucide-react";

import { api } from "../api";

interface Props {
  modelName: string;
  title: string;
  description?: string;
}

/**
 * Reusable inference-algorithm dropdown for any model_name registered with
 * the InferenceSupervisor (huddling-detector, weight-estimator, ...).
 *
 * The backend hot-swaps the underlying adapter — no restart required.
 * Selection is persisted in `state/inference_selection.json`.
 *
 * Versions whose artifact (`.pt`) isn't on disk yet still appear in the
 * dropdown, but are disabled with a hint about what's missing.
 */
export function InferenceMethodSelector({
  modelName,
  title,
  description,
}: Props) {
  const qc = useQueryClient();

  const versions = useQuery({
    queryKey: ["inference", modelName, "versions"],
    queryFn: () => api.inferenceVersions(modelName),
    refetchInterval: 30_000,
  });

  const selectMut = useMutation({
    mutationFn: (version: string) => api.inferenceSelect(modelName, version),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inference", modelName, "versions"] });
    },
  });

  const onChange: React.ChangeEventHandler<HTMLSelectElement> = (e) => {
    const v = e.target.value;
    if (!v) return;
    selectMut.mutate(v);
  };

  const active = versions.data?.find((v) => v.is_active);
  const errorMsg = selectMut.error?.message;

  return (
    <div className="card">
      <div className="flex items-start gap-2">
        <Settings2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-sky-400" />
        <div className="flex-1">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            {title}
          </div>
          {description && (
            <div className="mt-0.5 text-[11px] text-slate-500">
              {description}
            </div>
          )}
          {!versions.data ? (
            <div className="mt-2 flex items-center gap-2 text-sm text-slate-500">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading available methods…
            </div>
          ) : versions.data.length === 0 ? (
            <div className="mt-2 text-sm text-slate-500">
              No versions for{" "}
              <code className="text-slate-300">{modelName}</code> found on
              disk.
            </div>
          ) : (
            <>
              <select
                className="mt-2 w-full rounded-md border border-ink-700 bg-ink-950 px-2 py-1.5 text-sm text-slate-100 focus:border-sky-500 focus:outline-none disabled:opacity-50"
                value={active?.version ?? ""}
                onChange={onChange}
                disabled={selectMut.isPending}
              >
                {!active && <option value="">— pick a method —</option>}
                {versions.data.map((v) => (
                  <option
                    key={v.version}
                    value={v.version}
                    disabled={!v.available && !v.is_active}
                  >
                    {v.display_name} ({v.version})
                    {!v.available && !v.is_active ? " — unavailable" : ""}
                  </option>
                ))}
              </select>
              <div className="mt-2 space-y-1 text-[11px] text-slate-500">
                {active && (
                  <div className="flex items-center gap-1 text-emerald-300">
                    <CheckCircle2 className="h-3 w-3" />
                    Active: {active.algorithm} ({active.version})
                  </div>
                )}
                {versions.data
                  .filter((v) => !v.available && !v.is_active && v.notes)
                  .map((v) => (
                    <div
                      key={v.version}
                      className="flex items-start gap-1 text-amber-300/80"
                    >
                      <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0" />
                      <span>
                        <strong>{v.version}:</strong> {v.notes}
                      </span>
                    </div>
                  ))}
              </div>
              {errorMsg && (
                <div className="mt-2 flex items-start gap-1 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-200">
                  <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0" />
                  <div className="flex-1">{errorMsg}</div>
                  <button
                    type="button"
                    className="text-rose-300 underline"
                    onClick={() => selectMut.reset()}
                  >
                    dismiss
                  </button>
                </div>
              )}
              {selectMut.isPending && (
                <div className="mt-2 flex items-center gap-1 text-[11px] text-sky-300">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Switching method…
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
