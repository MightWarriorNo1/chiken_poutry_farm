# Prosper PoultryVision AI — EdgeBox

On-shed AI inference and IoT ingestion runtime for the Prosper PoultryVision AI platform.

This repo owns the **edge layer**: it captures camera frames, runs AI models for bird detection / weight estimation / huddling, ingests sensor readings, buffers everything in a local outbox, forwards to the cloud API, **and serves a local read-only dashboard on `127.0.0.1:8090` for in-shed visibility**. The customer-facing cloud dashboard lives in a separate repo.

> **Status:** Sprint 0 scaffold. Contracts published; pipelines stubbed.

---

## Quick start (dev laptop, no real cameras)

```powershell
# 1. Install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[ai,sensors,dev]"

# 2. Generate sample frames + point edge at the offline config
python scripts/make_demo_frames.py --out ./demo/frames --count 20
copy .env.example .env
$env:EDGE_STATIC_CONFIG_PATH = "./example.config.yaml"

# 3. Spin up the dev stack (Mosquitto + Prism cloud-mock)
docker compose -f docker/docker-compose.dev.yml up -d

# 4. (Optional) feed real MQTT traffic — only needed if you uncomment the
#    mqtt-protocol sensors in example.config.yaml
python scripts/mqtt_sensor_publisher.py --config example.config.yaml --interval 2

# 5. Run the edge
$env:EDGE_CLOUD__BASE_URL = "http://localhost:4010"
prosper-edge
```

You should see structured logs of:
- the YAML config loading and a camera spinning up
- frames being processed (stub detector emits realistic BirdDetections)
- sensor readings flowing (simulator)
- HTTP POSTs to the mock cloud

To switch to **cloud-driven config**, just unset `EDGE_STATIC_CONFIG_PATH` and point `EDGE_CLOUD__BASE_URL` at the real API.

---

## Repository map

| Path | Purpose |
|---|---|
| [contracts/](contracts/) | **Edge ↔ Cloud contract** — OpenAPI + JSON Schemas. The shared truth between this repo and the API team. |
| [src/edge/](src/edge/) | EdgeBox runtime. Hexagonal: domain → ports → adapters → pipelines. |
| [src/edge/dashboard/](src/edge/dashboard/) | On-device local dashboard — read-side projection + FastAPI + React UI. |
| [src/edge/dashboard/web/](src/edge/dashboard/web/) | React + Vite + Tailwind + Recharts source. Build output: `web/dist/`. |
| [models/](models/) | Versioned AI model artifacts (binaries via Git LFS or external registry). |
| [scripts/](scripts/) | Training, ONNX export, benchmarking, contract validation. |
| [tests/](tests/) | Unit + integration. AI-heavy tests are gated by the `ai` marker. |
| [docker/](docker/) | Multi-arch Dockerfiles (amd64 + Jetson) and dev compose stack. |
| [docs/](docs/) | Architecture, ADRs, runbooks. |

## Key documents

- [Architecture overview](docs/architecture.md)
- [Edge ↔ Cloud contract guide](docs/contract.md)
- [ADR 0001 — Modular edge architecture](docs/adr/0001-modular-edge-architecture.md)
- [ADR 0007 — On-device dashboard](docs/adr/0007-on-device-dashboard.md)

## On-device dashboard

A local read-only web UI runs alongside the pipelines so farm staff (and devs) can see what the edge is doing without the cloud being available.

```powershell
# 1. Install the dashboard extra (FastAPI + uvicorn + SSE)
pip install -e ".[dashboard]"

# 2. Build the React UI once
cd src/edge/dashboard/web
npm install
npm run build
cd ../../../..

# 3. Run the edge — the dashboard is on by default
prosper-edge
# → http://127.0.0.1:8090
```

Toggle off with `EDGE_DASHBOARD__ENABLED=false`. Change the port with
`EDGE_DASHBOARD__PORT=...`. See [.env.example](.env.example).

**Tabs:**
- **Overview** — flock-wide totals, latest temp/humidity, recent alerts
- **Cameras** — per-camera bird count, density, huddling, weight + sparklines
- **Sensors** — per-sensor value with threshold range badges + sparklines
- **Alerts** — rolling window of alerts the edge has raised

**Live updates:** the UI subscribes to `/events` (SSE) and invalidates React Query caches as events arrive. Slow clients have their oldest events dropped, never the publisher.

**React dev loop** (hot reload against the running Python backend):
```powershell
cd src/edge/dashboard/web
$env:EDGE_DASHBOARD__CORS_ORIGINS='["http://localhost:5173"]'
npm run dev
# → http://localhost:5173 (proxies /api + /events to 127.0.0.1:8090)
```

## Development

```powershell
# Lint + format
ruff check . --fix
ruff format .

# Type check
mypy src

# Tests
pytest                       # unit only
pytest -m integration        # full pipeline
pytest -m ai                 # model loading tests
```

## Architecture in one paragraph

Each capability (frame capture, AI inference, sensor read, cloud sync) is a **pipeline** built from **ports** (Python `Protocol`s) and **adapters** (concrete impls). Domain code never imports a driver. An **outbox** in SQLite makes the edge resilient to network loss — events are written locally first, then a background sync drains them in order. The sync transport, AI runtime, sensor protocol, and capture source are all swappable behind their port. PoC ships HTTP+JSON; production swaps in gRPC + TensorRT + Modbus with no change to pipelines or domain.
