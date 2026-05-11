"""End-to-end YOLO inference test — gated on the model artifact being present.

Skip cleanly on hosts without the model so CI doesn't have to download YOLO weights.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge.capture.source import Frame
from edge.inference.model_loader import ModelLoader
from edge.inference.models.bird_detector import YoloBirdDetector

MODEL_PATH = Path("models/bird-detector/v1.0.0/model.onnx")


@pytest.fixture(scope="module")
def model_or_skip() -> None:
    if not MODEL_PATH.exists():
        pytest.skip(
            f"{MODEL_PATH} missing — run `python scripts/bootstrap_bird_detector.py` first"
        )


@pytest.mark.ai
@pytest.mark.asyncio
async def test_yolo_runs_on_synthetic_frame(model_or_skip: None) -> None:
    import numpy as np  # noqa: PLC0415

    descriptor = ModelLoader().load("bird-detector", "v1.0.0")
    detector = YoloBirdDetector(descriptor)
    await detector.start()

    # Uniform gray frame — model should run without crashing and likely produce
    # zero detections. The point is to validate the pipeline end to end.
    image = np.full((720, 1280, 3), 128, dtype=np.uint8)
    frame = Frame(
        camera_id="cam-test",
        captured_at=datetime.now(timezone.utc),
        width=1280,
        height=720,
        image=image,
    )

    result = await detector.detect(frame)
    assert result.model_version == "bird-detector@v1.0.0"
    assert result.bird_count >= 0
    assert 0.0 <= result.density_score <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.bbox_centroids) == result.bird_count
    for x, y in result.bbox_centroids:
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0


@pytest.mark.ai
@pytest.mark.asyncio
async def test_yolo_session_is_idempotent_on_start(model_or_skip: None) -> None:
    descriptor = ModelLoader().load("bird-detector", "v1.0.0")
    detector = YoloBirdDetector(descriptor)
    await detector.start()
    first = detector._session  # noqa: SLF001 — white-box
    await detector.start()
    assert detector._session is first  # noqa: SLF001
