"""AI inference: ports + model adapters + registry."""

from edge.inference.inference import BirdDetector, HuddlingDetector, WeightEstimator
from edge.inference.model_loader import ModelDescriptor, ModelLoader

__all__ = [
    "BirdDetector",
    "HuddlingDetector",
    "ModelDescriptor",
    "ModelLoader",
    "WeightEstimator",
]
