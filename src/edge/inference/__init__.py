"""AI inference: ports + model adapters + registry."""

from edge.inference.factory import build_bird_detector
from edge.inference.inference import BirdDetector, HuddlingDetector, WeightEstimator
from edge.inference.model_loader import ModelDescriptor, ModelLoader
from edge.inference.proxied_detector import DetectorRegistry, ProxiedBirdDetector

__all__ = [
    "BirdDetector",
    "DetectorRegistry",
    "HuddlingDetector",
    "ModelDescriptor",
    "ModelLoader",
    "ProxiedBirdDetector",
    "WeightEstimator",
    "build_bird_detector",
]
