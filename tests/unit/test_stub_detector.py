"""StubBirdDetector emits schema-valid BirdDetections."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from edge.capture.source import Frame
from edge.inference.models.stub_detector import StubBirdDetector

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "events"


def _make_frame() -> Frame:
    return Frame(
        camera_id="cam-1",
        captured_at=datetime.now(timezone.utc),
        width=1280,
        height=720,
        image=None,  # detector doesn't read pixels
    )


@pytest.mark.asyncio
async def test_stub_returns_valid_detection() -> None:
    det = StubBirdDetector(seed=1)
    result = await det.detect(_make_frame())

    # Domain assertions
    assert 0 < result.bird_count
    assert 0.0 <= result.density_score <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.bbox_centroids) == result.bird_count
    assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in result.bbox_centroids)
    assert result.model_version.startswith("bird-detector@")

    # Wire-format assertion: must validate against the contract once device_id is set.
    payload = result.model_copy(update={"device_id": "edge-1"}).model_dump(mode="json")
    schema = json.loads((CONTRACTS / "bird_detection.schema.json").read_text())
    jsonschema.validate(payload, schema)


@pytest.mark.asyncio
async def test_stub_is_deterministic_with_seed() -> None:
    a = StubBirdDetector(seed=42)
    b = StubBirdDetector(seed=42)
    da = await a.detect(_make_frame())
    db = await b.detect(_make_frame())
    assert da.bird_count == db.bird_count
    assert da.confidence == db.confidence
