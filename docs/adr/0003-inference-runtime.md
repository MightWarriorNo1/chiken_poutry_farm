# ADR 0003 — Inference Runtime: ONNX Runtime + Versioned Local Registry

- **Status:** Accepted
- **Date:** 2026-05-11
- **Decision-makers:** Edge tech lead
- **Related:** [ADR 0001](0001-modular-edge-architecture.md), [ADR 0002](0002-config-driven-camera-supervision.md)

## Context

The edge must run AI models for bird detection, weight estimation, and huddling
detection. Decisions needed:

1. **What runtime?** Train in PyTorch (Ultralytics) is non-negotiable for now —
   open ecosystem, fastest iteration. But running PyTorch on-device is heavy
   (~1 GB image, slower inference, no easy TensorRT path).
2. **How to swap models without redeploying?** The cloud should be able to roll
   forward (v1.0 → v1.1) and roll back without an edge image push.
3. **How to keep the edge alive if a model is missing or broken?**

## Decision

1. **Inference runtime: ONNX Runtime.** Export from Ultralytics → ONNX once;
   run everywhere. CPU on dev laptops, CUDA on Jetson dev, TensorRT on Jetson
   prod. Same `.onnx` artifact, same Python adapter.
2. **Versioned local registry**: `models/<name>/<version>/{model.onnx,metadata.json,eval.md}`.
   The `ModelLoader` resolves names + versions to disk paths; metadata is
   structured (input shape, classes, thresholds).
3. **`InferenceSupervisor`** implements the `BirdDetector` port via delegation
   and reconciles the loaded detector against `EdgeConfig.ai.models`. When the
   cloud bumps the version, the supervisor loads the new model on next config
   poll. When loading fails, it falls back to `StubBirdDetector` and logs.

## Alternatives considered

1. **PyTorch on-device.** Rejected: 3-4× larger images, slower inference, no
   straightforward TensorRT, harder containerization for Jetson.
2. **NVIDIA Triton.** Considered for production scale-out. The `BirdDetector`
   port stays the same; a `TritonBirdDetector` adapter can replace the ONNX one
   for fleets where centralized inference makes sense. Overkill for PoC.
3. **Direct model file path in main.py.** Rejected: doesn't support cloud-driven
   rollouts or graceful fallback.
4. **`latest` symlink only.** Symlinks need admin on Windows dev hosts. Kept the
   symlink path but added "highest version directory" as a fallback.

## Consequences

**Positive**
- One inference adapter for the whole product lifecycle (dev → Jetson → fleet).
- Models version like code, with `metadata.json` + `eval.md` per version under VCS.
- The cloud controls rollout via `EdgeConfig.ai.models[*].version` — same channel
  as everything else.
- Missing or corrupt model files cannot bring the edge down. Stub keeps demos
  alive even on a brand-new device with no model downloaded yet.
- Tests are gated by `@pytest.mark.ai` so CI without the model artifact stays
  fast — humans/Jetson runners can opt in.

**Negative**
- Model binaries are big; not in Git. Needs an external download (Sprint 2 uses
  Ultralytics hub; production should host its own bucket).
- ONNX postprocessing (NMS, letterbox unwrap) is hand-written. Mitigated by
  unit tests on the math; bugs in postprocess are the second-most-common YOLO
  pitfall after preprocess.

## Implementation notes
- [src/edge/inference/model_loader.py](../../src/edge/inference/model_loader.py)
- [src/edge/inference/models/bird_detector.py](../../src/edge/inference/models/bird_detector.py)
- [src/edge/supervisors/inference_supervisor.py](../../src/edge/supervisors/inference_supervisor.py)
- [scripts/bootstrap_bird_detector.py](../../scripts/bootstrap_bird_detector.py)
- [scripts/benchmark_inference.py](../../scripts/benchmark_inference.py)
