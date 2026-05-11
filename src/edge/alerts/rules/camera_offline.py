"""Camera-offline rule.

State: per-camera last-seen timestamp + dedup tracker.
Trigger: tick fires when (now - last_seen) ≥ threshold for any known camera.
Recovery: any new frame from a camera resets its dedup so the next outage
re-alerts immediately rather than waiting for the cooldown to expire.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from edge.alerts.rule import RaisedTracker
from edge.alerts.rules._helpers import parse_iso
from edge.domain.alert import Alert, AlertSeverity, AlertSource, AlertType
from edge.domain.events import EventEnvelope, EventType


class CameraOfflineRule:
    name = "camera_offline"

    def __init__(
        self,
        device_id: str,
        threshold_seconds: float = 60.0,
        cooldown_seconds: float = 300.0,
    ) -> None:
        self._device_id = device_id
        self._threshold = threshold_seconds
        self._tracker = RaisedTracker(cooldown_seconds)
        self._last_seen: dict[str, datetime] = {}
        self._meta: dict[str, dict[str, str | None]] = {}

    async def on_event(self, event: EventEnvelope) -> Sequence[Alert]:
        if event.event_type != EventType.BIRD_DETECTION:
            return []
        camera_id = event.payload.get("camera_id")
        captured_at = parse_iso(event.payload.get("captured_at"))
        if not camera_id or captured_at is None:
            return []
        self._last_seen[camera_id] = captured_at
        self._meta[camera_id] = {
            "shed_id": event.payload.get("shed_id"),
            "zone_id": event.payload.get("zone_id"),
            "flock_id": event.payload.get("flock_id"),
        }
        # The camera is alive — clear any prior cooldown so the next outage alerts.
        self._tracker.reset(self._key(camera_id))
        return []

    async def tick(self, now: datetime) -> Sequence[Alert]:
        alerts: list[Alert] = []
        for camera_id, last in self._last_seen.items():
            elapsed = (now - last).total_seconds()
            if elapsed < self._threshold:
                continue
            key = self._key(camera_id)
            if not self._tracker.should_raise(key, now):
                continue
            meta = self._meta.get(camera_id, {})
            alerts.append(
                Alert(
                    device_id=self._device_id,
                    alert_type=AlertType.CAMERA_OFFLINE,
                    severity=AlertSeverity.HIGH,
                    source=AlertSource.CAMERA,
                    camera_id=camera_id,
                    shed_id=meta.get("shed_id"),
                    zone_id=meta.get("zone_id"),
                    flock_id=meta.get("flock_id"),
                    raised_at=now,
                    message=(
                        f"Camera {camera_id} has not produced a frame for "
                        f"{elapsed:.0f}s (threshold {self._threshold:.0f}s)."
                    ),
                    correlation_key=key,
                    metrics={
                        "elapsed_seconds": round(elapsed, 1),
                        "threshold_seconds": self._threshold,
                    },
                )
            )
        return alerts

    @classmethod
    def _key(cls, camera_id: str) -> str:
        return f"{cls.name}:{camera_id}"
