"""DbscanHuddlingDetector — clustering behavior on synthetic patterns."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.model_loader import ModelDescriptor
from edge.inference.models.huddling_detector import DbscanHuddlingDetector


def _descriptor(tmp_path: Path, **meta_overrides) -> ModelDescriptor:
    meta = {
        "name": "huddling-detector",
        "version": "0.1.0",
        "eps": 0.05,
        "min_samples": 4,
        **meta_overrides,
    }
    fake = tmp_path / "model.json"
    fake.write_text("{}")
    return ModelDescriptor(
        name="huddling-detector",
        version="0.1.0",
        artifact_path=fake,
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


def _detection(centroids, zone_id=None) -> BirdDetection:
    return BirdDetection(
        device_id="edge-1",
        camera_id="cam-1",
        shed_id="shed-1",
        flock_id="flock-A",
        zone_id=zone_id,
        captured_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        model_version="bird-detector@stub-0.0.1",
        bird_count=len(centroids),
        density_score=0.5,
        confidence=0.85,
        bbox_centroids=centroids,
    )


@pytest.mark.asyncio
async def test_tight_cluster_scores_high(tmp_path: Path) -> None:
    """20 birds packed into a 0.01-radius blob → score near 1.0."""
    det = DbscanHuddlingDetector(_descriptor(tmp_path))
    # Tight blob around (0.5, 0.5).
    centroids = [(0.5 + (i % 5) * 0.005, 0.5 + (i // 5) * 0.005) for i in range(20)]
    result = await det.score(_frame(), _detection(centroids))
    assert result.huddling_score == 1.0
    assert result.cluster_count == 1
    assert result.largest_cluster_pct == 1.0


@pytest.mark.asyncio
async def test_spread_distribution_scores_zero(tmp_path: Path) -> None:
    """16 birds on a 4×4 grid spaced 0.2 apart → no clusters at eps=0.05."""
    det = DbscanHuddlingDetector(_descriptor(tmp_path))
    centroids = [(0.1 + r * 0.2, 0.1 + c * 0.2) for r in range(4) for c in range(4)]
    result = await det.score(_frame(), _detection(centroids))
    assert result.huddling_score == 0.0
    assert result.cluster_count == 0


@pytest.mark.asyncio
async def test_mixed_returns_largest_cluster_fraction(tmp_path: Path) -> None:
    """15 in one tight blob + 5 outliers → score = 15/20 = 0.75."""
    det = DbscanHuddlingDetector(_descriptor(tmp_path))
    blob = [(0.3 + (i % 5) * 0.005, 0.3 + (i // 5) * 0.005) for i in range(15)]
    outliers = [(0.05, 0.05), (0.95, 0.05), (0.05, 0.95), (0.95, 0.95), (0.5, 0.95)]
    result = await det.score(_frame(), _detection(blob + outliers))
    assert result.huddling_score == pytest.approx(0.75, abs=0.01)
    assert result.cluster_count == 1
    assert result.largest_cluster_pct == pytest.approx(0.75, abs=0.01)


@pytest.mark.asyncio
async def test_two_separated_clusters_scores_largest(tmp_path: Path) -> None:
    """Two equal blobs of 8 each → score = 0.5, cluster_count = 2."""
    det = DbscanHuddlingDetector(_descriptor(tmp_path))
    blob1 = [(0.25 + (i % 4) * 0.005, 0.25 + (i // 4) * 0.005) for i in range(8)]
    blob2 = [(0.75 + (i % 4) * 0.005, 0.75 + (i // 4) * 0.005) for i in range(8)]
    result = await det.score(_frame(), _detection(blob1 + blob2))
    assert result.huddling_score == pytest.approx(0.5, abs=0.01)
    assert result.cluster_count == 2


@pytest.mark.asyncio
async def test_below_min_samples_returns_zero(tmp_path: Path) -> None:
    det = DbscanHuddlingDetector(_descriptor(tmp_path, min_samples=4))
    # Only 3 birds → can't form a cluster with min_samples=4.
    result = await det.score(_frame(), _detection([(0.5, 0.5), (0.51, 0.5), (0.5, 0.51)]))
    assert result.huddling_score == 0.0
    assert result.cluster_count == 0


@pytest.mark.asyncio
async def test_empty_centroids_returns_zero(tmp_path: Path) -> None:
    det = DbscanHuddlingDetector(_descriptor(tmp_path))
    result = await det.score(_frame(), _detection([]))
    assert result.huddling_score == 0.0


@pytest.mark.asyncio
async def test_zone_overrides_applied(tmp_path: Path) -> None:
    """Without the override, eps=0.05 → spread doesn't cluster.
    With zone override eps=0.25, the same points cluster into one big group."""
    det = DbscanHuddlingDetector(
        _descriptor(
            tmp_path,
            eps=0.05,
            zone_overrides={"zone-A": {"eps": 0.25, "min_samples": 4}},
        )
    )
    centroids = [(0.1 + r * 0.2, 0.1 + c * 0.2) for r in range(4) for c in range(4)]

    no_zone = await det.score(_frame(), _detection(centroids))
    assert no_zone.huddling_score == 0.0  # default eps too small

    with_zone = await det.score(_frame(), _detection(centroids, zone_id="zone-A"))
    assert with_zone.huddling_score > 0.5  # broad eps catches the grid


@pytest.mark.asyncio
async def test_propagates_zone_to_event(tmp_path: Path) -> None:
    det = DbscanHuddlingDetector(_descriptor(tmp_path))
    result = await det.score(_frame(), _detection([], zone_id="zone-B"))
    assert result.zone_id == "zone-B"
