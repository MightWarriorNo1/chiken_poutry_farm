"""Supervisors: reconcile desired-vs-actual state for long-running things."""

from edge.supervisors.camera_supervisor import CameraSupervisor
from edge.supervisors.inference_supervisor import InferenceSupervisor

__all__ = ["CameraSupervisor", "InferenceSupervisor"]
