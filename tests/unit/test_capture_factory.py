"""build_frame_source dispatches by URI scheme."""

from __future__ import annotations

import pytest

from edge.capture.factory import build_frame_source


def test_file_scheme_returns_file_source() -> None:
    src = build_frame_source(
        {"camera_id": "cam-1", "source_uri": "file://./tests/fixtures"},
        target_fps=1.0,
    )
    assert src.camera_id == "cam-1"
    assert type(src).__name__ == "FileFrameSource"


def test_relative_path_no_scheme_returns_file_source() -> None:
    src = build_frame_source(
        {"camera_id": "cam-2", "source_uri": "./tests/fixtures"},
    )
    assert type(src).__name__ == "FileFrameSource"


def test_rtsp_scheme_returns_rtsp_source() -> None:
    src = build_frame_source(
        {"camera_id": "cam-3", "source_uri": "rtsp://192.0.2.10:554/stream"},
    )
    assert src.camera_id == "cam-3"
    assert type(src).__name__ == "RtspFrameSource"


def test_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported source URI scheme"):
        build_frame_source({"camera_id": "x", "source_uri": "smb://share/cam"})
