# ADR 0004 — Sensor Supervision (per-Protocol Pipelines)

- **Status:** Accepted
- **Date:** 2026-05-11
- **Decision-makers:** Edge tech lead
- **Related:** [ADR 0001](0001-modular-edge-architecture.md), [ADR 0002](0002-config-driven-camera-supervision.md), [ADR 0003](0003-hot-swappable-models.md)

## Context

Sprint 0 wired a single `SimulatedSensorReader` directly into `main.py`. Sprint 3
needs:
- Real **MQTT** sensors (one broker, many sensors).
- Real **Modbus** sensors (one TCP/RTU bus, many holding registers).
- Continued **simulator** support for offline dev.
- All three driven by `EdgeConfig.sensors[*]` so the cloud can add/remove sensors
  without an edge restart.

The challenge: a single `SensorReader` is the wrong granularity. An MQTT broker
likely serves many sensors over one connection; a Modbus serial bus is shared
across registers; the simulator is in-process. Each protocol wants exactly one
runtime instance for the whole sensor set targeting it.

## Decision

Add a third reconciler — **`SensorSupervisor`** — mirroring `CameraSupervisor`
and `InferenceSupervisor`, but **grouped by protocol**.

1. `apply(sensors)` groups the desired list by `source.protocol`.
2. For each protocol group, the supervisor maintains exactly one running
   `SensorPipeline` (one reader, one outbox writer).
3. If a protocol's sensor list changes, that protocol's pipeline restarts; other
   protocols are untouched.
4. Pipeline construction goes through `build_sensor_reader(protocol, configs, ...)`
   which dispatches on protocol name.

`ConfigPipeline` now drives all three supervisors in `_apply()` — inference,
sensors, then cameras. Inference goes first so the detector is always ready
before a frame pipeline tries to use it.

## Alternatives considered

1. **One reader per sensor.** Wasteful: 50 MQTT sensors → 50 broker connections.
2. **Hash sensor list to detect change.** Considered. Equivalent to dict equality
   in our case and harder to debug in logs. Skipped.
3. **Per-sensor pipelines that share a connection.** Possible with a shared
   client object, but the reconciliation logic gets messier (need to track which
   sensors are subscribed). The protocol-grouped pipeline is simpler and matches
   how MQTT/Modbus libraries want to be used.
4. **Drive sensors from the camera supervisor.** No — different lifecycle, different
   reconciliation key. Two supervisors stay clean.

## Consequences

**Positive**
- Adding a new sensor protocol (BACnet, OPC-UA, BLE) is a one-branch change in
  `sensors/factory.py` and a new `*_reader.py` adapter.
- Per-protocol restart isolates churn: rotating an MQTT topic doesn't disturb
  Modbus polling.
- `SensorSupervisor` follows exactly the same shape as `CameraSupervisor`
  (idempotent `apply`, `_RunningGroup` state, `anyio.Lock`) so cognitive load is
  amortized across the codebase.
- Operators see clean log lines: `sensor.group.start protocol=mqtt sensors=12`.

**Negative**
- A small amount of duplication between supervisors. Could be unified behind a
  generic `Supervisor[K, V]`. We're keeping them separate for now because
  cameras and sensors will diverge in production (per-camera health checks,
  per-sensor calibration sync). Consolidate later if the divergence stays
  shallow.
- `MqttSensorReader.start()` opens a network connection; if the broker is down
  the reader logs and proceeds with no subscriptions. Caller (the pipeline) sees
  no events. Sprint 6 will surface this as a `device.sensor.offline` alert.

## Implementation pointers
- [src/edge/sensors/spec.py](../../src/edge/sensors/spec.py)
- [src/edge/sensors/factory.py](../../src/edge/sensors/factory.py)
- [src/edge/sensors/mqtt_reader.py](../../src/edge/sensors/mqtt_reader.py)
- [src/edge/sensors/modbus_reader.py](../../src/edge/sensors/modbus_reader.py)
- [src/edge/supervisors/sensor_supervisor.py](../../src/edge/supervisors/sensor_supervisor.py)
- [docker/docker-compose.dev.yml](../../docker/docker-compose.dev.yml)
- [scripts/mqtt_sensor_publisher.py](../../scripts/mqtt_sensor_publisher.py)
