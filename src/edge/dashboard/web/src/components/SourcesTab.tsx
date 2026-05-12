import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Cable,
  CircuitBoard,
  Film,
  Loader2,
  PlayCircle,
  RefreshCw,
  Search,
  Square,
  Wifi,
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import { fmtNumber } from "../format";
import type {
  AdhocStatusView,
  DiscoveredDeviceView,
  DiscoverSourceType,
} from "../types";

/**
 * Sources tab — dropdown of camera types → auto-discover → start ad-hoc.
 *
 * The dropdown drives a per-type "Discover" action. Discovery is on-demand
 * (not on tab mount) because USB/CSI probes briefly open the device and
 * RTSP probes broadcast on the LAN — we don't want either to fire when the
 * user just clicked the tab.
 */
const TYPES: { id: DiscoverSourceType; label: string; hint: string }[] = [
  { id: "usb", label: "USB", hint: "/dev/video* — UVC cameras" },
  { id: "csi", label: "CSI", hint: "nvargus sensor — Jetson ribbon cameras" },
  {
    id: "rtsp",
    label: "RTSP",
    hint: "ONVIF auto-discovery on the local network",
  },
  { id: "file", label: "File", hint: "video files under demo/recordings/" },
];

const ICONS: Record<DiscoverSourceType, ReactNode> = {
  usb: <Cable className="h-4 w-4 text-amber-400" />,
  csi: <CircuitBoard className="h-4 w-4 text-emerald-400" />,
  rtsp: <Wifi className="h-4 w-4 text-sky-400" />,
  file: <Film className="h-4 w-4 text-violet-400" />,
};

