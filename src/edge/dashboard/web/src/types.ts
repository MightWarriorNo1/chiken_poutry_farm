// Mirrors the pydantic response models in `src/edge/dashboard/views.py`.
// Kept hand-written (small enough) rather than codegen'd from OpenAPI to keep
// the build pipeline simple.

export interface AIModelView {
  name: string;
  version: string;
}

export interface StatusView {
  device_id: string;
  device_name?: string | null;
  software_version: string;
  status: string;
  reported_at?: string | null;
  cpu_pct?: number | null;
  memory_pct?: number | null;
  storage_pct?: number | null;
  outbox_pending: number;
  ai_models: AIModelView[];
  camera_count: number;
  sensor_count: number;
  open_alert_count: number;
}

export interface CameraView {
  camera_id: string;
  shed_id?: string | null;
  flock_id?: string | null;
  zone_id?: string | null;
  model_version?: string | null;
  bird_count?: number | null;
  density_score?: number | null;
  confidence?: number | null;
  last_frame_at?: string | null;
  snapshot_uri?: string | null;
  huddling_score?: number | null;
  cluster_count?: number | null;
  largest_cluster_pct?: number | null;
  huddling_at?: string | null;
  estimated_avg_weight_g?: number | null;
  weight_confidence?: number | null;
  bird_age_days?: number | null;
  breed?: string | null;
  weight_at?: string | null;
}

export interface TimePoint {
  t: string;
  values: Record<string, number>;
}

export interface CameraSeriesView {
  camera_id: string;
  bird_count: TimePoint[];
  huddling: TimePoint[];
}

export interface SensorView {
  sensor_id: string;
  sensor_type: string;
  shed_id?: string | null;
  zone_id?: string | null;
  value?: number | null;
  unit?: string | null;
  recorded_at?: string | null;
  quality?: string | null;
  threshold_min?: number | null;
  threshold_max?: number | null;
  in_range?: boolean | null;
}

export interface SensorSeriesView {
  sensor_id: string;
  points: TimePoint[];
}

export interface AlertView {
  event_id: string;
  alert_type: string;
  severity: string;
  source: string;
  raised_at: string;
  message: string;
  shed_id?: string | null;
  zone_id?: string | null;
  flock_id?: string | null;
  camera_id?: string | null;
  sensor_id?: string | null;
  snapshot_uri?: string | null;
  correlation_key?: string | null;
  metrics: Record<string, unknown>;
}

export interface ManualWeightView {
  event_id: string;
  flock_id: string;
  shed_id?: string | null;
  sampled_at: string;
  flock_age_days?: number | null;
  sample_count: number;
  average_weight_g: number;
  min_weight_g?: number | null;
  max_weight_g?: number | null;
  notes?: string | null;
  operator?: string | null;
}

export interface LiveEventView {
  type: string;
  at: string;
  payload: Record<string, unknown>;
}
