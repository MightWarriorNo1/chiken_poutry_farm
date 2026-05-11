import { useQueries, useQuery } from "@tanstack/react-query";
import { Camera, PlayCircle, Video } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { fmtInt, fmtNumber, fmtPct, relativeTime } from "../format";
import type { CameraView } from "../types";
import { Empty } from "./Empty";
import { LiveView } from "./LiveView";
import { Sparkline } from "./Sparkline";

export function CamerasTab() {
  const [liveCameraId, setLiveCameraId] = useState<string | null>(null);

  const cameras = useQuery({
    queryKey: ["cameras"],
    queryFn: api.cameras,
    refetchInterval: 5_000,
  });

  const seriesQueries = useQueries({
    queries: (cameras.data ?? []).map((c) => ({
      queryKey: ["cameraSeries", c.camera_id],
      queryFn: () => api.cameraSeries(c.camera_id),
      refetchInterval: 10_000,
      // Don't hammer the API for empty series on first load.
      enabled: true,
    })),
  });

  if (!cameras.data) {
    return <div className="text-sm text-slate-500">Loading cameras…</div>;
  }
  if (cameras.data.length === 0) {
    return (
      <Empty
        icon={<Video className="h-6 w-6" />}
        title="No cameras yet"
        description="Bird detection events haven't arrived. Add a camera to EdgeConfig (or wait for the next frame)."
      />
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {cameras.data.map((cam, i) => (
          <CameraCard
            key={cam.camera_id}
            cam={cam}
            series={seriesQueries[i]?.data}
            onLive={() => setLiveCameraId(cam.camera_id)}
          />
        ))}
      </div>
      {liveCameraId && (
        <LiveView
          cameraId={liveCameraId}
          onClose={() => setLiveCameraId(null)}
        />
      )}
    </>
  );
}

interface CardProps {
  cam: CameraView;
  series:
    | {
        bird_count: { t: string; values: Record<string, number> }[];
        huddling: { t: string; values: Record<string, number> }[];
      }
    | undefined;
  onLive: () => void;
}

function CameraCard({ cam, series, onLive }: CardProps) {
  const huddleHigh = (cam.huddling_score ?? 0) > 0.7;

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <Camera className="h-4 w-4 text-sky-400" />
            {cam.camera_id}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500">
            {cam.shed_id && <span>shed {cam.shed_id}</span>}
            {cam.zone_id && <span>zone {cam.zone_id}</span>}
            {cam.flock_id && <span>flock {cam.flock_id}</span>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-2 text-xs text-slate-500 tabular-nums">
          <button
            type="button"
            onClick={onLive}
            className="inline-flex items-center gap-1 rounded-md border border-sky-500/40 bg-sky-500/10 px-2 py-1 text-xs font-medium text-sky-300 hover:bg-sky-500/20"
            title="Open live MJPEG stream"
          >
            <PlayCircle className="h-3.5 w-3.5" />
            Live
          </button>
          <div className="text-right">
            <div>last frame</div>
            <div className="text-slate-300">
              {relativeTime(cam.last_frame_at)}
            </div>
          </div>
        </div>
      </div>

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
    </div>
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
