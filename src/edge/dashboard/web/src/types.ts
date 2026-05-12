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

// ── Phase 2 — camera-source / type browser ─────────────────────────────────

export type CameraSourceType =
  | "rtsp"
  | "http"
  | "usb"
  | "csi"
  | "gstreamer"
  | "file"
  | "unknown";

export interface CameraSourceView {
  camera_id: string;
  source_uri: string;
  source_type: CameraSourceType;
  source_type_label: string;
  role?: string | null;
  shed_id?: string | null;
  zone_id?: string | null;
  flock_id?: string | null;
  running: boolean;
  has_frames: boolean;
  viewer_count_hint: number;
  stream_url?: string | null;
}

// ── Phase 3 — demo subsystem ───────────────────────────────────────────────

export interface DemoVideoView {
  name: string;
  path: string;
  size_bytes: number;
  duration_seconds?: number | null;
  fps?: number | null;
  width?: number | null;
  height?: number | null;
  frame_count?: number | null;
}

export interface DemoImageView {
  name: string;
  path: string;
  size_bytes: number;
  width?: number | null;
  height?: number | null;
}

export interface DemoStatusView {
  running: boolean;
  kind?: "video" | "image" | null;
  video?: string | null;
  image?: string | null;
  camera_id?: string | null;
  started_at?: string | null;
  elapsed_seconds?: number | null;
  duration_seconds?: number | null;
  frame_count?: number | null;
  bird_count?: number | null;
  huddling_score?: number | null;
  estimated_avg_weight_g?: number | null;
  completed_at?: string | null;
  last_completed_video?: string | null;
  last_completed_image?: string | null;
  stream_url?: string | null;
}

export interface DemoRunView {
  id: string;
  kind: "video" | "image";
  name: string;
  started_at: string;
  ended_at?: string | null;
  ended_reason?: "stopped" | "completed" | null;
  frame_count?: number | null;
  bird_count_avg?: number | null;
  bird_count_max?: number | null;
}

// ── Phase 4 — discovery + ad-hoc cameras ───────────────────────────────────

export type DiscoverSourceType = "usb" | "csi" | "rtsp" | "file";

export interface DiscoveredDeviceView {
  source_type: DiscoverSourceType;
  name: string;
  suggested_source_uri?: string | null;
  device?: string | null;
  sensor_id?: number | null;
  ip?: string | null;
  xaddr?: string | null;
  requires_auth?: boolean | null;
  size_bytes?: number | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
}

export interface AdhocStatusView {
  running: boolean;
  camera_id?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  label?: string | null;
  started_at?: string | null;
  elapsed_seconds?: number | null;
  stream_url?: string | null;
}

// ── Phase 5 — inference algorithm selector ─────────────────────────────────

export interface InferenceVersionView {
  version: string;
  algorithm: string;
  display_name: string;
  requires_artifact: boolean;
  artifact_present: boolean;
  available: boolean;
  is_active: boolean;
  notes?: string | null;
}
