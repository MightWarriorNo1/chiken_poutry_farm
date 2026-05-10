"""Domain types validate the wire contract."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from edge.domain.detection import BirdDetection, HuddlingScore, WeightEstimate
from edge.domain.device import DeviceHeartbeat, DeviceStatus
from edge.domain.reading import SensorReading, SensorType

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "events"


def _schema(name: str) -> dict:
    return json.loads((CONTRACTS / f"{name}.schema.json").read_text())


def test_bird_detection_round_trips_to_schema() -> None:
    event = BirdDetection(
        device_id="edge-1",
        camera_id="cam-1",
        captured_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        model_version="bird-detector@1.0.0",
        bird_count=42,
        density_score=0.5,
        confidence=0.91,
    )
    payload = event.model_dump(mode="json")
    jsonschema.validate(payload, _schema("bird_detection"))


def test_weight_estimate_round_trips_to_schema() -> None:
    event = WeightEstimate(
        device_id="edge-1",
        camera_id="cam-1",
        flock_id="flock-A",
        captured_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        model_version="weight-estimator@0.1.0",
        estimated_avg_weight_g=1850.0,
        confidence=0.7,
    )
    jsonschema.validate(event.model_dump(mode="json"), _schema("weight_estimate"))


def test_huddling_score_round_trips_to_schema() -> None:
    event = HuddlingScore(
        device_id="edge-1",
        camera_id="cam-1",
        captured_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        model_version="huddling@0.1.0",
        huddling_score=0.3,
    )
    jsonschema.validate(event.model_dump(mode="json"), _schema("huddling_score"))


def test_sensor_reading_round_trips_to_schema() -> None:
    reading = SensorReading(
        device_id="edge-1",
        sensor_id="temp-1",
        sensor_type=SensorType.TEMPERATURE,
        value=24.3,
        unit="celsius",
        recorded_at=datetime.now(timezone.utc),
    )
    jsonschema.validate(reading.model_dump(mode="json"), _schema("sensor_reading"))


def test_heartbeat_round_trips_to_schema() -> None:
    hb = DeviceHeartbeat(
        device_id="edge-1",
        reported_at=datetime.now(timezone.utc),
        status=DeviceStatus.HEALTHY,
        software_version="0.1.0",
    )
    jsonschema.validate(hb.model_dump(mode="json"), _schema("device_heartbeat"))


@pytest.mark.parametrize("score", [-0.1, 1.1])
def test_density_score_bounds(score: float) -> None:
    with pytest.raises(Exception):
        BirdDetection(
            device_id="edge-1",
            camera_id="cam-1",
            captured_at=datetime.now(timezone.utc),
            processed_at=datetime.now(timezone.utc),
            model_version="m@1",
            bird_count=1,
            density_score=score,
            confidence=0.5,
        )
