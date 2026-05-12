"""Response models for the local dashboard API.

These are the shape the React UI consumes. They intentionally do **not** import
from `domain/` directly — the dashboard is a read side, and decoupling lets us
denormalize / rename fields for display without leaking UI concerns into domain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


# ── Status (Overview tab) ───────────────────────────────────────────────────


class AIModelView(_View):
    name: str
    version: str


class StatusView(_View):
    device_id: str
    device_name: str | None = None
    software_version: str
    status: str = "unknown"               # healthy | degraded | error | unknown
    reported_at: datetime | None = None
    cpu_pct: float | None = None
    memory_pct: float | None = None
    storage_pct: float | None = None
    outbox_pending: int = 0
    ai_models: list[AIModelView] = Field(default_factory=list)
    camera_count: int = 0
    sensor_count: int = 0
    open_alert_count: int = 0


# ── Cameras tab ─────────────────────────────────────────────────────────────


class CameraView(_View):
    camera_id: str
    shed_id: str | None = None
    flock_id: str | None = None
    zone_id: str | None = None
    model_version: str | None = None

    # Latest bird detection
    bird_count: int | None = None
    density_score: float | None = None
    confidence: float | None = None
    last_frame_at: datetime | None = None
    snapshot_uri: str | None = None

    # Latest huddling
    huddling_score: float | None = None
    cluster_count: int | None = None
    largest_cluster_pct: float | None = None
    huddling_at: datetime | None = None

    # Latest weight (per-flock but exposed at camera level for the UI)
    estimated_avg_weight_g: float | None = None
    weight_confidence: float | None = None
    bird_age_days: int | None = None
    breed: str | None = None
    weight_at: datetime | None = None


class TimePoint(_View):
    """One point on a sparkline."""

    t: datetime
    # All series stuff their numeric measurement(s) into `values`.
    values: dict[str, float] = Field(default_factory=dict)


class CameraSeriesView(_View):
    camera_id: str
    bird_count: list[TimePoint] = Field(default_factory=list)
    huddling: list[TimePoint] = Field(default_factory=list)


# ── Sensors tab ─────────────────────────────────────────────────────────────


class SensorView(_View):
    sensor_id: str
    sensor_type: str
    shed_id: str | None = None
    zone_id: str | None = None
    value: float | None = None
    unit: str | None = None
    recorded_at: datetime | None = None
    quality: str | None = None
    # Populated from EdgeConfig (passed in by the server layer at request time).
    threshold_min: float | None = None
    threshold_max: float | None = None
    in_range: bool | None = None


class SensorSeriesView(_View):
    sensor_id: str
    points: list[TimePoint] = Field(default_factory=list)


# ── Alerts tab ──────────────────────────────────────────────────────────────


class AlertView(_View):
    event_id: str
    alert_type: str
    severity: str
    source: str
    raised_at: datetime
    message: str
    shed_id: str | None = None
    zone_id: str | None = None
    flock_id: str | None = None
    camera_id: str | None = None
    sensor_id: str | None = None
    snapshot_uri: str | None = None
    correlation_key: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


# ── Manual weights (Growth tab) ─────────────────────────────────────────────


class ManualWeightView(_View):
    event_id: str
    flock_id: str
    shed_id: str | None = None
    sampled_at: datetime
    flock_age_days: int | None = None
    sample_count: int
    average_weight_g: float
    min_weight_g: float | None = None
    max_weight_g: float | None = None
    notes: str | None = None
    operator: str | None = None


# ── Live feed (SSE) ─────────────────────────────────────────────────────────


class LiveEventView(_View):
    """One frame on the SSE stream — minimal so the UI can patch local caches."""

    type: str          # event_type
    at: datetime
    payload: dict[str, Any]


# ── Cameras: source/type browser (Phase 2) ──────────────────────────────────


class CameraSourceView(_View):
    """Configured-camera surface for the type-filter UI.

    Sourced from CameraSupervisor (config-driven) and decorated with live
    status from the FrameBroadcaster (has-frames / has-viewers). Decoupled
    from CameraView, which is detection-driven and only populates after the
    first inference event lands in the read model.
    """

    camera_id: str
    source_uri: str
    source_type: str           # rtsp | http | usb | csi | gstreamer | file | unknown
    source_type_label: str
    role: str | None = None    # "demo" for demo cameras, None otherwise
    shed_id: str | None = None
    zone_id: str | None = None
    flock_id: str | None = None

    running: bool = False
    has_frames: bool = False   # broadcaster has produced at least one annotated frame
    viewer_count_hint: int = 0  # 0 or 1; 1 means at least one live-view tab is open
    stream_url: str | None = None


# ── Demo tab (Phase 3) ──────────────────────────────────────────────────────


class DemoVideoView(_View):
    """One recorded video that can be replayed through the pipeline."""

    name: str                  # bare filename, used as the start() identifier
    path: str                  # absolute path on the device, for logs/debug
    size_bytes: int
    duration_seconds: float | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None
    frame_count: int | None = None


class DemoImageView(_View):
    """One test image that can be looped through the pipeline."""

    name: str                  # bare filename, used as the start_image() identifier
    path: str                  # absolute path on the device, for logs/debug
    size_bytes: int
    width: int | None = None
    height: int | None = None


class DemoStatusView(_View):
    """Snapshot of the demo subsystem — one running demo at a time."""

    running: bool
    kind: str | None = None            # "video" | "image" when running
    video: str | None = None           # set when a video demo is running
    image: str | None = None           # set when an image demo is running
    camera_id: str | None = None       # always "demo" when running
    started_at: datetime | None = None
    elapsed_seconds: float | None = None
    duration_seconds: float | None = None
    frame_count: int | None = None
    bird_count: int | None = None      # latest bird count for the demo camera
    huddling_score: float | None = None
    estimated_avg_weight_g: float | None = None
    completed_at: datetime | None = None
    last_completed_video: str | None = None
    last_completed_image: str | None = None
    stream_url: str | None = None


class DemoStartRequest(_View):
    """Body of POST /api/demo/start."""

    video: str


class DemoStartImageRequest(_View):
    """Body of POST /api/demo/start-image."""

    image: str


# ── Sources / camera discovery (Phase 4) ────────────────────────────────────


class DiscoveredDeviceView(_View):
    """One auto-discovered camera. Fields populated per-type; missing = None."""

    source_type: str                # usb | csi | rtsp | file
    name: str
    suggested_source_uri: str | None = None
    # USB
    device: str | None = None
    # CSI
    sensor_id: int | None = None
    # RTSP / ONVIF
    ip: str | None = None
    xaddr: str | None = None
    requires_auth: bool | None = None
    # File
    size_bytes: int | None = None
    # Common probe data
    width: int | None = None
    height: int | None = None
    fps: float | None = None


class AdhocStartRequest(_View):
    """Body of POST /api/cameras/adhoc/start."""

    source_type: str
    source_uri: str
    label: str | None = None


class AdhocStatusView(_View):
    """Snapshot of the ad-hoc subsystem — one running camera at a time."""

    running: bool
    camera_id: str | None = None
    source_type: str | None = None
    source_uri: str | None = None
    label: str | None = None
    started_at: datetime | None = None
    elapsed_seconds: float | None = None
    stream_url: str | None = None

