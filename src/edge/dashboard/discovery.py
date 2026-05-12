"""Camera auto-discovery — USB, CSI, RTSP (ONVIF), File.

Each `discover_*()` function is fully self-contained and returns a list of
`DiscoveredDevice` dicts ready for serialization. None of them mutate
device state — they probe, then release.

USB
  Enumerate `/dev/video*`, briefly open each via V4L2, read one frame to
  prove a real camera (not a virtual /dev/videoN device).

CSI
  Try `gst-launch-1.0 nvarguscamerasrc sensor-id=<N> num-buffers=1 ! fakesink`
  for N in 0..3. Captures one frame per sensor — the only way to confirm a
  CSI camera is wired without a custom V4L2 driver per board.

RTSP
  WS-Discovery via UDP multicast (239.255.255.250:3702). Returns ONVIF
  device endpoints. For each, we attempt an anonymous Media1 GetStreamUri
  to resolve the actual rtsp:// URL. Auth-required devices come back with
  a marker so the UI can surface that.

File
  Pass-through to the demo recordings directory. Same listing logic as
  DemoManager.list_videos() so File-typed adhoc starts behave consistently.
"""

from __future__ import annotations

import asyncio
import re
import socket
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import anyio
import structlog

log = structlog.get_logger(__name__)


# ── USB ────────────────────────────────────────────────────────────────────


async def discover_usb(timeout_per_device: float = 0.6) -> list[dict[str, Any]]:
    """Return one entry per working V4L2 device found at `/dev/video*`."""
    return await anyio.to_thread.run_sync(_scan_usb_sync, timeout_per_device)


def _scan_usb_sync(timeout_per_device: float) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    dev_dir = Path("/dev")
    if not dev_dir.is_dir():
        return devices
    nodes = sorted(p for p in dev_dir.glob("video*") if p.is_char_device())
    if not nodes:
        return devices

    try:
        import cv2  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        log.warning("discovery.usb.no_cv2", error=str(exc))
        return devices

    for node in nodes:
        info = _probe_v4l2(cv2, node, timeout_per_device)
        if info is not None:
            devices.append(info)
    return devices


def _probe_v4l2(cv2_mod: Any, node: Path, timeout: float) -> dict[str, Any] | None:
    cap = None
    try:
        cap = cv2_mod.VideoCapture(str(node), cv2_mod.CAP_V4L2)
        if not cap.isOpened():
            return None
        # Bound how long we wait for a frame.
        cap.set(cv2_mod.CAP_PROP_BUFFERSIZE, 1)
        # Some virtual devices "open" but never deliver frames; cap reads.
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        h, w = frame.shape[:2]
        fps = float(cap.get(cv2_mod.CAP_PROP_FPS) or 0.0) or None
        name = _v4l2_name(node) or node.name
        return {
            "device": str(node),
            "name": name,
            "width": int(w),
            "height": int(h),
            "fps": fps,
            "suggested_source_uri": str(node),
        }
    except Exception as exc:  # noqa: BLE001
        log.debug("discovery.usb.probe_failed", device=str(node), error=str(exc))
        return None
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass


def _v4l2_name(node: Path) -> str | None:
    """Read the human-readable camera name from sysfs (`name` attribute)."""
    try:
        # /sys/class/video4linux/videoN/name
        idx = re.search(r"video(\d+)$", node.name)
        if idx is None:
            return None
        sysfs = Path(f"/sys/class/video4linux/video{idx.group(1)}/name")
        if sysfs.is_file():
            return sysfs.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:  # noqa: BLE001
        pass
    return None


# ── CSI (Jetson nvargus) ───────────────────────────────────────────────────


async def discover_csi(max_sensor_id: int = 3, timeout: float = 3.0) -> list[dict[str, Any]]:
    """Probe nvargus sensor-ids 0..max_sensor_id. Returns one entry per working one."""
    return await anyio.to_thread.run_sync(_scan_csi_sync, max_sensor_id, timeout)


