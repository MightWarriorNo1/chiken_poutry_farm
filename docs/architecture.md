# EdgeBox Architecture

## One-paragraph summary

The EdgeBox runtime is a single Python process composed of independent **pipelines**
(frame, sensor, heartbeat, sync) that communicate only through a durable
**outbox** (SQLite). Each pipeline is built from **ports** (Python `Protocol`s)
and **adapters** (concrete implementations). Domain code is pure data — it never
imports a driver, an HTTP client, or an AI library. This means we can swap
RTSP for GStreamer, ONNX for TensorRT, MQTT for Modbus, or HTTPS for gRPC
without changing pipelines or domain logic.

## Layering

```
┌──────────────── COMPOSITION ROOT (main.py) ────────────────┐
│              wires pipelines + adapters from config         │
└────────────────────────────┬────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│   Pipelines    │  │    Adapters    │  │     Ports      │
│ (use cases)    │←─│ (drivers, I/O) │  │ (Protocols)    │
└───────┬────────┘  └────────────────┘  └────────────────┘
        │ depend only on ↑                       ▲
        ▼                                        │
┌────────────────┐                              │
│     Domain     │ ─────────────────────────────┘
│ (pure data)    │
└────────────────┘
```

**Rule:** dependencies point downward only. A pipeline depends on ports + domain;
adapters depend on ports + domain; domain depends on nothing.

## Modules

| Module | Role | Port? |
|---|---|---|
| [domain/](../src/edge/domain/) | Pure dataclasses; mirror wire contracts. | — |
| [capture/](../src/edge/capture/) | Frame source (RTSP, file, future GStreamer). | `FrameSource` |
| [inference/](../src/edge/inference/) | AI models for bird/weight/huddling. | `BirdDetector`, `WeightEstimator`, `HuddlingDetector` |
| [sensors/](../src/edge/sensors/) | IoT sensor reader (MQTT, simulator, Modbus). | `SensorReader` |
| [outbox/](../src/edge/outbox/) | Durable FIFO queue (SQLite). | `Outbox` |
| [sync/](../src/edge/sync/) | Cloud transport (HTTP, future gRPC). | `CloudSync` |
| [pipelines/](../src/edge/pipelines/) | Long-running coroutines that compose the above. | — |

## Concurrency model

- One process, `anyio` task group → structured concurrency (no orphaned tasks).
- One pipeline = one coroutine. Frame pipelines parallel per camera.
- Sync I/O (OpenCV, paho callbacks) is bridged via `anyio.to_thread.run_sync`.
- The outbox is the only shared state; it's transactional via SQLite WAL.

## Data flow (frame example)

```
RtspFrameSource ─► FramePipeline ─► YoloBirdDetector ─► outbox.put(BirdDetection)
                                  ↘
                                    HeuristicWeightEstimator ─► outbox.put(WeightEstimate)
                                  ↘
                                    DbscanHuddlingDetector ─► outbox.put(HuddlingScore)

SyncPipeline (loop, every 5s)
  for each EventType:
    events = outbox.peek(type, batch_size)
    cloud.send_batch(type, events)   # HTTPS POST
    outbox.ack([e.event_id ...])
```

## Failure modes

| Failure | Behavior |
|---|---|
| Camera offline | RTSP source reconnects with backoff; pipeline keeps running. Heartbeat reports `cameras[].status = offline`. |
| Cloud offline | Sync raises; events stay in outbox; `nack` increments `attempts`. Outbox grows; heartbeat still tries (and queues). When cloud returns, sync drains. |
| Power cut | SQLite WAL preserves committed events; pipeline resumes on next boot. |
| AI model crash | Exception caught in pipeline; logged; next frame proceeds. |
| Schema drift | Cloud rejects 400; sync nacks; alarm via `attempts` rising. |

## Observability

- **Logs:** structured JSON via `structlog`. Every pipeline tags its module.
- **Traces:** OpenTelemetry; `frame_pipeline` opens a span per frame, sync per batch.
- **Metrics:** to be added in Sprint 6 (`outbox_pending`, `frame_latency_ms`, `inference_ms`).

## Production extension points

| PoC | Production swap | Where |
|---|---|---|
| HTTPS+JSON sync | gRPC streaming | new adapter `sync/grpc_sync.py`, same `CloudSync` port |
| Simulator sensor | MQTT / Modbus | `sensors/{mqtt,modbus}_reader.py` (already stubbed) |
| ONNX CPU inference | TensorRT on Jetson | `inference/models/bird_detector.py` selects EP at start |
| In-process logs | Loki + Grafana Tempo | `telemetry.py` → swap exporter |
| YAML config | Cloud-pushed config | `EdgeConfig` poll already in contract |
