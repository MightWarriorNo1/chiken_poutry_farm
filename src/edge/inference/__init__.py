"""AI inference: ports + model adapters + registry."""

from edge.inference.factory import (
    build_bird_detector,
    build_huddling_detector,
    build_weight_estimator,
)
from edge.inference.inference import BirdDetector, HuddlingDetector, WeightEstimator
from edge.inference.model_loader import ModelDescriptor, ModelLoader
from edge.inference.proxied_detector import DetectorRegistry, ProxiedBirdDetector
from edge.inference.proxied_estimator import EstimatorRegistry, ProxiedWeightEstimator
from edge.inference.proxied_huddling import HuddlingRegistry, ProxiedHuddlingDetector

__all__ = [
    "BirdDetector",
    "DetectorRegistry",
    "EstimatorRegistry",
    "HuddlingDetector",
    "HuddlingRegistry",
    "ModelDescriptor",
    "ModelLoader",
    "ProxiedBirdDetector",
    "ProxiedHuddlingDetector",
    "ProxiedWeightEstimator",
    "WeightEstimator",
    "build_bird_detector",
    "build_huddling_detector",
    "build_weight_estimator",
]
