import type {
  AlertView,
  CameraSeriesView,
  CameraView,
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

export const api = {
  status: () => getJSON<StatusView>("/api/status"),
  cameras: () => getJSON<CameraView[]>("/api/cameras"),
  cameraSeries: (cameraId: string, limit = 100) =>
    getJSON<CameraSeriesView>(
      `/api/cameras/${encodeURIComponent(cameraId)}/series?limit=${limit}`,
    ),
  sensors: () => getJSON<SensorView[]>("/api/sensors"),
  sensorSeries: (sensorId: string, limit = 100) =>
    getJSON<SensorSeriesView>(
      `/api/sensors/${encodeURIComponent(sensorId)}/series?limit=${limit}`,
    ),
  alerts: (limit = 50) => getJSON<AlertView[]>(`/api/alerts?limit=${limit}`),
  manualWeights: (limit = 20) =>
    getJSON<ManualWeightView[]>(`/api/manual-weights?limit=${limit}`),
};
