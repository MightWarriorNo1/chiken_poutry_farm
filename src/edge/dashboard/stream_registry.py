"""Registry mapping camera_id → FrameBroadcaster.

One instance lives on the edge composition root and is shared between:
  - the FramePipeline factory in main.py (publisher side — `get_or_create`)
  - the dashboard server (subscriber side — `get`)

When the CameraSupervisor stops a camera, its broadcaster is left in place
until a new camera with the same id (or process restart) replaces it. The
overhead is one tiny object per never-running-again camera id — negligible.
"""

from __future__ import annotations

from edge.dashboard.frame_broadcaster import FrameBroadcaster


class StreamRegistry:
    def __init__(self) -> None:
        self._broadcasters: dict[str, FrameBroadcaster] = {}

    def get_or_create(self, camera_id: str) -> FrameBroadcaster:
        bc = self._broadcasters.get(camera_id)
        if bc is None:
            bc = FrameBroadcaster()
            self._broadcasters[camera_id] = bc
        return bc

    def get(self, camera_id: str) -> FrameBroadcaster | None:
        return self._broadcasters.get(camera_id)

    def camera_ids(self) -> list[str]:
        return list(self._broadcasters)
