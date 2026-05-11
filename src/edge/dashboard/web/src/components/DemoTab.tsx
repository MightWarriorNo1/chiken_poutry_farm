import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Film,
  Loader2,
  PlayCircle,
  Square,
} from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { fmtInt, fmtNumber, fmtPct } from "../format";
import type { DemoStatusView, DemoVideoView } from "../types";
import { Empty } from "./Empty";
import { LiveView } from "./LiveView";

/**
 * Demo tab — list recorded videos in `demo/recordings/`, replay one through
 * the live pipeline, watch the annotated stream + live counters.
 *
 * The backend enforces "one demo at a time" — starting while running returns
 * 409. The UI mirrors that by disabling Start buttons whenever `status.running`
 * is true (except for the active one's Stop button).
 */
export function DemoTab() {
  const qc = useQueryClient();
  const [showLive, setShowLive] = useState(false);

  const videos = useQuery({
    queryKey: ["demo", "videos"],
    queryFn: api.demoVideos,
    refetchInterval: 30_000,
  });

  const status = useQuery({
    queryKey: ["demo", "status"],
    queryFn: api.demoStatus,
    // Aggressive while running so the progress bar feels live.
    refetchInterval: (q) => (q.state.data?.running ? 1_000 : 5_000),
  });

  const startMut = useMutation({
    mutationFn: (video: string) => api.demoStart(video),
    onSuccess: (data) => {
      qc.setQueryData(["demo", "status"], data);
      qc.invalidateQueries({ queryKey: ["cameraSources"] });
    },
  });

  const stopMut = useMutation({
    mutationFn: () => api.demoStop(),
    onSuccess: (data) => {
      qc.setQueryData(["demo", "status"], data);
      qc.invalidateQueries({ queryKey: ["cameraSources"] });
    },
  });

  const errorMsg = startMut.error?.message ?? stopMut.error?.message;

  return (
    <div className="space-y-6">
      <StatusCard
        status={status.data}
        onStop={() => stopMut.mutate()}
        onOpenLive={() => setShowLive(true)}
        stopping={stopMut.isPending}
      />

      {errorMsg && (
        <div className="card flex items-start gap-2 border-rose-500/40 bg-rose-500/10 text-sm text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div className="flex-1">{errorMsg}</div>
          <button
            type="button"
            className="text-xs text-rose-300 underline"
            onClick={() => {
              startMut.reset();
              stopMut.reset();
            }}
          >
            dismiss
          </button>
        </div>
      )}

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Recordings
        </h3>
        {videos.isLoading ? (
          <div className="text-sm text-slate-500">Scanning demo/recordings…</div>
        ) : !videos.data || videos.data.length === 0 ? (
          <Empty
            icon={<Film className="h-6 w-6" />}
            title="No demo videos found"
            description="Drop video files (.mp4, .mkv, .avi, .mov, .webm) into demo/recordings/ on the device, then refresh."
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {videos.data.map((v) => (
              <VideoCard
                key={v.name}
                video={v}
                running={status.data?.running ?? false}
                activeVideo={status.data?.video ?? null}
                onStart={() => startMut.mutate(v.name)}
                starting={
                  startMut.isPending && startMut.variables === v.name
                }
              />
            ))}
          </div>
        )}
      </section>

      {showLive && status.data?.running && status.data.camera_id && (
        <LiveView
          cameraId={status.data.camera_id}
          onClose={() => setShowLive(false)}
        />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

interface StatusCardProps {
  status: DemoStatusView | undefined;
  onStop: () => void;
  onOpenLive: () => void;
  stopping: boolean;
}

function StatusCard({
  status,
  onStop,
  onOpenLive,
  stopping,
}: StatusCardProps) {
  if (!status) {
    return (
      <div className="card flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading demo status…
      </div>
    );
  }

  if (status.running) {
    const pct = progressPct(status);
    return (
      <div className="card border-sky-500/40">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-sky-300">
              Demo running
            </div>
            <div className="mt-1 text-base font-semibold text-slate-100">
              {status.video}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              camera_id: <code className="text-slate-300">{status.camera_id}</code>
              {" · "}
              {fmtNumber(status.elapsed_seconds, 0)}s elapsed
              {status.duration_seconds != null && (
                <> · {fmtNumber(status.duration_seconds, 0)}s long</>
              )}
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={onOpenLive}
              className="inline-flex items-center gap-1 rounded-md border border-sky-500/40 bg-sky-500/10 px-2 py-1 text-xs font-medium text-sky-300 hover:bg-sky-500/20"
            >
              <PlayCircle className="h-3.5 w-3.5" />
              Live view
            </button>
            <button
              type="button"
              onClick={onStop}
              disabled={stopping}
              className="inline-flex items-center gap-1 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs font-medium text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
            >
              {stopping ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Square className="h-3.5 w-3.5" />
              )}
              Stop
            </button>
          </div>
        </div>

        {pct != null && (
          <div className="mt-4">
            <div className="h-2 overflow-hidden rounded-full bg-ink-700">
              <div
                className="h-full bg-sky-500 transition-all"
                style={{ width: `${Math.min(100, pct)}%` }}
              />
            </div>
            <div className="mt-1 text-right text-[11px] text-slate-500 tabular-nums">
              {pct.toFixed(0)}%
            </div>
          </div>
        )}

        <div className="mt-4 grid grid-cols-3 gap-3 border-t border-ink-700 pt-3">
          <Metric label="Birds (latest)" value={fmtInt(status.bird_count)} />
          <Metric label="Huddling" value={fmtPct(status.huddling_score, 0)} />
          <Metric
            label="Est. weight"
            value={`${fmtNumber(status.estimated_avg_weight_g, 0)} g`}
          />
        </div>
      </div>
    );
  }

  if (status.last_completed_video) {
    return (
      <div className="card border-emerald-500/30">
        <div className="flex items-center gap-2 text-sm">
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          <div>
            <div className="text-slate-100">
              Last demo:{" "}
              <span className="font-semibold">
                {status.last_completed_video}
              </span>
            </div>
            <div className="text-xs text-slate-500">
              Completed{" "}
              {status.completed_at
                ? new Date(status.completed_at).toLocaleString()
                : ""}
              . Pick another recording below to start a new run.
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="card text-sm text-slate-400">
      <div className="text-slate-100">No demo running.</div>
      <div className="mt-1 text-xs text-slate-500">
        Demos replay a recorded video through the live inference pipeline.
        Bird counts, huddling and weight estimates appear in real time. Demo
        events are tagged <code className="text-slate-300">role: demo</code>{" "}
        and never reach the cloud.
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

interface VideoCardProps {
  video: DemoVideoView;
  running: boolean;
  activeVideo: string | null;
  onStart: () => void;
  starting: boolean;
}

function VideoCard({
  video,
  running,
  activeVideo,
  onStart,
  starting,
}: VideoCardProps) {
  const isActive = running && activeVideo === video.name;
  const canStart = !running && !starting;

  return (
    <div className={`card ${isActive ? "border-sky-500/40" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <Film className="h-4 w-4 text-violet-400" />
            <span className="truncate" title={video.name}>
              {video.name}
            </span>
            {isActive && (
              <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-sky-300">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-400" />
                running
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500 tabular-nums">
            {video.width && video.height && (
              <span>
                {video.width}×{video.height}
              </span>
            )}
            {video.fps != null && <span>{video.fps.toFixed(1)} fps</span>}
            {video.duration_seconds != null && (
              <span>{video.duration_seconds.toFixed(0)} s</span>
            )}
            <span>{(video.size_bytes / 1024 / 1024).toFixed(1)} MB</span>
          </div>
        </div>
        <button
          type="button"
          onClick={onStart}
          disabled={!canStart}
          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-40"
          title={
            running && !isActive
              ? "Stop the running demo first"
              : isActive
                ? "Already running"
                : "Replay this video through the pipeline"
          }
        >
          {starting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <PlayCircle className="h-3.5 w-3.5" />
          )}
          {isActive ? "Active" : "Start"}
        </button>
      </div>
    </div>
  );
}

interface MetricProps {
  label: string;
  value: string;
}

function Metric({ label, value }: MetricProps) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-0.5 text-lg font-semibold text-slate-100 tabular-nums">
        {value}
      </div>
    </div>
  );
}

function progressPct(s: DemoStatusView): number | null {
  if (s.elapsed_seconds == null || s.duration_seconds == null) return null;
  if (s.duration_seconds <= 0) return null;
  return (s.elapsed_seconds / s.duration_seconds) * 100;
}
