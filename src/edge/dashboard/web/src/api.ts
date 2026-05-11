import type {
  AlertView,
  CameraSeriesView,
  CameraSourceView,
  CameraView,
  DemoStatusView,
  DemoVideoView,
  ManualWeightView,
  SensorSeriesView,
  SensorView,
  StatusView,
} from "./types";

// Same origin when served by FastAPI (`/`), or proxied to the Python backend
// in `npm run dev`. Either way, relative URLs work.
async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} from ${path}`);
  return (await r.json()) as T;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body ?? {}),
  });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = (await r.json()) as { detail?: string };
      if (j?.detail) detail = `${detail} — ${j.detail}`;
    } catch {
      /* ignore */
    }
    throw new Error(`${detail} from ${path}`);
  }
  return (await r.json()) as T;
}

export const api = {
  status: () => getJSON<StatusView>("/api/status"),
  cameras: () => getJSON<CameraView[]>("/api/cameras"),
  cameraSeries: (cameraId: string, limit = 100) =>
    getJSON<CameraSeriesView>(
      `/api/cameras/${encodeURIComponent(cameraId)}/series?limit=${limit}`,
    ),
  /** MJPEG live-stream URL — drop this into an <img src=...> tag. */
  cameraStreamUrl: (cameraId: string) =>
    `/api/cameras/${encodeURIComponent(cameraId)}/stream`,
  sensors: () => getJSON<SensorView[]>("/api/sensors"),
  sensorSeries: (sensorId: string, limit = 100) =>
    getJSON<SensorSeriesView>(
      `/api/sensors/${encodeURIComponent(sensorId)}/series?limit=${limit}`,
    ),
  alerts: (limit = 50) => getJSON<AlertView[]>(`/api/alerts?limit=${limit}`),
  manualWeights: (limit = 20) =>
    getJSON<ManualWeightView[]>(`/api/manual-weights?limit=${limit}`),

  // ── Phase 2 — camera type/status browser ────────────────────────────────
  cameraSources: () => getJSON<CameraSourceView[]>("/api/cameras/sources"),

  // ── Phase 3 — demo subsystem ────────────────────────────────────────────
  demoVideos: () => getJSON<DemoVideoView[]>("/api/demo/videos"),
  demoStatus: () => getJSON<DemoStatusView>("/api/demo/status"),
  demoStart: (video: string) =>
    postJSON<DemoStatusView>("/api/demo/start", { video }),
  demoStop: () => postJSON<DemoStatusView>("/api/demo/stop", {}),
};
