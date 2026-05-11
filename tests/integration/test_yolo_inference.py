"""Real YOLO inference end-to-end. Skipped if model artifact is missing."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge.capture.source import Frame
from edge.inference.factory import build_bird_detector
from edge.inference.model_loader import ModelLoader

MODEL_ROOT = Path(__file__).resolve().parents[2] / "models"
ARTIFACT = MODEL_ROOT / "bird-detector" / "1.0.0" / "model.onnx"


@pytest.mark.ai
@pytest.mark.integration
@pytest.mark.asyncio
async def test_yolo_runs_on_synthetic_frame() -> None:
    if not ARTIFACT.exists():
        pytest.skip(
            f"Model not present at {ARTIFACT}. "
            f"Run `python scripts/download_yolov8n.py` to bootstrap."
        )

    import numpy as np

    loader = ModelLoader(MODEL_ROOT)
    desc = loader.load("bird-detector", "1.0.0")
    detector = build_bird_detector(desc)
    await detector.start()

    rng = np.random.default_rng(42)
    image = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    frame = Frame(
        camera_id="t",
        captured_at=datetime.now(timezone.utc),
        width=1280,
        height=720,
        image=image,
    )

    result = await detector.detect(frame)
    # Random noise won't reliably contain birds — assert structural correctness only.
    assert result.model_version == "bird-detector@1.0.0"
    assert result.bird_count >= 0
    assert 0.0 <= result.density_score <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in result.bbox_centroids)
