"""Alert — operational signal raised by the edge for the cloud to surface.

The edge only ever emits alerts in the **open** state. Lifecycle (acknowledge /
resolve / mark false-positive) lives in the cloud — the dashboard owns it.

Repeat alerts for the same condition share a `correlation_key` so the cloud can
deduplicate / count them without each event having to be unique.
"""

from __future__ import annotations

from datetime import datetime
from edge._compat import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class AlertSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertSource(StrEnum):
    CAMERA = "camera"
    SENSOR = "sensor"
    AI = "ai"
    DEVICE = "device"


class AlertType(StrEnum):
    CAMERA_OFFLINE = "camera_offline"
    SENSOR_OFFLINE = "sensor_offline"
    SENSOR_OUT_OF_RANGE = "sensor_out_of_range"
    HIGH_HUDDLING = "high_huddling"
    WEIGHT_BELOW_TARGET = "weight_below_target"
    EDGE_DEVICE_DEGRADED = "edge_device_degraded"
    EDGE_DEVICE_OFFLINE = "edge_device_offline"  # cloud-side detected; defined for shared vocab
    INFERENCE_SWAP_FAILURE = "inference_swap_failure"


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    device_id: str
    alert_type: AlertType
    severity: AlertSeverity
    source: AlertSource
    raised_at: datetime
    message: str

    # Context — populated where available so the cloud can show "where".
    shed_id: str | None = None
    zone_id: str | None = None
    flock_id: str | None = None
    camera_id: str | None = None
    sensor_id: str | None = None

    # Evidence
    snapshot_uri: str | None = None

    # Cloud uses this to deduplicate / count repeats. Pattern: "<rule_name>:<entity>".
    correlation_key: str | None = None

    # Free-form structured data (the values that triggered the alert).
    metrics: dict[str, Any] = Field(default_factory=dict)
