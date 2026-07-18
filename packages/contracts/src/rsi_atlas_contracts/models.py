import os
import re
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
    capabilities: frozenset[ModelCapability] = Field(max_length=len(ModelCapability))
    capability_results: frozenset[str] = Field(default_factory=frozenset, max_length=64)
    approved_tasks: frozenset[str] = Field(default_factory=frozenset, max_length=64)
    lifecycle: ModelLifecycle = ModelLifecycle.IMPORTED

    @field_validator("artifact_id")
    @classmethod
    def nonzero_artifact_uuid(cls, value: UUID) -> UUID:
        if value.int == 0:
            raise ValueError("model artifact UUID must be nonzero")
        return value

    @field_validator("sha256", "tokenizer_sha256")
    @classmethod
    def exact_digest(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("model digest must be lowercase SHA-256")
        return value

    @field_validator("source_manifest_artifact_id")
    @classmethod
    def exact_manifest_artifact_id(cls, value: str) -> str:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
            raise ValueError("source manifest must be a CAS artifact identifier")
        return value

    @field_validator("provider_family", "architecture", "parameter_class", "quantization")
    @classmethod
    def compact_slug(cls, value: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value) is None:
            raise ValueError("model metadata slug is invalid")
        return value

    @field_validator("upstream_id")
    @classmethod
    def conservative_upstream_identifier(cls, value: str) -> str:
        if len(value) > 128:
            raise ValueError("model upstream identifier is invalid")
        segments = value.split("/")
        if not 1 <= len(segments) <= 4 or any(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", segment) is None
            for segment in segments
        ):
            raise ValueError("model upstream identifier is invalid")
        return value

    @field_validator("license_id")
    @classmethod
    def compact_license_identifier(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]{0,95}", value) is None:
            raise ValueError("model license identifier is invalid")
        return value

    @field_validator("capability_results", "approved_tasks")
    @classmethod
    def compact_identifier_set(cls, values: frozenset[str]) -> frozenset[str]:
        if any(re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value) is None for value in values):
            raise ValueError("model result or task identifier is invalid")
        return values

    @field_validator("local_path")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute() or value != Path(os.path.normpath(value)):
            raise ValueError("model path must be absolute and canonical")
        return value