export function SourcesTab() {
  const qc = useQueryClient();
  const [selectedType, setSelectedType] = useState<DiscoverSourceType>("usb");

  const discovery = useQuery({
    queryKey: ["discover", selectedType],
    queryFn: () => api.discover(selectedType),
    enabled: false, // user-triggered only
    staleTime: 30_000,
  });

  const adhoc = useQuery({
    queryKey: ["adhoc", "status"],
    queryFn: api.adhocStatus,
    refetchInterval: (q) => (q.state.data?.running ? 1_500 : 5_000),
  });

  const startMut = useMutation({
    mutationFn: api.adhocStart,
    onSuccess: (data) => {
      qc.setQueryData(["adhoc", "status"], data);
      qc.invalidateQueries({ queryKey: ["cameraSources"] });
    },
  });

  const stopMut = useMutation({
    mutationFn: api.adhocStop,
    onSuccess: (data) => {
      qc.setQueryData(["adhoc", "status"], data);
      qc.invalidateQueries({ queryKey: ["cameraSources"] });
    },
  });

  const errorMsg = startMut.error?.message ?? stopMut.error?.message;

  return (
    <div className="space-y-6">
      <AdhocStatusCard
        status={adhoc.data}
        onStop={() => stopMut.mutate()}
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

      <section className="card">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex-1">
            <span className="block text-xs font-semibold uppercase tracking-wider text-slate-500">
              Camera type
            </span>
            <select
              className="mt-1 w-full max-w-xs rounded-md border border-ink-700 bg-ink-950 px-2 py-1.5 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
              value={selectedType}
              onChange={(e) =>
                setSelectedType(e.target.value as DiscoverSourceType)
              }
              disabled={adhoc.data?.running}
            >
              {TYPES.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-[11px] text-slate-500">
              {TYPES.find((t) => t.id === selectedType)?.hint}
            </span>
          </label>
          <button
            type="button"
            onClick={() => discovery.refetch()}
            disabled={discovery.isFetching || adhoc.data?.running}
            className="inline-flex items-center gap-1.5 rounded-md border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 text-sm font-medium text-sky-300 hover:bg-sky-500/20 disabled:opacity-50"
          >
            {discovery.isFetching ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
            Discover
          </button>
        </div>
        {adhoc.data?.running && (
          <div className="mt-3 text-xs text-amber-300">
            Stop the running ad-hoc camera before starting a new one.
          </div>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Discovered ({discovery.data?.length ?? 0})
          </h3>
          {discovery.dataUpdatedAt > 0 && (
            <button
              type="button"
              onClick={() => discovery.refetch()}
              disabled={discovery.isFetching}
              className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50"
            >
              <RefreshCw className="h-3 w-3" />
              Rescan
            </button>
          )}
        </div>
        <DiscoveryList
          loading={discovery.isFetching}
          data={discovery.data}
          startable={!adhoc.data?.running}
          activeUri={adhoc.data?.source_uri ?? null}
          onStart={(d) =>
            d.suggested_source_uri &&
            startMut.mutate({
              source_type: d.source_type,
              source_uri: d.suggested_source_uri,
              label: d.name,
            })
          }
          startingUri={startMut.variables?.source_uri ?? null}
          starting={startMut.isPending}
        />
      </section>

    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

interface AdhocStatusCardProps {
  status: AdhocStatusView | undefined;
  onStop: () => void;
  stopping: boolean;
}

function AdhocStatusCard({ status, onStop, stopping }: AdhocStatusCardProps) {
  // Cache-buster: a new key every time the camera_id changes so re-starting
  // doesn't resurrect the closed MJPEG stream from the browser image cache.
  // useMemo + dependency on camera_id keeps the URL stable for the duration
  // of one running session (otherwise the <img> re-mounts every render and
  // re-connects the MJPEG stream from scratch).
  const streamKey = useMemo(() => Date.now(), [status?.camera_id]);
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    setErrored(false);
  }, [status?.camera_id]);

  if (!status) {
    return (
      <div className="card flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading ad-hoc status…
      </div>
    );
  }

  if (!status.running) {
    return (
      <div className="card text-sm text-slate-400">
        <div className="text-slate-100">No ad-hoc camera running.</div>
        <div className="mt-1 text-xs text-slate-500">
          Pick a camera type below and click <strong>Discover</strong>. Click{" "}
          <strong>Start</strong> on a found device and its annotated live feed
          will appear right here. Ad-hoc events are tagged{" "}
          <code className="text-slate-300">role: adhoc</code> and never reach
          the cloud.
        </div>
      </div>
    );
  }

  const streamSrc = `${api.cameraStreamUrl(status.camera_id ?? "adhoc")}?t=${streamKey}`;

  return (
    <div className="card border-sky-500/40 p-0 overflow-hidden">
      <div className="flex items-start justify-between gap-3 border-b border-ink-700 px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-sky-300">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            Live · ad-hoc
          </div>
          <div className="mt-1 truncate text-base font-semibold text-slate-100">
            {status.label ?? status.source_uri}
          </div>
          <div className="mt-1 truncate text-xs text-slate-500">
            <span className="mr-2 rounded bg-ink-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-slate-300">
              {status.source_type}
            </span>
            <code className="text-slate-400" title={status.source_uri ?? ""}>
              {status.source_uri}
            </code>
            {" · "}
            {fmtNumber(status.elapsed_seconds, 0)}s elapsed
          </div>
        </div>
        <button
          type="button"
          onClick={onStop}
          disabled={stopping}
          className="inline-flex flex-shrink-0 items-center gap-1 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs font-medium text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
        >
          {stopping ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Square className="h-3.5 w-3.5" />
          )}
          Stop
        </button>
      </div>
      <div className="flex items-center justify-center bg-black">
        {errored ? (
          <div className="px-6 py-12 text-center text-sm text-slate-400">
            <div className="font-semibold text-slate-200">
              No live frames yet
            </div>
            <div className="mt-1 max-w-md text-xs text-slate-500">
              The pipeline hasn't produced an annotated frame yet — usually
              this means the camera URI couldn't open, or the first inference
              tick hasn't fired. Wait a few seconds, then refresh, or check
              the <code>prosper-edge</code> logs for{" "}
              <code>frame.process.failed</code>.
            </div>
          </div>
        ) : (
          <img
            src={streamSrc}
            alt={`Live feed from ${status.label ?? status.camera_id}`}
            className="block max-h-[60vh] w-auto"
            onError={() => setErrored(true)}
          />
        )}
      </div>
    </div>
  );
}

interface DiscoveryListProps {
  loading: boolean;
  data: DiscoveredDeviceView[] | undefined;
  startable: boolean;
  activeUri: string | null;
  onStart: (d: DiscoveredDeviceView) => void;
  startingUri: string | null;
  starting: boolean;
}

function DiscoveryList({
  loading,
  data,
  startable,
  activeUri,
  onStart,
  startingUri,
  starting,
}: DiscoveryListProps) {
  if (data === undefined) {
    return (
      <div className="card text-sm text-slate-500">
        Click <strong>Discover</strong> to scan for cameras of the selected
        type.
      </div>
    );
  }
  if (loading) {
    return (
      <div className="card flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Probing… USB/CSI takes ~1s per device, RTSP up to 3s for LAN response.
      </div>
    );
  }
  if (data.length === 0) {
    return (
      <div className="card text-sm text-slate-500">
        Nothing found. For RTSP, check that the camera is on the same subnet
        and supports ONVIF. For CSI, confirm the ribbon cable is seated and{" "}
        <code>nvargus-daemon</code> is running.
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {data.map((d, i) => (
        <DeviceCard
          key={`${d.source_type}-${d.suggested_source_uri ?? d.name}-${i}`}
          device={d}
          startable={startable && !!d.suggested_source_uri}
          starting={starting && startingUri === d.suggested_source_uri}
          active={!!activeUri && activeUri === d.suggested_source_uri}
          onStart={() => onStart(d)}
        />
      ))}
    </div>
  );
}

function DeviceCard({
  device,
  startable,
  starting,
  active,
  onStart,
}: {
  device: DiscoveredDeviceView;
  startable: boolean;
  starting: boolean;
  active: boolean;
  onStart: () => void;
}) {
  const meta: string[] = [];
  if (device.device) meta.push(device.device);
  if (device.sensor_id !== null && device.sensor_id !== undefined)
    meta.push(`sensor-id ${device.sensor_id}`);
  if (device.ip) meta.push(device.ip);
  if (device.width && device.height)
    meta.push(`${device.width}×${device.height}`);
  if (device.fps != null) meta.push(`${device.fps.toFixed(1)} fps`);
  if (device.size_bytes != null)
    meta.push(`${(device.size_bytes / 1024 / 1024).toFixed(1)} MB`);

  return (
    <div className={`card ${active ? "border-sky-500/40" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            {ICONS[device.source_type]}
            <span className="truncate" title={device.name}>
              {device.name}
            </span>
            {active && (
              <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-sky-300">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-400" />
                running
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500 tabular-nums">
            {meta.map((m) => (
              <span key={m}>{m}</span>
            ))}
          </div>
          {device.requires_auth && (
            <div className="mt-1 text-[11px] text-amber-300">
              ONVIF auth required — credentials not yet supported in this UI.
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onStart}
          disabled={!startable || starting}
          className="inline-flex flex-shrink-0 items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-40"
          title={
            !device.suggested_source_uri
              ? "No usable URL — see message above"
              : !startable
                ? "Stop the running ad-hoc camera first"
                : "Start streaming this camera"
          }
        >
          {starting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <PlayCircle className="h-3.5 w-3.5" />
          )}
          {active ? "Active" : "Start"}
        </button>
      </div>
    </div>
  );
}
