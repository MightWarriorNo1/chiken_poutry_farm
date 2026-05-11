"""Domain types — pure data, no I/O, safe to import anywhere."""

from edge.domain.alert import Alert, AlertSeverity, AlertSource, AlertType
from edge.domain.detection import BirdDetection, HuddlingScore, WeightEstimate
from edge.domain.device import CameraStatus, DeviceHeartbeat, SensorStatus
from edge.domain.events import EdgeEvent, EventEnvelope, EventType
from edge.domain.manual_weight import ManualWeightSample
from edge.domain.reading import SensorReading, SensorType

__all__ = [
    "Alert",
    "AlertSeverity",
    "AlertSource",
    "AlertType",
    "BirdDetection",
    "CameraStatus",
    "DeviceHeartbeat",
    "EdgeEvent",
    "EventEnvelope",
    "EventType",
    "HuddlingScore",
    "ManualWeightSample",
    "SensorReading",
    "SensorStatus",
    "SensorType",
    "WeightEstimate",
]
