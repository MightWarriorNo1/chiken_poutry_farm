"""InferenceSupervisor: multi-model handlers, idempotency, isolation, error safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from edge.inference.model_loader import ModelLoader
from edge.inference.models.stub_detector import StubBirdDetector
from edge.inference.models.stub_weight_estimator import StubWeightEstimator
from edge.inference.proxied_detector import DetectorRegistry
from edge.inference.proxied_estimator import EstimatorRegistry
from edge.supervisors.inference_supervisor import InferenceSupervisor, ModelHandler


def _fresh(tmp_path: Path) -> tuple[InferenceSupervisor, DetectorRegistry, EstimatorRegistry]:
    detector_reg = DetectorRegistry(
        initial=StubBirdDetector(model_version="bird-detector@stub-0.0.1")
    )
    estimator_reg = EstimatorRegistry(
        initial=StubWeightEstimator(model_version="weight-estimator@stub-0.0.1")
    )

    def build_detector(desc):
        return StubBirdDetector(model_version=desc.reference)

    def build_estimator(desc):
        return StubWeightEstimator(model_version=desc.reference)

    sup = InferenceSupervisor(
        loader=ModelLoader(tmp_path),
        handlers={
            "bird-detector": ModelHandler(build=build_detector, install=detector_reg.swap),
            "weight-estimator": ModelHandler(build=build_estimator, install=estimator_reg.swap),
        },
    )
    return sup, detector_reg, estimator_reg


@pytest.mark.asyncio
async def test_swaps_a_single_model_on_version_change(tmp_path: Path) -> None:
    sup, det_reg, est_reg = _fresh(tmp_path)
    initial_est = est_reg.current

    await sup.apply({"models": [{"name": "bird-detector", "version": "stub-0.0.2"}]})
    assert sup.current_version_for("bird-detector") == "stub-0.0.2"
    assert det_reg.current.model_version == "bird-detector@stub-0.0.2"
    # Other model unaffected.
    assert est_reg.current is initial_est


@pytest.mark.asyncio
async def test_swaps_multiple_models_in_one_apply(tmp_path: Path) -> None:
    sup, det_reg, est_reg = _fresh(tmp_path)
    await sup.apply(
        {
            "models": [
                {"name": "bird-detector", "version": "stub-0.0.2"},
                {"name": "weight-estimator", "version": "stub-0.0.2"},
            ]
        }
    )
    assert det_reg.current.model_version == "bird-detector@stub-0.0.2"
    assert est_reg.current.model_version == "weight-estimator@stub-0.0.2"
    assert sup.versions() == {
        "bird-detector": "stub-0.0.2",
        "weight-estimator": "stub-0.0.2",
    }


@pytest.mark.asyncio
async def test_idempotent_when_version_unchanged(tmp_path: Path) -> None:
    sup, det_reg, _ = _fresh(tmp_path)
    await sup.apply({"models": [{"name": "bird-detector", "version": "stub-0.0.2"}]})
    after_first = det_reg.current
    await sup.apply({"models": [{"name": "bird-detector", "version": "stub-0.0.2"}]})
    assert det_reg.current is after_first  # no swap


@pytest.mark.asyncio
async def test_ignores_unknown_model_names(tmp_path: Path) -> None:
    sup, det_reg, est_reg = _fresh(tmp_path)
    initial_det = det_reg.current
    initial_est = est_reg.current
    await sup.apply({"models": [{"name": "huddling-detector", "version": "1.0.0"}]})
    assert det_reg.current is initial_det
    assert est_reg.current is initial_est


@pytest.mark.asyncio
async def test_swap_failure_isolated_to_one_model(tmp_path: Path) -> None:
    sup, det_reg, est_reg = _fresh(tmp_path)
    initial_det = det_reg.current
    # Detector points at a real version that doesn't exist on disk → loader raises.
    # Estimator points at a stub → succeeds. Failure must not cancel the success.
    await sup.apply(
        {
            "models": [
                {"name": "bird-detector", "version": "9.9.9"},
                {"name": "weight-estimator", "version": "stub-0.0.2"},
            ]
        }
    )
    assert det_reg.current is initial_det  # rolled back
    assert sup.current_version_for("bird-detector") is None
    assert est_reg.current.model_version == "weight-estimator@stub-0.0.2"
    assert sup.current_version_for("weight-estimator") == "stub-0.0.2"


@pytest.mark.asyncio
async def test_skips_entries_without_name_or_version(tmp_path: Path) -> None:
    sup, det_reg, _ = _fresh(tmp_path)
    initial = det_reg.current
    await sup.apply(
        {
            "models": [
                {"name": "bird-detector"},          # no version
                {"version": "stub-0.0.2"},           # no name
                "not a dict",                        # wrong shape
            ]
        }
    )
    assert det_reg.current is initial
    assert sup.versions() == {}
