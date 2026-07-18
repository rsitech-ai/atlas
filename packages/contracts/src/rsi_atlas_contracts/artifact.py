from typing import Literal, NewType
from uuid import UUID

from pydantic import Field, model_validator

from rsi_atlas_contracts.system_status import StrictModel

ArtifactID = NewType("ArtifactID", str)


class ArtifactIntegrityError(RuntimeError):
    """Raised when on-disk artifact evidence is missing or no longer trustworthy."""


class ArtifactCommandContext(StrictModel):
    tenant_id: UUID
    workspace_id: UUID
    actor_id: UUID
    trace_id: UUID


class ArtifactDescriptor(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    artifact_id: ArtifactID = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    algorithm: Literal["sha256"] = "sha256"
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)

    @model_validator(mode="after")
    def identifier_matches_digest(self) -> "ArtifactDescriptor":
        if self.artifact_id != f"sha256:{self.digest}":
            raise ValueError("artifact identifier must match the digest")
        return self
