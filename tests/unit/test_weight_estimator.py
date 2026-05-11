"""HeuristicWeightEstimator — interpolation, breed fallback, confidence math."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.model_loader import ModelDescriptor
from edge.inference.models.weight_estimator import HeuristicWeightEstimator


def _descriptor(tmp_path: Path, **meta_overrides) -> ModelDescriptor:
    meta = {
        "name": "weight-estimator",
        "version": "0.1.0",
        "default_breed": "ross_308",
        "baseline_confidence": 0.4,
        "growth_curves": {
            "ross_308": [[1, 42], [28, 1620], [42, 3050]],
            "cobb_500": [[1, 40], [28, 1580], [42, 3000]],
        },
        **meta_overrides,
    }
    fake_artifact = tmp_path / "model.json"
    fake_artifact.write_text("{}")
    return ModelDescriptor(
        name="weight-estimator",
        version="0.1.0",
        artifact_path=fake_artifact,
        metadata=meta,
    )


def _frame() -> Frame:
    return Frame(
        camera_id="cam-1",
        captured_at=datetime.now(timezone.utc),
        width=1280,
        height=720,
        image=None,
    )


def _detection(bird_count: int = 100, confidence: float = 0.8) -> BirdDetection:
    return BirdDetection(
        device_id="edge-1",
        camera_id="cam-1",
        shed_id="shed-1",
        flock_id="flock-A",
        captured_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        model_version="bird-detector@stub-0.0.1",
        bird_count=bird_count,
        density_score=0.5,
        confidence=confidence,
    )


@pytest.mark.asyncio
async def test_known_breed_and_age_interpolates(tmp_path: Path) -> None:
    est = HeuristicWeightEstimator(_descriptor(tmp_path))
    # Halfway between (28, 1620) and (42, 3050) → age=35, weight ≈ 2335
    result = await est.estimate(_frame(), _detection(), bird_age_days=35, breed="ross_308")
    assert result.estimated_avg_weight_g == pytest.approx(2335.0, abs=1.0)
    assert result.bird_age_days == 35
    assert result.breed == "ross_308"


@pytest.mark.asyncio
async def test_age_below_first_point_clamps(tmp_path: Path) -> None:
    est = HeuristicWeightEstimator(_descriptor(tmp_path))
    result = await est.estimate(_frame(), _detection(), bird_age_days=0, breed="ross_308")
    assert result.estimated_avg_weight_g == 42.0  # clamped to first point


@pytest.mark.asyncio
async def test_age_above_last_point_clamps(tmp_path: Path) -> None:
    est = HeuristicWeightEstimator(_descriptor(tmp_path))
    result = await est.estimate(_frame(), _detection(), bird_age_days=999, breed="ross_308")
    assert result.estimated_avg_weight_g == 3050.0  # clamped to last point


@pytest.mark.asyncio
async def test_unknown_breed_falls_back_to_default(tmp_path: Path) -> None:
    est = HeuristicWeightEstimator(_descriptor(tmp_path))
    out_default = await est.estimate(_frame(), _detection(), bird_age_days=28, breed="ross_308")
    out_unknown = await est.estimate(_frame(), _detection(), bird_age_days=28, breed="dodo")
    # Default breed is ross_308, so the unknown breed should fall back to its curve.
    assert out_default.estimated_avg_weight_g == out_unknown.estimated_avg_weight_g


@pytest.mark.asyncio
async def test_breed_normalization(tmp_path: Path) -> None:
    est = HeuristicWeightEstimator(_descriptor(tmp_path))
    # "Ross 308" should match "ross_308" after normalization.
    a = await est.estimate(_frame(), _detection(), bird_age_days=28, breed="Ross 308")
    b = await est.estimate(_frame(), _detection(), bird_age_days=28, breed="ross_308")
    assert a.estimated_avg_weight_g == b.estimated_avg_weight_g


@pytest.mark.asyncio
async def test_missing_age_returns_zero_with_zero_confidence(tmp_path: Path) -> None:
    est = HeuristicWeightEstimator(_descriptor(tmp_path))
    result = await est.estimate(_frame(), _detection(), bird_age_days=None, breed="ross_308")
    assert result.estimated_avg_weight_g == 0.0
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_confidence_is_baseline_times_detection_confidence(tmp_path: Path) -> None:
    est = HeuristicWeightEstimator(_descriptor(tmp_path))
    result = await est.estimate(
        _frame(), _detection(confidence=0.9), bird_age_days=28, breed="ross_308"
    )
    assert result.confidence == pytest.approx(0.4 * 0.9, abs=0.001)


@pytest.mark.asyncio
async def test_propagates_flock_and_shed_from_detection(tmp_path: Path) -> None:
    est = HeuristicWeightEstimator(_descriptor(tmp_path))
    result = await est.estimate(_frame(), _detection(), bird_age_days=28, breed="ross_308")
    assert result.flock_id == "flock-A"
    assert result.shed_id == "shed-1"
    assert result.sample_size == 100


@pytest.mark.asyncio
async def test_empty_metadata_uses_builtin_curves(tmp_path: Path) -> None:
    est = HeuristicWeightEstimator(_descriptor(tmp_path, growth_curves={}))
    result = await est.estimate(_frame(), _detection(), bird_age_days=28, breed="ross_308")
    # Falls back to _BUILTIN_CURVES['ross_308'] which includes (28, 1620).
    assert result.estimated_avg_weight_g == 1620.0
