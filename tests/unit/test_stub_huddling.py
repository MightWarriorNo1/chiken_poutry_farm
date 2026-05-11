"""StubHuddlingDetector emits a schema-valid HuddlingScore."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.models.stub_huddling import StubHuddlingDetector

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
        zone_id="zone-A",
        captured_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        model_version="bird-detector@stub-0.0.1",
        bird_count=50,
        density_score=0.3,
        confidence=0.8,
    )


@pytest.mark.asyncio
async def test_stub_returns_constant_low_score() -> None:
    det = StubHuddlingDetector()
    result = await det.score(_frame(), _detection())
    assert result.huddling_score == 0.1
    assert result.cluster_count == 0
    assert result.largest_cluster_pct == 0.0
    assert result.zone_id == "zone-A"
    assert result.model_version == "huddling-detector@stub-0.0.1"


@pytest.mark.asyncio
async def test_stub_validates_against_schema() -> None:
    det = StubHuddlingDetector()
    result = await det.score(_frame(), _detection())
    payload = result.model_copy(update={"device_id": "edge-1"}).model_dump(mode="json")
    schema = json.loads((CONTRACTS / "huddling_score.schema.json").read_text())
    jsonschema.validate(payload, schema)
