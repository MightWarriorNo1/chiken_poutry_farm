"""Frame annotation — overlay AI inference results onto BGR images.

Pure function; no I/O. Called from the FramePipeline after each frame's
inference results are in. Returns JPEG-encoded bytes ready to ship over
the dashboard's MJPEG stream.

CPU-bound (OpenCV draw calls + JPEG encode), so the pipeline calls this
through `anyio.to_thread.run_sync` to keep the event loop responsive.
"""

from __future__ import annotations

from typing import Any


def annotate_and_encode(
    image: Any,  # numpy.ndarray (BGR)
    *,
    bird_count: int | None = None,
    density: float | None = None,
    confidence: float | None = None,
    huddling: float | None = None,
    weight_g: float | None = None,
    centroids: list[tuple[float, float]] | None = None,
    jpeg_quality: int = 75,
) -> bytes:
    """Draw HUD + centroid markers, then JPEG-encode. Returns bytes."""
    import cv2  # local import — keeps this module importable without OpenCV at metadata time

    h, w = image.shape[:2]
    img = image.copy()

    # ── Centroids: small filled circles at each detected bird ──────────────
    if centroids:
        for c in centroids:
            cx, cy = float(c[0]), float(c[1])
            # Per BirdDetection schema, centroids are normalized to [0, 1].
            # Accept already-pixel values too, just in case.
            x = int(round(cx * w if cx <= 1.0 else cx))
            y = int(round(cy * h if cy <= 1.0 else cy))
            x = max(0, min(x, w - 1))
            y = max(0, min(y, h - 1))
            cv2.circle(img, (x, y), 6, (0, 255, 0), -1, cv2.LINE_AA)
            cv2.circle(img, (x, y), 8, (0, 0, 0), 1, cv2.LINE_AA)

    # ── HUD strip (top-left translucent box) ───────────────────────────────
    rows: list[str] = []
    if bird_count is not None:
        rows.append(f"Birds: {bird_count}")
    if density is not None:
        rows.append(f"Density: {density * 100:.0f}%")
    if confidence is not None:
        rows.append(f"Conf: {confidence * 100:.0f}%")
    if huddling is not None:
        rows.append(f"Huddle: {huddling * 100:.0f}%")
    if weight_g is not None:
        rows.append(f"Wt: {weight_g:.0f}g")

    if rows:
        pad = 8
        line_h = 22
        box_h = pad * 2 + line_h * len(rows)
        box_w = 220
        overlay = img.copy()
        cv2.rectangle(overlay, (10, 10), (10 + box_w, 10 + box_h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)
        for i, txt in enumerate(rows):
            cv2.putText(
                img,
                txt,
                (10 + pad, 10 + pad + (i + 1) * line_h - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (220, 220, 220),
                1,
                cv2.LINE_AA,
            )

    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    return bytes(buf)
