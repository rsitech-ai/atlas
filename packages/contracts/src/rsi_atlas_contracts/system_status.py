from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    UNSAFE = "unsafe"
    REPAIRABLE = "repairable"


class RuntimeProfile(StrEnum):
    OFFLINE = "offline"
    MONITORED = "monitored"


class ComponentStatus(StrictModel):
    component_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1)
    state: HealthState
    summary: str = Field(min_length=1)


class SystemStatus(StrictModel):
    schema_version: Literal["1.0.0"]
    product: Literal["RSI Atlas Engine"]
    profile: RuntimeProfile
    state: HealthState
    checked_at: AwareDatetime
    components: tuple[ComponentStatus, ...] = Field(min_length=1)
