"""Built-in alert rules."""

from edge.alerts.rules.camera_offline import CameraOfflineRule
from edge.alerts.rules.high_huddling import HighHuddlingRule
from edge.alerts.rules.sensor_out_of_range import SensorOutOfRangeRule
from edge.alerts.rules.weight_below_target import WeightBelowTargetRule

__all__ = [
    "CameraOfflineRule",
    "HighHuddlingRule",
    "SensorOutOfRangeRule",
    "WeightBelowTargetRule",
]
