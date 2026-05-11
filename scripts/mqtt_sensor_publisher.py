"""MQTT sensor publisher — synthesizes traffic for end-to-end testing.

Reads the sensor list from an EdgeConfig YAML file and publishes a synthetic
value to every sensor whose `source.protocol` is `mqtt`. The value follows the
same diurnal+noise model as `SimulatedSensorReader`, so dashboards see realistic
trends.

Usage:
    python scripts/mqtt_sensor_publisher.py --config example.config.yaml
    python scripts/mqtt_sensor_publisher.py --config example.config.yaml --interval 2
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Reuse the simulator's profile so values match what `SimulatedSensorReader` would emit.
_PROFILES: dict[str, tuple[float, float, float, str]] = {
    "temperature": (24.0, 3.0, 0.3, "celsius"),
    "humidity": (65.0, 5.0, 1.5, "percent"),
    "ammonia": (8.0, 2.0, 0.5, "ppm"),
    "co2": (1500.0, 200.0, 50.0, "ppm"),
    "water_flow": (4.5, 1.0, 0.2, "lpm"),
    "water_pressure": (2.0, 0.3, 0.05, "bar"),
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", type=Path, default=Path("example.config.yaml"))
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--interval", type=float, default=5.0)
    args = p.parse_args()

    try:
        import paho.mqtt.client as mqtt  # noqa: PLC0415
    except ImportError:
        print("Install with: pip install -e '.[sensors]'")
        return 1

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    mqtt_sensors = [
        s
        for s in (cfg.get("sensors") or [])
        if (s.get("source") or {}).get("protocol") == "mqtt"
    ]
    if not mqtt_sensors:
        print(f"No MQTT-protocol sensors found in {args.config}.")
        return 1

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)  # type: ignore[attr-defined]
    client.connect(args.host, args.port, keepalive=30)
    client.loop_start()

    print(
        f"Publishing {len(mqtt_sensors)} sensor(s) → mqtt://{args.host}:{args.port} "
        f"every {args.interval}s. Ctrl-C to stop."
    )
    t = 0.0
    try:
        while True:
            for s in mqtt_sensors:
                topic = (s.get("source") or {}).get("topic")
                if not topic:
                    continue
                profile = _PROFILES.get(s.get("sensor_type", ""))
                if profile is None:
                    continue
                base, swing, noise, _unit = profile
                value = (
                    base
                    + swing * math.sin(2 * math.pi * t / 600.0)
                    + random.uniform(-noise, noise)  # noqa: S311
                )
                payload = json.dumps(
                    {
                        "value": round(value, 3),
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "quality": "good",
                    }
                )
                client.publish(topic, payload, qos=0, retain=False)
            t += args.interval
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
