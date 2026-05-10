# Prosper PoultryVision AI — EdgeBox

On-shed AI inference and IoT ingestion runtime for the Prosper PoultryVision AI platform.

This repo owns the **edge layer**: it captures camera frames, runs AI models for bird detection / weight estimation / huddling, ingests sensor readings, buffers everything in a local outbox, and forwards to the cloud API. The cloud API and web dashboard live in separate repos.

> **Status:** Sprint 0 scaffold. Contracts published; pipelines stubbed.

---

## Quick start (dev laptop, no real cameras)

```powershell
# 1. Install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[ai,sensors,dev]"

# 2. Run with simulated sensors and a sample video file
copy .env.example .env
docker compose -f docker/docker-compose.dev.yml up -d   # mosquitto + sensor sim
prosper-edge
```

You should see structured logs of frames being processed, sensor readings flowing, and HTTP POSTs going to the cloud base URL. Point `EDGE_CLOUD_BASE_URL` at a mock server (e.g. [Prism](https://stoplight.io/open-source/prism) running against [`contracts/openapi.yaml`](contracts/openapi.yaml)) until the real API is online.

---

## Repository map

| Path | Purpose |
|---|---|
| [contracts/](contracts/) | **Edge ↔ Cloud contract** — OpenAPI + JSON Schemas. The shared truth between this repo and the API team. |
| [src/edge/](src/edge/) | EdgeBox runtime. Hexagonal: domain → ports → adapters → pipelines. |
| [models/](models/) | Versioned AI model artifacts (binaries via Git LFS or external registry). |
| [scripts/](scripts/) | Training, ONNX export, benchmarking, contract validation. |
| [tests/](tests/) | Unit + integration. AI-heavy tests are gated by the `ai` marker. |
| [docker/](docker/) | Multi-arch Dockerfiles (amd64 + Jetson) and dev compose stack. |
| [docs/](docs/) | Architecture, ADRs, runbooks. |

## Key documents

- [Architecture overview](docs/architecture.md)
- [Edge ↔ Cloud contract guide](docs/contract.md)
- [ADR 0001 — Modular edge architecture](docs/adr/0001-modular-edge-architecture.md)

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
