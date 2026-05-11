"""Event taxonomy + envelope.

Domain events are the canonical things the edge produces. They are persisted to the
outbox before any network call so we never lose data on a crash or network blip.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """All event kinds the edge can emit. Maps 1:1 to ingest endpoints."""

    BIRD_DETECTION = "bird_detection"
    WEIGHT_ESTIMATE = "weight_estimate"
    HUDDLING_SCORE = "huddling_score"
    SENSOR_READING = "sensor_reading"
    DEVICE_HEARTBEAT = "device_heartbeat"
    MANUAL_WEIGHT_SAMPLE = "manual_weight_sample"
    ALERT = "alert"


class EventEnvelope(BaseModel):
    """Envelope persisted in the outbox.

    `payload` is the JSON-serializable wire format defined in contracts/events/.
    The envelope itself is internal — never sent over the wire.
    """

    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any]
    schema_version: str = "0.1.0"
    attempts: int = 0


# Type alias used by domain producers. Concrete subclasses live alongside.
EdgeEvent = EventEnvelope
