import { useQueries, useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  Camera,
  CircleDot,
  PlayCircle,
  Video,
} from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "../api";
import { fmtInt, fmtNumber, fmtPct, relativeTime } from "../format";
import type { CameraSourceView, CameraSourceType, CameraView } from "../types";
import { Empty } from "./Empty";
import { LiveView } from "./LiveView";
import { Sparkline } from "./Sparkline";

const TYPE_ORDER: CameraSourceType[] = [
  "rtsp",
  "http",
  "usb",
  "csi",
  "gstreamer",
  "file",
  "unknown",
];

type Filter = "all" | CameraSourceType;

export function CamerasTab() {
  const [liveCameraId, setLiveCameraId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const cameras = useQuery({
    queryKey: ["cameras"],
    queryFn: api.cameras,
    refetchInterval: 5_000,
  });

  // Phase 2: source/type browser. Polled alongside the detection-driven
  // /api/cameras so type badges and connection status stay fresh.
  const sources = useQuery({
    queryKey: ["cameraSources"],
    queryFn: api.cameraSources,
    refetchInterval: 5_000,
  });

  const seriesQueries = useQueries({
    queries: (cameras.data ?? []).map((c) => ({
      queryKey: ["cameraSeries", c.camera_id],
      queryFn: () => api.cameraSeries(c.camera_id),
      refetchInterval: 10_000,
      enabled: true,
    })),
  });

  // Combine: for every configured camera, attach its detection-driven view
  // (if any). Detection-only cameras with no source row are still shown.
  const combined = useMemo(() => {
    const sourcesById = new Map<string, CameraSourceView>(
      (sources.data ?? []).map((s) => [s.camera_id, s]),
    );
    const detectionById = new Map<string, CameraView>(
      (cameras.data ?? []).map((c) => [c.camera_id, c]),
    );
    const allIds = new Set<string>([
      ...sourcesById.keys(),
      ...detectionById.keys(),
    ]);
    return [...allIds].sort().map((id) => ({
      camera_id: id,
      source: sourcesById.get(id),
      detection: detectionById.get(id),
    }));
  }, [sources.data, cameras.data]);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: combined.length };
    for (const t of TYPE_ORDER) m[t] = 0;
    for (const c of combined) {
      const k = c.source?.source_type ?? "unknown";
      m[k] = (m[k] ?? 0) + 1;
    }
    return m;
  }, [combined]);

  const visible = useMemo(() => {
    if (filter === "all") return combined;
    return combined.filter((c) => c.source?.source_type === filter);
  }, [combined, filter]);

  if (cameras.isLoading && sources.isLoading) {
    return <div className="text-sm text-slate-500">Loading cameras…</div>;
  }

  return (
    <>
      <TypeFilter
        active={filter}
        onChange={setFilter}
        counts={counts}
        availableTypes={TYPE_ORDER.filter((t) => (counts[t] ?? 0) > 0)}
      />

      {visible.length === 0 ? (
        filter === "all" ? (
          <Empty
            icon={<Video className="h-6 w-6" />}
            title="No cameras yet"
            description="No cameras configured. Add one to EdgeConfig (or wait for the next frame on a configured camera)."
          />
        ) : (
          <Empty
            icon={<Video className="h-6 w-6" />}
            title={`No ${filter.toUpperCase()} cameras`}
            description="No cameras of this type are configured. Switch the filter to see what is."
          />
        )
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {visible.map((entry, i) => (
            <CameraCard
              key={entry.camera_id}
              cameraId={entry.camera_id}
              cam={entry.detection}
              source={entry.source}
              series={
                entry.detection
                  ? seriesQueries[
                      (cameras.data ?? []).findIndex(
                        (c) => c.camera_id === entry.camera_id,
                      )
                    ]?.data
                  : undefined
              }
              onLive={() => setLiveCameraId(entry.camera_id)}
              indexHint={i}
            />
          ))}
        </div>
      )}

      {liveCameraId && (
        <LiveView
          cameraId={liveCameraId}
          onClose={() => setLiveCameraId(null)}
        />
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

interface TypeFilterProps {
  active: Filter;
  onChange: (f: Filter) => void;
  counts: Record<string, number>;
  availableTypes: CameraSourceType[];
}

function TypeFilter({
  active,
  onChange,
  counts,
  availableTypes,
}: TypeFilterProps) {
  const pills: { id: Filter; label: string }[] = [
    { id: "all", label: "All" },
    ...availableTypes.map((t) => ({ id: t, label: labelFor(t) })),
  ];

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <span className="text-xs uppercase tracking-wider text-slate-500">
        Source type
      </span>
      <div className="flex flex-wrap gap-1.5">
        {pills.map((p) => {
          const isActive = active === p.id;
          const n = counts[p.id] ?? 0;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => onChange(p.id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                isActive
                  ? "border-sky-500/60 bg-sky-500/15 text-sky-200"
                  : "border-ink-700 bg-ink-900 text-slate-400 hover:border-ink-600 hover:text-slate-200"
              }`}
            >
              {p.label}
              <span
                className={`tabular-nums ${isActive ? "text-sky-300" : "text-slate-500"}`}
              >
                {n}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function labelFor(t: CameraSourceType): string {
  switch (t) {
    case "rtsp":
      return "RTSP";
    case "http":
      return "HTTP";
    case "usb":
      return "USB";
    case "csi":
      return "CSI";
    case "gstreamer":
      return "GStreamer";
    case "file":
      return "File";
    default:
      return "Unknown";
  }
}

// ─────────────────────────────────────────────────────────────────────────────

interface CardProps {
  cameraId: string;
  cam: CameraView | undefined;
  source: CameraSourceView | undefined;
  series:
    | {
        bird_count: { t: string; values: Record<string, number> }[];
        huddling: { t: string; values: Record<string, number> }[];
      }
    | undefined;
  onLive: () => void;
  indexHint: number;
}

function CameraCard({ cameraId, cam, source, onLive, series }: CardProps) {
  const huddleHigh = (cam?.huddling_score ?? 0) > 0.7;
  const isDemo = source?.role === "demo";
  const canLive = source?.has_frames === true || !!cam;

  const shedId = cam?.shed_id ?? source?.shed_id ?? null;
  const zoneId = cam?.zone_id ?? source?.zone_id ?? null;
  const flockId = cam?.flock_id ?? source?.flock_id ?? null;

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <Camera className="h-4 w-4 text-sky-400" />
            <span className="truncate" title={cameraId}>
              {cameraId}
            </span>
            {source && (
              <TypeBadge type={source.source_type} label={source.source_type_label} />
            )}
            {isDemo && (
              <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-violet-300">
                demo
              </span>
            )}
            {source && <ConnBadge source={source} />}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500">
            {shedId && <span>shed {shedId}</span>}
            {zoneId && <span>zone {zoneId}</span>}
            {flockId && <span>flock {flockId}</span>}
          </div>
          {source?.source_uri && (
            <div
              className="mt-1 truncate text-[11px] text-slate-600"
              title={source.source_uri}
            >
              {source.source_uri}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-2 text-xs text-slate-500 tabular-nums">
          <button
            type="button"
            onClick={onLive}
            disabled={!canLive}
            className="inline-flex items-center gap-1 rounded-md border border-sky-500/40 bg-sky-500/10 px-2 py-1 text-xs font-medium text-sky-300 hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-40"
            title={
              canLive
                ? "Open live MJPEG stream"
                : "No frames yet — wait until the pipeline produces one"
            }
          >
            <PlayCircle className="h-3.5 w-3.5" />
            Live
          </button>
          {cam && (
            <div className="text-right">
              <div>last frame</div>
              <div className="text-slate-300">
                {relativeTime(cam.last_frame_at)}
              </div>
            </div>
          )}
        </div>
      </div>

      {cam ? (
        <>
          <div className="mt-4 grid grid-cols-3 gap-3">
            <Metric label="Birds" value={fmtInt(cam.bird_count)}>
              {series?.bird_count && (
                <Sparkline points={series.bird_count} valueKey="count" />
              )}
            </Metric>
            <Metric
              label="Density"
              value={fmtPct(cam.density_score, 0)}
              sub={`conf ${fmtPct(cam.confidence, 0)}`}
            >
              {series?.bird_count && (
                <Sparkline
                  points={series.bird_count}
                  valueKey="density"
                  color="#a78bfa"
                  tooltipFormatter={(n) => `${(n * 100).toFixed(0)}%`}
                />
              )}
            </Metric>
            <Metric
              label="Huddling"
              value={fmtPct(cam.huddling_score, 0)}
              tone={huddleHigh ? "bad" : "ok"}
            >
              {series?.huddling && (
                <Sparkline
                  points={series.huddling}
                  valueKey="score"
                  color={huddleHigh ? "#fb7185" : "#34d399"}
                  tooltipFormatter={(n) => `${(n * 100).toFixed(0)}%`}
                />
              )}
            </Metric>
          </div>

          <div className="mt-4 flex items-end justify-between border-t border-ink-700 pt-3">
            <div>
              <div className="text-xs text-slate-500">Estimated weight</div>
              <div className="mt-0.5 text-xl font-semibold text-slate-100 tabular-nums">
                {fmtNumber(cam.estimated_avg_weight_g, 0)}{" "}
                <span className="text-sm text-slate-500">g</span>
              </div>
            </div>
            <div className="text-right text-xs text-slate-500">
              {cam.breed && <div>{cam.breed}</div>}
              {cam.bird_age_days !== null && cam.bird_age_days !== undefined && (
                <div>{cam.bird_age_days} days old</div>
              )}
              {cam.weight_confidence !== null &&
                cam.weight_confidence !== undefined && (
                  <div>confidence {fmtPct(cam.weight_confidence, 0)}</div>
                )}
            </div>
          </div>
        </>
      ) : (
        <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
          <AlertCircle className="h-3.5 w-3.5" />
          No detections yet — pipeline hasn't produced an event for this
          camera.
        </div>
      )}
    </div>
  );
}

function TypeBadge({ type, label }: { type: CameraSourceType; label: string }) {
  const colors: Record<CameraSourceType, string> = {
    rtsp: "bg-amber-500/15 text-amber-300",
    http: "bg-amber-500/15 text-amber-300",
    usb: "bg-emerald-500/15 text-emerald-300",
    csi: "bg-purple-500/15 text-purple-300",
    gstreamer: "bg-cyan-500/15 text-cyan-300",
    file: "bg-slate-500/15 text-slate-300",
    unknown: "bg-slate-700/30 text-slate-400",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${colors[type]}`}
    >
      {label}
    </span>
  );
}

function ConnBadge({ source }: { source: CameraSourceView }) {
  if (source.has_frames) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-300">
        <CircleDot className="h-2.5 w-2.5" /> connected
      </span>
    );
  }
  if (source.running) {
    return (
      <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-amber-300">
        starting
      </span>
    );
  }
  return (
    <span className="rounded-full bg-slate-700/30 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-slate-400">
      idle
    </span>
  );
}

interface MetricProps {
  label: string;
  value: string;
  sub?: string;
  tone?: "ok" | "warn" | "bad";
  children?: React.ReactNode;
}

function Metric({ label, value, sub, tone = "ok", children }: MetricProps) {
  const toneClass = {
    ok: "text-slate-100",
    warn: "text-amber-300",
    bad: "text-rose-300",
  }[tone];
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-0.5 text-xl font-semibold tabular-nums ${toneClass}`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-slate-600">{sub}</div>}
      <div className="mt-1">{children}</div>
    </div>
  );
}
