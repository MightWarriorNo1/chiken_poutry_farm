"""Weight-below-target rule.

Self-contained: uses the same growth curves the heuristic estimator uses to
derive an expected weight at this (breed, age), then alerts if the actual
estimate is more than `threshold_pct` below it.

We deliberately ignore low-confidence estimates (default `min_confidence=0.3`)
so the stub estimator at confidence 0.05 never fires this rule.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from edge.alerts.rule import RaisedTracker
from edge.domain.alert import Alert, AlertSeverity, AlertSource, AlertType
from edge.domain.events import EventEnvelope, EventType

# Same curves the heuristic estimator uses — kept here so the rule has no
# runtime dep on the inference module. Update both if you tune one.
_CURVES: dict[str, list[tuple[int, float]]] = {
    "ross_308": [(1, 42), (7, 180), (14, 480), (21, 980), (28, 1620), (35, 2350), (42, 3050)],
    "cobb_500": [(1, 42), (7, 175), (14, 460), (21, 950), (28, 1580), (35, 2300), (42, 3000)],
    "hubbard_classic": [(1, 41), (7, 170), (14, 450), (21, 920), (28, 1540), (35, 2240), (42, 2920)],
}
_DEFAULT_BREED = "ross_308"


class WeightBelowTargetRule:
    name = "weight_below_target"

    def __init__(
        self,
        device_id: str,
        threshold_pct: float = 0.15,
        min_confidence: float = 0.3,
        cooldown_seconds: float = 900.0,
    ) -> None:
        self._device_id = device_id
        self._threshold_pct = threshold_pct
        self._min_confidence = min_confidence
        self._tracker = RaisedTracker(cooldown_seconds)

    async def on_event(self, event: EventEnvelope) -> Sequence[Alert]:
        if event.event_type != EventType.WEIGHT_ESTIMATE:
            return []
        p = event.payload
        confidence = float(p.get("confidence") or 0.0)
        if confidence < self._min_confidence:
            return []

        estimated = float(p.get("estimated_avg_weight_g") or 0.0)
        age = p.get("bird_age_days")
        if not isinstance(age, (int, float)):
            return []

        breed = self._normalize_breed(p.get("breed"))
        target = self._target_weight(breed, int(age))
        if not target:
            return []

        gap_pct = (target - estimated) / target
        if gap_pct < self._threshold_pct:
            return []

        flock_id = p.get("flock_id")
        camera_id = p.get("camera_id")
        # Correlate per flock when known — same flock across cameras shouldn't multi-alert.
        correlation_entity = flock_id or camera_id or "unknown"
        key = f"{self.name}:{correlation_entity}"
        now = datetime.now(timezone.utc)
        if not self._tracker.should_raise(key, now):
            return []

        return [
            Alert(
                device_id=self._device_id,
                alert_type=AlertType.WEIGHT_BELOW_TARGET,
                severity=AlertSeverity.MEDIUM,
                source=AlertSource.AI,
                camera_id=camera_id,
                shed_id=p.get("shed_id"),
                flock_id=flock_id,
                raised_at=now,
                message=(
                    f"Estimated weight {estimated:.0f}g is {gap_pct * 100:.0f}% below "
                    f"target {target:.0f}g (breed={breed}, age={int(age)}d)."
                ),
                correlation_key=key,
                metrics={
                    "estimated_g": estimated,
                    "target_g": round(target, 1),
                    "gap_pct": round(gap_pct, 4),
                    "confidence": confidence,
                },
            )
        ]

    async def tick(self, _now: datetime) -> Sequence[Alert]:
        return []

    # ── private ───────────────────────────────────────────────────────────
    @staticmethod
    def _normalize_breed(name: object) -> str:
        if not name:
            return _DEFAULT_BREED
        normalized = str(name).strip().lower().replace(" ", "_").replace("-", "_")
        return normalized if normalized in _CURVES else _DEFAULT_BREED

    @staticmethod
    def _target_weight(breed: str, age: int) -> float | None:
        curve = _CURVES.get(breed) or _CURVES[_DEFAULT_BREED]
        if not curve:
            return None
        if age <= curve[0][0]:
            return float(curve[0][1])
        if age >= curve[-1][0]:
            return float(curve[-1][1])
        for (a1, w1), (a2, w2) in zip(curve, curve[1:], strict=True):
            if a1 <= age <= a2:
                t = (age - a1) / (a2 - a1)
                return w1 + (w2 - w1) * t
        return float(curve[-1][1])