def _scan_csi_sync(max_sensor_id: int, timeout: float) -> list[dict[str, Any]]:
    """Try gst-launch-1.0 nvarguscamerasrc per sensor-id; one frame is success."""
    import subprocess  # noqa: PLC0415

    if subprocess.run(  # noqa: S603, S607
        ["which", "gst-launch-1.0"], capture_output=True, text=True
    ).returncode != 0:
        log.debug("discovery.csi.no_gst_launch")
        return []

    found: list[dict[str, Any]] = []
    for sensor_id in range(max_sensor_id + 1):
        pipeline_args = [
            "gst-launch-1.0",
            "-q",
            "nvarguscamerasrc",
            f"sensor-id={sensor_id}",
            "num-buffers=1",
            "!",
            "fakesink",
        ]
        try:
            r = subprocess.run(  # noqa: S603
                pipeline_args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            log.debug("discovery.csi.timeout", sensor_id=sensor_id)
            continue
        if r.returncode != 0:
            continue
        # Pipeline ran clean — sensor present.
        gst_uri = (
            f"nvarguscamerasrc sensor-id={sensor_id} ! "
            "video/x-raw(memory:NVMM),width=1920,height=1080,framerate=15/1 ! "
            "nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! "
            "video/x-raw,format=BGR ! appsink"
        )
        found.append(
            {
                "sensor_id": sensor_id,
                "name": f"CSI sensor {sensor_id}",
                "width": 1920,
                "height": 1080,
                "fps": 15.0,
                "suggested_source_uri": gst_uri,
            }
        )
    return found


# ── RTSP via ONVIF WS-Discovery ────────────────────────────────────────────


_WS_DISCOVERY_ADDR = "239.255.255.250"
_WS_DISCOVERY_PORT = 3702

_PROBE_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <s:Header>
    <a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
    <a:MessageID>uuid:{msg_id}</a:MessageID>
    <a:To s:mustUnderstand="1">urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
  </s:Header>
  <s:Body>
    <Probe xmlns="http://schemas.xmlsoap.org/ws/2005/04/discovery">
      <d:Types xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
               xmlns:dp="http://www.onvif.org/ver10/network/wsdl">dp:NetworkVideoTransmitter</d:Types>
    </Probe>
  </s:Body>
</s:Envelope>
"""

_GET_PROFILES_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:trt="http://www.onvif.org/ver10/media/wsdl">'
    "<s:Body><trt:GetProfiles/></s:Body></s:Envelope>"
)


async def discover_rtsp(timeout: float = 3.0) -> list[dict[str, Any]]:
    """WS-Discover ONVIF devices on the LAN; try to resolve each to an rtsp:// URL."""
    devices = await anyio.to_thread.run_sync(_ws_discovery_sync, timeout)
    if not devices:
        return []

    # Resolve RTSP URLs in parallel.
    async def _resolve(d: dict[str, Any]) -> dict[str, Any]:
        url = await _resolve_rtsp_uri(d.get("xaddr"))
        d2 = dict(d)
        if url is not None:
            d2["suggested_source_uri"] = url
            d2["requires_auth"] = False
        else:
            d2["suggested_source_uri"] = None
            d2["requires_auth"] = True
        return d2

    return list(await asyncio.gather(*(_resolve(d) for d in devices)))


def _ws_discovery_sync(timeout: float) -> list[dict[str, Any]]:
    msg_id = str(uuid.uuid4())
    probe = _PROBE_TEMPLATE.format(msg_id=msg_id).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        sock.sendto(probe, (_WS_DISCOVERY_ADDR, _WS_DISCOVERY_PORT))
    except OSError as exc:
        log.warning("discovery.rtsp.send_failed", error=str(exc))
        sock.close()
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        while True:
            try:
                data, addr = sock.recvfrom(8192)
            except socket.timeout:
                break
            xml = data.decode("utf-8", errors="ignore")
            for xaddr in _extract_xaddrs(xml):
                if xaddr in seen:
                    continue
                seen.add(xaddr)
                out.append(
                    {
                        "ip": addr[0],
                        "xaddr": xaddr,
                        "name": _extract_scope_name(xml) or addr[0],
                    }
                )
    finally:
        sock.close()
    return out


def _extract_xaddrs(xml: str) -> Iterable[str]:
    # Be liberal: ONVIF responses vary in namespace prefixes.
    matches = re.findall(r"<[^>]*XAddrs[^>]*>([^<]+)</[^>]*XAddrs[^>]*>", xml, re.IGNORECASE)
    for chunk in matches:
        for piece in chunk.split():
            if piece.lower().startswith("http"):
                yield piece


def _extract_scope_name(xml: str) -> str | None:
    # ONVIF Scopes look like onvif://www.onvif.org/name/Camera-XYZ — grab any.
    m = re.search(r"onvif://www\.onvif\.org/name/([^\s<]+)", xml, re.IGNORECASE)
    if m:
        return m.group(1).replace("%20", " ")
    return None


async def _resolve_rtsp_uri(xaddr: str | None) -> str | None:
    """Best-effort: GetProfiles → GetStreamUri (no auth). Returns rtsp URL or None."""
    if not xaddr:
        return None

    # Lazy import — httpx is already in the project's runtime deps.
    import httpx  # noqa: PLC0415

    try:
        async with httpx.AsyncClient(timeout=2.5, follow_redirects=True) as client:
            r = await client.post(
                xaddr,
                content=_GET_PROFILES_BODY,
                headers={"Content-Type": "application/soap+xml; charset=utf-8"},
            )
            if r.status_code == 401:
                return None
            if r.status_code >= 400:
                return None
            profiles_xml = r.text
            token = _extract_first_profile_token(profiles_xml)
            if token is None:
                return None
            stream_body = _build_get_stream_uri_body(token)
            r2 = await client.post(
                xaddr,
                content=stream_body,
                headers={"Content-Type": "application/soap+xml; charset=utf-8"},
            )
            if r2.status_code != 200:
                return None
            return _extract_first_uri(r2.text)
    except Exception as exc:  # noqa: BLE001
        log.debug("discovery.rtsp.resolve_failed", xaddr=xaddr, error=str(exc))
        return None


def _extract_first_profile_token(xml: str) -> str | None:
    # Profiles look like <trt:Profiles token="..."> — capture the token.
    m = re.search(r"<[^>]*Profiles[^>]*token=\"([^\"]+)\"", xml, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _build_get_stream_uri_body(profile_token: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
        ' xmlns:trt="http://www.onvif.org/ver10/media/wsdl"'
        ' xmlns:tt="http://www.onvif.org/ver10/schema">'
        "<s:Body><trt:GetStreamUri>"
        "<trt:StreamSetup>"
        "<tt:Stream>RTP-Unicast</tt:Stream>"
        "<tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>"
        "</trt:StreamSetup>"
        f"<trt:ProfileToken>{profile_token}</trt:ProfileToken>"
        "</trt:GetStreamUri></s:Body></s:Envelope>"
    )


def _extract_first_uri(xml: str) -> str | None:
    m = re.search(r"<[^>]*Uri[^>]*>(rtsp://[^<]+)</[^>]*Uri[^>]*>", xml, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


# ── File (demo/recordings pass-through) ────────────────────────────────────


async def discover_file(videos_dir: Path) -> list[dict[str, Any]]:
    """Mirror DemoManager.list_videos but in the discovery shape."""
    if not videos_dir.is_dir():
        return []

    def _scan() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in sorted(videos_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in (".mp4", ".mkv", ".avi", ".mov", ".webm"):
                continue
            out.append(
                {
                    "name": path.name,
                    "size_bytes": int(path.stat().st_size),
                    "suggested_source_uri": f"file://{path.resolve()}",
                }
            )
        return out

    return await anyio.to_thread.run_sync(_scan)
