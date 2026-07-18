from enum import StrEnum
from typing import Literal, Self
from unicodedata import category

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


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


class ComponentGroup(StrEnum):
    STORAGE = "storage"
    PRIVACY = "privacy"
    OBSERVABILITY = "observability"
    RESOURCES = "resources"
    ENGINE = "engine"


SYSTEM_COMPONENT_LAYOUT = (
    ("engine_runtime", ComponentGroup.ENGINE),
    ("database", ComponentGroup.STORAGE),
    ("artifact_store", ComponentGroup.STORAGE),
    ("offline_policy", ComponentGroup.PRIVACY),
    ("trace_store", ComponentGroup.OBSERVABILITY),
    ("resource_policy", ComponentGroup.RESOURCES),
    ("model_registry", ComponentGroup.RESOURCES),
    ("contract_api", ComponentGroup.ENGINE),
)


class ComponentStatus(StrictModel):
    component_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    title: str = Field(min_length=1, max_length=80)
    group: ComponentGroup
    state: HealthState
    summary: str = Field(min_length=1, max_length=240)
    remediation: str | None = Field(default=None, min_length=1, max_length=240)

    @field_validator("title", "summary", "remediation")
    @classmethod
    def bounded_display_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        contains_control = any(category(character).startswith("C") for character in value)
        if value != value.strip() or contains_control:
            raise ValueError("component display text is invalid")
        return value


class SystemStatus(StrictModel):
    schema_version: Literal["1.1.0"]
    product: Literal["RSI Atlas Engine"]
    profile: RuntimeProfile
    state: HealthState
    checked_at: AwareDatetime
    components: tuple[ComponentStatus, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_components(self) -> Self:
        layout = tuple((component.component_id, component.group) for component in self.components)
        if layout != SYSTEM_COMPONENT_LAYOUT:
            raise ValueError("system status requires the exact ordered component layout")
        identifiers = tuple(component.component_id for component in self.components)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("system status contains a duplicate component identifier")
        priority = {
            HealthState.HEALTHY: 0,
            HealthState.DEGRADED: 1,
            HealthState.REPAIRABLE: 2,
            HealthState.BLOCKED: 3,
            HealthState.UNSAFE: 4,
        }
        expected = max(self.components, key=lambda component: priority[component.state]).state
        if self.state is not expected:
            raise ValueError("system state must equal the highest component severity")
        return self
