"""Demo subsystem — replay recorded videos through the live pipeline.

A demo is just a regular camera config pushed into the CameraSupervisor's
`extras` overlay. Same FramePipeline, same inference, same dashboard
projections. The only differences are:

  - `role: "demo"` in the camera config → the FramePipeline-builder in
    main.py routes its events through the `demo_outbox`, which omits the
    SqliteOutbox layer so SyncPipeline never sees them and they never
    reach the cloud.
  - `loop: false` on the FileFrameSource → the source returns when the
    video runs out, the supervisor fires `on_complete`, and this manager
    clears its extras overlay automatically.

One demo at a time, by design. Starting a new demo while one is running
returns 409 — the caller must stop the running one first.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anyio
import structlog

from edge.dashboard.demo_history import DemoHistoryStore
from edge.dashboard.read_model import ReadModel
from edge.dashboard.views import DemoImageView, DemoStatusView, DemoVideoView
from edge.supervisors.camera_supervisor import CameraSupervisor

log = structlog.get_logger(__name__)

DEMO_CAMERA_ID = "demo"
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".webm")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp")


@dataclass(slots=True)
class _DemoJob:
    kind: str                              # "video" | "image"
    name: str                              # bare filename
    path: Path
    started_at: datetime
    # Video-only metadata (None for image jobs).
    duration_seconds: float | None = None
    fps: float | None = None
    frame_count: int | None = None
    # Image-only metadata (None for video jobs).
    width: int | None = None
    height: int | None = None


@dataclass(slots=True)
class _LastCompleted:
    kind: str
    name: str
    completed_at: datetime


# Callable that yields per-video defaults (flock metadata, etc.) so the demo
# camera config matches the live pipeline's expectations. Returns the FULL
# camera config dict — the manager only fills in id/source_uri/role/loop.
DemoCameraDefaults = Callable[[str], dict[str, Any]]


def _default_defaults(video_name: str) -> dict[str, Any]:  # noqa: ARG001
    return {
        "shed_id": "demo-shed",
        "zone_id": "demo-zone",
        "flock_id": "demo-flock",
        "flock_age_days": 30,
        "breed": "ross_308",
    }


def _probe_video(path: Path) -> dict[str, Any]:
    """Read fps / frame count / dimensions without opening a long-lived handle."""
    try:
        import cv2  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return {}

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {}
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or None
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) or None
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0) or None
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) or None
        duration = (n / fps) if (n and fps) else None
        return {
            "fps": fps,
            "frame_count": n,
            "width": w,
            "height": h,
            "duration_seconds": duration,
        }
    finally:
        cap.release()


def _probe_image(path: Path) -> dict[str, Any]:
    """Get width/height of an image file without holding it in memory."""
    try:
        import cv2  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return {}
    img = cv2.imread(str(path))
    if img is None:
        return {}
    h, w = img.shape[:2]
    return {"width": int(w), "height": int(h)}


class DemoManager:
    """One-at-a-time replay of demo videos OR demo images through the live pipeline."""

    def __init__(
        self,
        *,
        videos_dir: Path,
        images_dir: Path,
        camera_supervisor: CameraSupervisor,
        read_model: ReadModel,
        history_store: DemoHistoryStore | None = None,
        defaults: DemoCameraDefaults = _default_defaults,
    ) -> None:
        self._videos_dir = videos_dir
        self._images_dir = images_dir
        self._supervisor = camera_supervisor
        self._read_model = read_model
        self._history = history_store
        self._defaults = defaults
        self._lock = anyio.Lock()
        self._current: _DemoJob | None = None
        self._current_run_id: str | None = None
        self._last_completed: _LastCompleted | None = None
        # Register completion hook so we self-clean when the video runs out.
        self._supervisor.set_on_complete(self._on_pipeline_complete)

    # ── public API ─────────────────────────────────────────────────────────

    async def list_videos(self) -> list[DemoVideoView]:
        if not self._videos_dir.is_dir():
            return []

        def _scan() -> list[DemoVideoView]:
            out: list[DemoVideoView] = []
            for path in sorted(self._videos_dir.iterdir()):
                if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                stat = path.stat()
                meta = _probe_video(path)
                out.append(
                    DemoVideoView(
                        name=path.name,
                        path=str(path.resolve()),
                        size_bytes=int(stat.st_size),
                        duration_seconds=meta.get("duration_seconds"),
                        fps=meta.get("fps"),
                        width=meta.get("width"),
                        height=meta.get("height"),
                        frame_count=meta.get("frame_count"),
                    )
                )
            return out

        return await anyio.to_thread.run_sync(_scan)

    async def list_images(self) -> list[DemoImageView]:
        """Scan `demo/images/` for still-image test inputs."""
        if not self._images_dir.is_dir():
            return []

        def _scan() -> list[DemoImageView]:
            out: list[DemoImageView] = []
            for path in sorted(self._images_dir.iterdir()):
                if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                stat = path.stat()
                meta = _probe_image(path)
                out.append(
                    DemoImageView(
                        name=path.name,
                        path=str(path.resolve()),
                        size_bytes=int(stat.st_size),
                        width=meta.get("width"),
                        height=meta.get("height"),
                    )
                )
            return out

        return await anyio.to_thread.run_sync(_scan)

    async def start(self, video: str) -> DemoStatusView:
        """Start a video demo. Pipeline ends naturally when the video runs out."""
        target = self._validate_filename(video, self._videos_dir, "video")

        async with self._lock:
            if self._current is not None:
                raise RuntimeError(
                    f"Demo already running ({self._current.name}); stop it first."
                )

            meta = await anyio.to_thread.run_sync(_probe_video, target)
            self._current = _DemoJob(
                kind="video",
                name=video,
                path=target,
                started_at=datetime.now(timezone.utc),
                duration_seconds=meta.get("duration_seconds"),
                fps=meta.get("fps"),
                frame_count=meta.get("frame_count"),
                width=meta.get("width"),
                height=meta.get("height"),
            )

            cam_cfg = {
                **self._defaults(video),
                "camera_id": DEMO_CAMERA_ID,
                "source_uri": f"file://{target.resolve()}",
                "role": "demo",
                "loop": False,                      # videos end naturally
            }
            log.info("demo.start", kind="video", name=video, path=str(target))

        # set_extras takes the supervisor lock; call it outside our own lock
        # to keep nesting predictable.
        await self._supervisor.set_extras([cam_cfg])
        await self._record_begin(kind="video", name=video)
        return await self.status()

    async def start_image(self, image: str) -> DemoStatusView:
        """Start an image demo. Loops the same image until stopped — useful for
        verifying detections on a still picture."""
        target = self._validate_filename(image, self._images_dir, "image")

        async with self._lock:
            if self._current is not None:
                raise RuntimeError(
                    f"Demo already running ({self._current.name}); stop it first."
                )

            meta = await anyio.to_thread.run_sync(_probe_image, target)
            self._current = _DemoJob(
                kind="image",
                name=image,
                path=target,
                started_at=datetime.now(timezone.utc),
                width=meta.get("width"),
                height=meta.get("height"),
            )

            cam_cfg = {
                **self._defaults(image),
                "camera_id": DEMO_CAMERA_ID,
                "source_uri": f"file://{target.resolve()}",
                "role": "demo",
                "loop": True,                       # images re-feed until Stop
            }
            log.info("demo.start", kind="image", name=image, path=str(target))

        await self._supervisor.set_extras([cam_cfg])
        await self._record_begin(kind="image", name=image)
        return await self.status()

    async def stop(self) -> DemoStatusView:
        async with self._lock:
            if self._current is None:
                # Idempotent: stopping when nothing is running is a no-op.
                return await self._build_status_locked()
            name = self._current.name
            run_id = self._current_run_id
            self._current = None
            self._current_run_id = None
            log.info("demo.stop", name=name)
        await self._supervisor.set_extras([])
        await self._record_end(run_id, reason="stopped")
        return await self.status()

    async def status(self) -> DemoStatusView:
        async with self._lock:
            return await self._build_status_locked()

    # ── private ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_filename(name: str, root: Path, kind: str) -> Path:
        if "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError(f"Invalid demo {kind} name: {name!r}")
        target = root / name
        if not target.is_file():
            raise FileNotFoundError(f"Demo {kind} not found: {target}")
        return target

    # ── private ────────────────────────────────────────────────────────────

    async def _build_status_locked(self) -> DemoStatusView:
        current = self._current
        last = self._last_completed

        running = current is not None and DEMO_CAMERA_ID in self._supervisor.running_cameras

        elapsed: float | None = None
        if current is not None:
            elapsed = (datetime.now(timezone.utc) - current.started_at).total_seconds()

        bird_count: int | None = None
        huddling: float | None = None
        weight_g: float | None = None
        if running:
            try:
                cams = await self._read_model.list_cameras()
                for c in cams:
                    if c.camera_id == DEMO_CAMERA_ID:
                        bird_count = c.bird_count
                        huddling = c.huddling_score
                        weight_g = c.estimated_avg_weight_g
                        break
            except Exception as exc:  # noqa: BLE001
                log.debug("demo.status.read_model_failed", error=str(exc))

        stream_url = (
            f"/api/cameras/{DEMO_CAMERA_ID}/stream" if running else None
        )

        return DemoStatusView(
            running=bool(running),
            kind=current.kind if current else None,
            video=current.name if current and current.kind == "video" else None,
            image=current.name if current and current.kind == "image" else None,
            camera_id=DEMO_CAMERA_ID if running else None,
            started_at=current.started_at if current else None,
            elapsed_seconds=elapsed,
            duration_seconds=current.duration_seconds if current else None,
            frame_count=current.frame_count if current else None,
            bird_count=bird_count,
            huddling_score=huddling,
            estimated_avg_weight_g=weight_g,
            completed_at=last.completed_at if last else None,
            last_completed_video=(
                last.name if last and last.kind == "video" else None
            ),
            last_completed_image=(
                last.name if last and last.kind == "image" else None
            ),
            stream_url=stream_url,
        )

    async def _on_pipeline_complete(self, camera_id: str) -> None:
        if camera_id != DEMO_CAMERA_ID:
            return
        async with self._lock:
            if self._current is None:
                # Already stopped manually. Nothing to do.
                return
            self._last_completed = _LastCompleted(
                kind=self._current.kind,
                name=self._current.name,
                completed_at=datetime.now(timezone.utc),
            )
            run_id = self._current_run_id
            log.info("demo.complete", kind=self._current.kind, name=self._current.name)
            self._current = None
            self._current_run_id = None
        # Clear extras (supervisor takes its own lock).
        try:
            await self._supervisor.set_extras([])
        except Exception as exc:  # noqa: BLE001
            log.exception("demo.cleanup.failed", error=str(exc))
        await self._record_end(run_id, reason="completed")

    async def _record_begin(self, *, kind: str, name: str) -> None:
        """Stamp a new history entry; remember its id for `_record_end`."""
        if self._history is None:
            return
        async with self._lock:
            started_at = self._current.started_at if self._current is not None else (
                datetime.now(timezone.utc)
            )
        try:
            run_id = await self._history.begin_run(
                kind=kind, name=name, started_at=started_at
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("demo_history.begin.failed", error=str(exc))
            return
        async with self._lock:
            # `_current` may already be None if the user clicked Stop very
            # quickly — that's fine, _record_end will skip the lookup too.
            self._current_run_id = run_id

    async def _record_end(self, run_id: str | None, *, reason: str) -> None:
        if self._history is None or run_id is None:
            return
        try:
            await self._history.end_run(
                run_id,
                ended_at=datetime.now(timezone.utc),
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("demo_history.end.failed", error=str(exc))
