"""AI inference results — mirror contracts/events/*.schema.json exactly."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class _BaseAIResult(BaseModel):
    """Common fields for every AI inference event."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    device_id: str
    camera_id: str
    shed_id: str | None = None
    flock_id: str | None = None
    zone_id: str | None = None
    captured_at: datetime
    processed_at: datetime
    model_version: str
    snapshot_uri: str | None = None


class BirdDetection(_BaseAIResult):
    bird_count: int = Field(ge=0)
    density_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    bbox_centroids: list[tuple[float, float]] = Field(default_factory=list)
    # Per-bird bounding boxes in (cx, cy, w, h), all normalized to [0, 1] in
    # image coordinates. Empty for legacy events / stubs that didn't populate
    # them; consumers should fall back gracefully when missing. Length, when
    # non-empty, matches `bbox_centroids` 1-to-1.
    bboxes: list[tuple[float, float, float, float]] = Field(default_factory=list)


class WeightEstimate(_BaseAIResult):
    estimated_avg_weight_g: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    sample_size: int = Field(ge=0, default=0)
    bird_age_days: int | None = Field(default=None, ge=0)
    breed: str | None = None


class HuddlingScore(_BaseAIResult):
    huddling_score: float = Field(ge=0, le=1)
    cluster_count: int = Field(ge=0, default=0)
    largest_cluster_pct: float = Field(ge=0, le=1, default=0.0)
