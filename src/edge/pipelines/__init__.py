"""Pipelines: long-running coroutines wired up by main.py."""

from edge.pipelines.config_pipeline import ConfigPipeline
from edge.pipelines.frame_pipeline import FramePipeline
from edge.pipelines.heartbeat_pipeline import HeartbeatPipeline
from edge.pipelines.sensor_pipeline import SensorPipeline
from edge.pipelines.sync_pipeline import SyncPipeline

__all__ = [
    "ConfigPipeline",
    "FramePipeline",
    "HeartbeatPipeline",
    "SensorPipeline",
    "SyncPipeline",
]
