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
