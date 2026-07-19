"""Strict embedding / index / retrieval-publication contracts for Phase 2D."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, StrictFloat, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.artifact import ArtifactCommandContext, ArtifactDescriptor
from rsi_atlas_contracts.document_parsing import (
    DocumentContractModel,
    DocumentProcessingLifecycle,
)

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_VERSION_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_CANONICAL_ID_PATTERN = r"^canonical:[0-9a-f]{64}$"
_CHUNK_ID_PATTERN = r"^chunk:[0-9a-f]{64}$"
_CHUNK_SET_ID_PATTERN = r"^chunkset:[0-9a-f]{64}$"
_EMBEDDING_SET_ID_PATTERN = r"^embeddingset:[0-9a-f]{64}$"
_PUBLICATION_ID_PATTERN = r"^publication:[0-9a-f]{64}$"
_DENSE_MEDIA = "application/vnd.rsi-atlas.dense-index+json"
_LEXICAL_MEDIA = "application/vnd.rsi-atlas.lexical-index+json"

# Development dense width for fixture embedder + pgvector staging (not production policy).
DEVELOPMENT_EMBEDDING_DIMENSIONS = 64


class EmbeddingPromotionClass(StrEnum):
    DEVELOPMENT_FIXTURE = "development_fixture"
    CANDIDATE = "candidate"
    PRODUCTION = "production"


class EmbeddingModelIdentity(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    model_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    version: str = Field(pattern=_VERSION_PATTERN)
    dimensions: StrictInt = Field(ge=2, le=4_096)
    normalization: Literal["none", "l2"] = "l2"
    configuration_hash: str = Field(pattern=_SHA256_PATTERN)
    promotion_class: EmbeddingPromotionClass = EmbeddingPromotionClass.DEVELOPMENT_FIXTURE

    @model_validator(mode="after")
    def fixture_promotion_rules(self) -> Self:
        if (
            self.model_id.startswith("fixture_")
            and self.promotion_class is EmbeddingPromotionClass.PRODUCTION
        ):
            raise ValueError("fixture embedding models cannot claim production promotion")
        if (
            self.promotion_class is EmbeddingPromotionClass.DEVELOPMENT_FIXTURE
            and not self.model_id.startswith("fixture_")
        ):
            raise ValueError("development_fixture models must use a fixture_ model_id prefix")
        return self


class ChunkEmbedding(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    chunk_id: str = Field(pattern=_CHUNK_ID_PATTERN)
    chunk_text_hash: str = Field(pattern=_SHA256_PATTERN)
    vector: tuple[StrictFloat, ...] = Field(min_length=2, max_length=4_096)
    input_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    model: EmbeddingModelIdentity

    @model_validator(mode="after")
    def vector_matches_model(self) -> Self:
        validate_vector(self.vector, dimensions=self.model.dimensions)
        return self


class EmbeddingSet(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    embedding_set_id: str = Field(pattern=_EMBEDDING_SET_ID_PATTERN)
    chunk_set_id: str = Field(pattern=_CHUNK_SET_ID_PATTERN)
    chunk_set_content_hash: str = Field(pattern=_SHA256_PATTERN)
    model: EmbeddingModelIdentity
    embeddings: tuple[ChunkEmbedding, ...] = Field(min_length=1, max_length=1_000_000)

    @model_validator(mode="after")
    def embedding_set_is_consistent(self) -> Self:
        expected = embedding_set_identifier(
            chunk_set_id=self.chunk_set_id,
            chunk_set_content_hash=self.chunk_set_content_hash,
            model=self.model,
            embeddings=self.embeddings,
        )
        if self.embedding_set_id != expected:
            raise ValueError("embedding_set_id does not match deterministic identity")
        chunk_ids = tuple(item.chunk_id for item in self.embeddings)
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("embedding chunk identifiers must be unique")
        for item in self.embeddings:
            if item.model != self.model:
                raise ValueError("embedding model must match embedding set model")
        return self


class RetrievalIndexBundle(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    dense_cardinality: StrictInt = Field(ge=1, le=1_000_000)
    lexical_cardinality: StrictInt = Field(ge=1, le=1_000_000)
    exact_identifier_cardinality: StrictInt = Field(ge=0, le=1_000_000)
    dense_content_hash: str = Field(pattern=_SHA256_PATTERN)
    lexical_content_hash: str = Field(pattern=_SHA256_PATTERN)
    exact_content_hash: str = Field(pattern=_SHA256_PATTERN)


class RetrievalPublicationManifestDraft(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    manifest_id: UUID
    publication_id: str = Field(pattern=_PUBLICATION_ID_PATTERN)
    context: ArtifactCommandContext
    acquisition_id: UUID
    document_version_id: str = Field(pattern=_CANONICAL_ID_PATTERN)
    chunk_set_id: str = Field(pattern=_CHUNK_SET_ID_PATTERN)
    embedding_set: EmbeddingSet
    index_bundle: RetrievalIndexBundle
    dense_index_artifact: ArtifactDescriptor
    lexical_index_artifact: ArtifactDescriptor
    chunk_count: StrictInt = Field(ge=1, le=1_000_000)
    lifecycle: Literal[
        DocumentProcessingLifecycle.INDEX_VALIDATED,
        DocumentProcessingLifecycle.PUBLISHED,
    ]
    searchable: StrictBool
    recorded_at: datetime
    warnings: tuple[str, ...] = ()

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")

    @model_validator(mode="after")
    def publication_is_internally_consistent(self) -> Self:
        if self.embedding_set.chunk_set_id != self.chunk_set_id:
            raise ValueError("embedding set chunk_set_id does not match publication")
        if len(self.embedding_set.embeddings) != self.chunk_count:
            raise ValueError("embedding set size must equal chunk_count")
        if self.index_bundle.dense_cardinality != self.chunk_count:
            raise ValueError("dense_cardinality must equal chunk_count")
        if self.index_bundle.lexical_cardinality != self.chunk_count:
            raise ValueError("lexical_cardinality must equal chunk_count")
        if self.dense_index_artifact.media_type != _DENSE_MEDIA:
            raise ValueError("dense index artifact has an invalid media type")
        if self.lexical_index_artifact.media_type != _LEXICAL_MEDIA:
            raise ValueError("lexical index artifact has an invalid media type")
        expected = publication_identifier(
            document_version_id=self.document_version_id,
            chunk_set_id=self.chunk_set_id,
            embedding_set_id=self.embedding_set.embedding_set_id,
            index_bundle=self.index_bundle,
            lifecycle=self.lifecycle,
        )
        if self.publication_id != expected:
            raise ValueError("publication_id does not match deterministic identity")
        if self.lifecycle is DocumentProcessingLifecycle.INDEX_VALIDATED and self.searchable:
            raise ValueError("index_validated manifests must remain non-searchable")
        if self.lifecycle is DocumentProcessingLifecycle.PUBLISHED and not self.searchable:
            raise ValueError("published manifests must be searchable")
        return self


RetrievalPublicationManifest = RetrievalPublicationManifestDraft


def validate_vector(vector: tuple[float, ...], *, dimensions: int) -> None:
    if len(vector) != dimensions:
        raise ValueError("vector dimensions do not match model")
    if any(not math.isfinite(component) for component in vector):
        raise ValueError("vector components must be finite")
    if all(component == 0.0 for component in vector):
        raise ValueError("vector norm must be non-zero")


def _canonical_json(payload: object) -> bytes:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def embedding_set_identifier(
    *,
    chunk_set_id: str,
    chunk_set_content_hash: str,
    model: EmbeddingModelIdentity,
    embeddings: tuple[ChunkEmbedding, ...],
) -> str:
    payload = {
        "chunk_set_id": chunk_set_id,
        "chunk_set_content_hash": chunk_set_content_hash,
        "model": model.model_dump(mode="json"),
        "embeddings": [
            {
                "chunk_id": item.chunk_id,
                "chunk_text_hash": item.chunk_text_hash,
                "vector": list(item.vector),
                "input_policy_hash": item.input_policy_hash,
            }
            for item in embeddings
        ],
    }
    return f"embeddingset:{sha256(_canonical_json(payload)).hexdigest()}"


def publication_identifier(
    *,
    document_version_id: str,
    chunk_set_id: str,
    embedding_set_id: str,
    index_bundle: RetrievalIndexBundle,
    lifecycle: DocumentProcessingLifecycle | Literal["index_validated", "published"] = (
        DocumentProcessingLifecycle.INDEX_VALIDATED
    ),
) -> str:
    lifecycle_value = (
        lifecycle.value if isinstance(lifecycle, DocumentProcessingLifecycle) else lifecycle
    )
    payload = {
        "document_version_id": document_version_id,
        "chunk_set_id": chunk_set_id,
        "embedding_set_id": embedding_set_id,
        "index_bundle": index_bundle.model_dump(mode="json"),
        "lifecycle": lifecycle_value,
    }
    return f"publication:{sha256(_canonical_json(payload)).hexdigest()}"


__all__ = [
    "DEVELOPMENT_EMBEDDING_DIMENSIONS",
    "ChunkEmbedding",
    "EmbeddingModelIdentity",
    "EmbeddingPromotionClass",
    "EmbeddingSet",
    "RetrievalIndexBundle",
    "RetrievalPublicationManifest",
    "RetrievalPublicationManifestDraft",
    "embedding_set_identifier",
    "publication_identifier",
    "validate_vector",
]
