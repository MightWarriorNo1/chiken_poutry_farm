"""StubWeightEstimator emits schema-valid WeightEstimate events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.models.stub_weight_estimator import StubWeightEstimator

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "events"


def _frame() -> Frame:
    return Frame(
        camera_id="cam-1",
        captured_at=datetime.now(timezone.utc),
        width=1280,
        height=720,
        image=None,
    )


def _detection() -> BirdDetection:
    return BirdDetection(
        device_id="edge-1",
        camera_id="cam-1",
        shed_id="shed-1",
        flock_id="flock-A",
        captured_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        model_version="bird-detector@stub-0.0.1",
        bird_count=80,
        density_score=0.4,
        confidence=0.9,
    )


@pytest.mark.asyncio
async def test_stub_emits_fixed_visible_value() -> None:
    est = StubWeightEstimator()
    result = await est.estimate(
        _frame(), _detection(), bird_age_days=28, breed="ross_308"
    )
    assert result.estimated_avg_weight_g == 1500.0
    assert result.confidence == 0.05  # low so dashboards can filter
    assert result.sample_size == 80
    assert result.flock_id == "flock-A"
    assert result.model_version == "weight-estimator@stub-0.0.1"


@pytest.mark.asyncio
async def test_stub_validates_against_schema() -> None:
    est = StubWeightEstimator()
    result = await est.estimate(_frame(), _detection(), bird_age_days=28, breed="ross_308")
    payload = result.model_copy(update={"device_id": "edge-1"}).model_dump(mode="json")
    schema = json.loads((CONTRACTS / "weight_estimate.schema.json").read_text())
    jsonschema.validate(payload, schema)
