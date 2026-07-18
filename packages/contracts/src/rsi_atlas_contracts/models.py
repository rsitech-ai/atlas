from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from rsi_atlas_contracts.system_status import StrictModel


class ModelCapability(StrEnum):
    TEXT_GENERATION = "text_generation"
    STRUCTURED_GENERATION = "structured_generation"
    TOOL_CALLING = "tool_calling"
    VISION = "vision"
    STREAMING = "streaming"
    LONG_CONTEXT = "long_context"
    REASONING = "reasoning"
    EMBEDDINGS = "embeddings"
    RERANKING = "reranking"
    MULTILINGUAL = "multilingual"
    DETERMINISTIC_SAMPLING = "deterministic_sampling"


class ModelLifecycle(StrEnum):
    IMPORTED = "imported"
    QUARANTINED = "quarantined"
    BENCHMARKING = "benchmarking"
    CANDIDATE = "candidate"
    PRODUCTION = "production"
    DEGRADED = "degraded"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    REJECTED = "rejected"


class ProviderHealthState(StrEnum):
    UNAVAILABLE = "unavailable"
    AVAILABLE = "available"


class ResourceClass(StrEnum):
    LIGHT = "light"
    HEAVY_MODEL = "heavy_model"


class ThermalState(StrEnum):
    NOMINAL = "nominal"
    FAIR = "fair"
    SERIOUS = "serious"
    CRITICAL = "critical"


class ModelArtifact(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    artifact_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_family: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    upstream_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
    architecture: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    parameter_class: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    quantization: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    tokenizer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_tokens: int = Field(gt=0, le=10_000_000)
    license_id: str = Field(pattern=r"^[A-Za-z0-9.-]{1,96}$")
    source_manifest_artifact_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    local_path: Path
    capabilities: frozenset[ModelCapability]
    capability_results: frozenset[str] = Field(default_factory=frozenset)
    approved_tasks: frozenset[str] = Field(default_factory=frozenset)
    lifecycle: ModelLifecycle = ModelLifecycle.IMPORTED

    @field_validator("local_path")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("model path must be absolute")
        return value
