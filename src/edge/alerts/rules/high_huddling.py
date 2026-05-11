"""High huddling rule.

Requires `consecutive_frames` huddle scores ≥ threshold from the same camera
before alerting — single-frame spikes don't trigger anything. A score below
threshold resets the consecutive counter and clears the dedup window.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from edge.alerts.rule import RaisedTracker
from edge.domain.alert import Alert, AlertSeverity, AlertSource, AlertType
from edge.domain.events import EventEnvelope, EventType


class HighHuddlingRule:
    name = "high_huddling"

    def __init__(
        self,
        device_id: str,
        threshold: float = 0.7,
        consecutive_frames: int = 3,
        cooldown_seconds: float = 300.0,
    ) -> None:
        self._device_id = device_id
        self._threshold = threshold
        self._consecutive_required = consecutive_frames
        self._tracker = RaisedTracker(cooldown_seconds)
        self._consecutive: dict[str, int] = {}

    async def on_event(self, event: EventEnvelope) -> Sequence[Alert]:
        if event.event_type != EventType.HUDDLING_SCORE:
            return []
        payload = event.payload
        camera_id = payload.get("camera_id")
        score = payload.get("huddling_score")
        if not camera_id or not isinstance(score, (int, float)):
            return []

        key = self._key(str(camera_id))

        if score < self._threshold:
            self._consecutive[camera_id] = 0
            self._tracker.reset(key)
            return []

        self._consecutive[camera_id] = self._consecutive.get(camera_id, 0) + 1
        if self._consecutive[camera_id] < self._consecutive_required:
            return []

        now = datetime.now(timezone.utc)
        if not self._tracker.should_raise(key, now):
            return []

        return [
            Alert(
                device_id=self._device_id,
                alert_type=AlertType.HIGH_HUDDLING,
                severity=AlertSeverity.HIGH,
                source=AlertSource.AI,
                camera_id=str(camera_id),
                shed_id=payload.get("shed_id"),
                zone_id=payload.get("zone_id"),
                flock_id=payload.get("flock_id"),
                raised_at=now,
                message=(
                    f"Huddling detected: score {score:.2f} ≥ {self._threshold:.2f} "
                    f"for {self._consecutive[camera_id]} consecutive frames "
                    f"on camera {camera_id}."
                ),
                snapshot_uri=payload.get("snapshot_uri"),
                correlation_key=key,
                metrics={
                    "score": float(score),
                    "threshold": self._threshold,
                    "consecutive": self._consecutive[camera_id],
                },
            )
        ]

    async def tick(self, _now: datetime) -> Sequence[Alert]:
        return []

    @classmethod
    def _key(cls, camera_id: str) -> str:
        return f"{cls.name}:{camera_id}"
