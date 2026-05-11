"""Alert domain type validates against the wire schema."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from edge.domain.alert import Alert, AlertSeverity, AlertSource, AlertType

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "events"


def _schema() -> dict:
    return json.loads((CONTRACTS / "alert.schema.json").read_text())


def test_minimal_round_trips_to_schema() -> None:
    alert = Alert(
        device_id="edge-1",
        alert_type=AlertType.CAMERA_OFFLINE,
        severity=AlertSeverity.HIGH,
        source=AlertSource.CAMERA,
        raised_at=datetime.now(timezone.utc),
        message="Camera cam-1 has not produced a frame for 75s.",
    )
    jsonschema.validate(alert.model_dump(mode="json"), _schema())


def test_full_round_trips_to_schema() -> None:
    alert = Alert(
        device_id="edge-1",
        alert_type=AlertType.HIGH_HUDDLING,
        severity=AlertSeverity.HIGH,
        source=AlertSource.AI,
        raised_at=datetime.now(timezone.utc),
        message="Huddling on cam-1",
        shed_id="shed-1",
        zone_id="zone-A",
        flock_id="flock-A",
        camera_id="cam-1",
        snapshot_uri="https://snapshots.example.com/abc.jpg",
        correlation_key="high_huddling:cam-1",
        metrics={"score": 0.84, "threshold": 0.7, "consecutive": 5},
    )
    jsonschema.validate(alert.model_dump(mode="json"), _schema())


@pytest.mark.parametrize(
    "alert_type",
    [
        AlertType.CAMERA_OFFLINE,
        AlertType.SENSOR_OUT_OF_RANGE,
        AlertType.HIGH_HUDDLING,
        AlertType.WEIGHT_BELOW_TARGET,
        AlertType.INFERENCE_SWAP_FAILURE,
    ],
)
def test_all_alert_types_validate(alert_type: AlertType) -> None:
    alert = Alert(
        device_id="edge-1",
        alert_type=alert_type,
        severity=AlertSeverity.MEDIUM,
        source=AlertSource.AI,
        raised_at=datetime.now(timezone.utc),
        message="x",
    )
    jsonschema.validate(alert.model_dump(mode="json"), _schema())
