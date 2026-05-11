"""ManualWeightSample — a manually-weighed sample submitted by farm staff.

Used by the cloud dashboard to compare AI estimates against ground truth and
(later) by the model registry to assemble training/eval datasets.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ManualWeightSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    device_id: str
    flock_id: str
    shed_id: str | None = None
    sampled_at: datetime
    flock_age_days: int | None = Field(default=None, ge=0)
    sample_count: int = Field(ge=1)
    average_weight_g: float = Field(ge=0)
    min_weight_g: float | None = Field(default=None, ge=0)
    max_weight_g: float | None = Field(default=None, ge=0)
    notes: str | None = None
    operator: str | None = None
