"""ManualWeightSample domain type validates against the wire schema."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from edge.domain.manual_weight import ManualWeightSample

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "events"


def test_minimal_round_trips_to_schema() -> None:
    sample = ManualWeightSample(
        device_id="edge-1",
        flock_id="flock-A",
        sampled_at=datetime.now(timezone.utc),
        sample_count=50,
        average_weight_g=1620.5,
    )
    payload = sample.model_dump(mode="json")
    schema = json.loads((CONTRACTS / "manual_weight_sample.schema.json").read_text())
    jsonschema.validate(payload, schema)


def test_full_round_trips_to_schema() -> None:
    sample = ManualWeightSample(
        device_id="edge-1",
        flock_id="flock-A",
        shed_id="shed-1",
        sampled_at=datetime.now(timezone.utc),
        flock_age_days=28,
        sample_count=50,
        average_weight_g=1620.5,
        min_weight_g=1450.0,
        max_weight_g=1820.0,
        notes="Wet litter near drinker line",
        operator="Maria S.",
    )
    payload = sample.model_dump(mode="json")
    schema = json.loads((CONTRACTS / "manual_weight_sample.schema.json").read_text())
    jsonschema.validate(payload, schema)


@pytest.mark.parametrize("invalid", [
    {"sample_count": 0},               # below minimum
    {"average_weight_g": -1},          # negative
    {"flock_age_days": -1},
])
def test_rejects_invalid_values(invalid: dict) -> None:
    base = {
        "device_id": "edge-1",
        "flock_id": "flock-A",
        "sampled_at": datetime.now(timezone.utc),
        "sample_count": 50,
        "average_weight_g": 1620.5,
    }
    with pytest.raises(Exception):
        ManualWeightSample(**{**base, **invalid})
