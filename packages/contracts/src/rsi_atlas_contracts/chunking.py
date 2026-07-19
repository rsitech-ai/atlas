"""Strict Chunk / ChunkSet contracts for Phase 2C retrieval projections."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Literal, Self
from unicodedata import category, normalize
from uuid import UUID

from pydantic import Field, StrictFloat, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.artifact import ArtifactCommandContext, ArtifactDescriptor
from rsi_atlas_contracts.document_parsing import (
    DocumentContractModel,
    DocumentProcessingLifecycle,
    sha256_text,
)

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_VERSION_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_ELEMENT_ID_PATTERN = r"^element:[0-9a-f]{64}$"
_ELEMENT_ID_RE = re.compile(_ELEMENT_ID_PATTERN)
_CHUNK_ID_PATTERN = r"^chunk:[0-9a-f]{64}$"
_CHUNK_SET_ID_PATTERN = r"^chunkset:[0-9a-f]{64}$"
_CANONICAL_ID_PATTERN = r"^canonical:[0-9a-f]{64}$"
_ALLOWED_TEXT_CONTROLS = {"\n", "\r", "\t"}

# Spec §13.2 full registry. Only IMPLEMENTED_CHUNK_FAMILIES are Phase 2C-callable.
IMPLEMENTED_CHUNK_FAMILIES: frozenset[str] = frozenset(
    {
        "fixed_token",
        "recursive",
        "page_based",
        "parent_child",
        "table_aware",
    }
)


class ChunkStrategyFamily(StrEnum):
    WHOLE_DOCUMENT = "whole_document"
    FIXED_CHARACTER = "fixed_character"
    FIXED_TOKEN = "fixed_token"
    RECURSIVE = "recursive"
    SENTENCE_PARAGRAPH = "sentence_paragraph"
    PAGE_BASED = "page_based"
    HEADING_SECTION = "heading_section"
    LAYOUT_AWARE = "layout_aware"
    SLIDING_WINDOW = "sliding_window"
    SEMANTIC_BREAKPOINT = "semantic_breakpoint"
    PARENT_CHILD = "parent_child"
    SMALL_TO_BIG = "small_to_big"
    PROPOSITION = "proposition"
    CONTEXTUALIZED = "contextualized"
    TABLE_AWARE = "table_aware"
    FIGURE_CAPTION = "figure_caption"
    SUMMARY_MULTI_REP = "summary_multi_rep"
    LATE_CHUNKING = "late_chunking"
    QUERY_AWARE = "query_aware"
    AGENTIC = "agentic"


class ChunkRelationshipKind(StrEnum):
    PARENT = "parent"
    CHILD = "child"
    NEIGHBOR_PREV = "neighbor_prev"
    NEIGHBOR_NEXT = "neighbor_next"
    TABLE_OF = "table_of"
    ROW_OF = "row_of"


class ChunkEmbeddingState(StrEnum):
    NONE = "none"
    PENDING = "pending"


class ChunkEvaluationStatus(StrEnum):
    UNEVALUATED = "unevaluated"
    INTRINSIC_PASS = "intrinsic_pass"
    INTRINSIC_FAIL = "intrinsic_fail"


class ChunkStrategyIdentity(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    family: ChunkStrategyFamily
    strategy_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    version: str = Field(pattern=_VERSION_PATTERN)
    configuration_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def family_matches_strategy_prefix(self) -> Self:
        expected_prefix = self.family.value
        if self.strategy_id != expected_prefix and not self.strategy_id.startswith(
            f"{expected_prefix}_"
        ):
            raise ValueError("strategy_id must equal or prefix-match the family value")
        return self


class Chunk(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    chunk_id: str = Field(pattern=_CHUNK_ID_PATTERN)
    ordinal: StrictInt = Field(ge=0, le=1_000_000)
    source_element_ids: tuple[str, ...] = Field(min_length=1, max_length=100_000)
    text: str = Field(min_length=1, max_length=2_000_000)
    text_hash: str = Field(pattern=_SHA256_PATTERN)
    contextual_prefix: str | None = Field(default=None, max_length=100_000)
    token_count: StrictInt = Field(ge=1, le=100_000)
    page_numbers: tuple[StrictInt, ...] = Field(min_length=1, max_length=2_000)
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def chunk_content_is_bound(self) -> Self:
        _require_text(self.text, field_name="text")
        if self.contextual_prefix is not None:
            _require_text(self.contextual_prefix, field_name="contextual_prefix")
        if self.text_hash != sha256_text(self.text):
            raise ValueError("text_hash does not match text")
        if len(set(self.source_element_ids)) != len(self.source_element_ids):
            raise ValueError("source_element_ids must be unique")
        for element_id in self.source_element_ids:
            if _ELEMENT_ID_RE.fullmatch(element_id) is None:
                raise ValueError("source_element_ids must be element identities")
        if len(set(self.page_numbers)) != len(self.page_numbers):
            raise ValueError("page_numbers must be unique")
        if tuple(sorted(self.page_numbers)) != self.page_numbers:
            raise ValueError("page_numbers must be sorted ascending")
        if any(page < 1 or page > 2_000 for page in self.page_numbers):
            raise ValueError("page_numbers must be within [1, 2000]")
        for key in self.metadata:
            if not key or len(key) > 64 or key != key.casefold():
                raise ValueError("metadata keys must be lowercase and bounded")
        return self


class ChunkRelationship(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: ChunkRelationshipKind
    from_chunk_id: str = Field(pattern=_CHUNK_ID_PATTERN)
    to_chunk_id: str = Field(pattern=_CHUNK_ID_PATTERN)

    @model_validator(mode="after")
    def endpoints_differ(self) -> Self:
        if self.from_chunk_id == self.to_chunk_id:
            raise ValueError("chunk relationship endpoints must differ")
        return self


class ChunkSetQuality(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    chunk_count: StrictInt = Field(ge=1, le=1_000_000)
    mean_token_count: StrictFloat = Field(ge=0.0, le=100_000.0)
    max_token_count: StrictInt = Field(ge=1, le=100_000)
    min_token_count: StrictInt = Field(ge=1, le=100_000)
    oversized_rate: StrictFloat = Field(ge=0.0, le=1.0)
    undersized_rate: StrictFloat = Field(ge=0.0, le=1.0)
    table_split_rate: StrictFloat = Field(ge=0.0, le=1.0)
    section_path_completeness: StrictFloat = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def token_bounds_are_consistent(self) -> Self:
        if self.min_token_count > self.max_token_count:
            raise ValueError("min_token_count cannot exceed max_token_count")
        if not (self.min_token_count <= self.mean_token_count <= self.max_token_count):
            raise ValueError("mean_token_count must lie within min/max token counts")
        return self


class ChunkSet(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    chunk_set_id: str = Field(pattern=_CHUNK_SET_ID_PATTERN)
    document_version_id: str = Field(pattern=_CANONICAL_ID_PATTERN)
    canonical_content_hash: str = Field(pattern=_SHA256_PATTERN)
    strategy: ChunkStrategyIdentity
    chunks: tuple[Chunk, ...] = Field(min_length=1, max_length=1_000_000)
    relationships: tuple[ChunkRelationship, ...] = Field(default=(), max_length=2_000_000)
    quality: ChunkSetQuality
    embedding_state: Literal[ChunkEmbeddingState.NONE] = ChunkEmbeddingState.NONE
    evaluation_status: ChunkEvaluationStatus = ChunkEvaluationStatus.UNEVALUATED

    @model_validator(mode="after")
    def chunk_set_is_internally_consistent(self) -> Self:
        if self.strategy.family.value not in IMPLEMENTED_CHUNK_FAMILIES:
            raise ValueError("chunk strategy family is not implemented in Phase 2C")
        expected_id = chunk_set_identifier_from_body(
            document_version_id=self.document_version_id,
            canonical_content_hash=self.canonical_content_hash,
            strategy=self.strategy,
            chunks=self.chunks,
            relationships=self.relationships,
            quality=self.quality,
            embedding_state=self.embedding_state,
            evaluation_status=self.evaluation_status,
        )
        if self.chunk_set_id != expected_id:
            raise ValueError("chunk_set_id does not match deterministic identity")
        ordinals = tuple(chunk.ordinal for chunk in self.chunks)
        if ordinals != tuple(range(len(self.chunks))):
            raise ValueError("chunk ordinals must be contiguous starting at 0")
        chunk_ids = tuple(chunk.chunk_id for chunk in self.chunks)
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("chunk identifiers must be unique")
        known = set(chunk_ids)
        for relationship in self.relationships:
            if relationship.from_chunk_id not in known or relationship.to_chunk_id not in known:
                raise ValueError("chunk relationship references unknown chunk")
        if self.quality.chunk_count != len(self.chunks):
            raise ValueError("quality chunk_count must match chunks")
        token_counts = tuple(chunk.token_count for chunk in self.chunks)
        if self.quality.min_token_count != min(token_counts):
            raise ValueError("quality min_token_count does not match chunks")
        if self.quality.max_token_count != max(token_counts):
            raise ValueError("quality max_token_count does not match chunks")
        expected_mean = sum(token_counts) / len(token_counts)
        if abs(self.quality.mean_token_count - expected_mean) > 1e-6:
            raise ValueError("quality mean_token_count does not match chunks")
        return self

    def content_hash(self) -> str:
        return sha256(self.canonical_json_bytes()).hexdigest()


class ChunkSetManifestDraft(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    manifest_id: UUID
    context: ArtifactCommandContext
    acquisition_id: UUID
    document_version_id: str = Field(pattern=_CANONICAL_ID_PATTERN)
    canonical_content_hash: str = Field(pattern=_SHA256_PATTERN)
    chunk_set: ChunkSet
    chunk_set_content_hash: str = Field(pattern=_SHA256_PATTERN)
    chunk_set_artifact: ArtifactDescriptor
    lifecycle: Literal[DocumentProcessingLifecycle.CHUNKED]
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")

    @model_validator(mode="after")
    def manifest_binds_chunk_set(self) -> Self:
        if self.chunk_set.document_version_id != self.document_version_id:
            raise ValueError("chunk set document_version_id does not match manifest")
        if self.chunk_set.canonical_content_hash != self.canonical_content_hash:
            raise ValueError("chunk set canonical_content_hash does not match manifest")
        expected_hash = self.chunk_set.content_hash()
        if self.chunk_set_content_hash != expected_hash:
            raise ValueError("chunk_set_content_hash does not match chunk set bytes")
        if self.chunk_set_artifact.media_type != "application/vnd.rsi-atlas.chunk-set+json":
            raise ValueError("chunk set artifact has an invalid media type")
        if self.chunk_set_artifact.digest != expected_hash:
            raise ValueError("chunk set artifact digest does not match content hash")
        expected_size = len(self.chunk_set.canonical_json_bytes())
        if self.chunk_set_artifact.size_bytes != expected_size:
            raise ValueError("chunk set artifact size does not match content bytes")
        return self


ChunkSetManifest = ChunkSetManifestDraft


def chunk_identifier(
    *,
    chunk_set_key: str,
    ordinal: int,
    source_element_ids: tuple[str, ...],
    text_hash: str,
) -> str:
    payload = {
        "chunk_set_key": chunk_set_key,
        "ordinal": ordinal,
        "source_element_ids": list(source_element_ids),
        "text_hash": text_hash,
    }
    return f"chunk:{sha256(_canonical_json(payload)).hexdigest()}"


def chunk_set_key(
    *,
    document_version_id: str,
    strategy: ChunkStrategyIdentity,
) -> str:
    payload = {
        "document_version_id": document_version_id,
        "strategy": strategy.model_dump(mode="json"),
    }
    return sha256(_canonical_json(payload)).hexdigest()


def chunk_set_body_hash(
    *,
    document_version_id: str,
    canonical_content_hash: str,
    strategy: ChunkStrategyIdentity,
    chunks: tuple[Chunk, ...],
    relationships: tuple[ChunkRelationship, ...],
    quality: ChunkSetQuality,
    embedding_state: ChunkEmbeddingState,
    evaluation_status: ChunkEvaluationStatus,
) -> str:
    payload = {
        "canonical_content_hash": canonical_content_hash,
        "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
        "document_version_id": document_version_id,
        "embedding_state": embedding_state.value,
        "evaluation_status": evaluation_status.value,
        "quality": quality.model_dump(mode="json"),
        "relationships": [rel.model_dump(mode="json") for rel in relationships],
        "schema_version": "1.0.0",
        "strategy": strategy.model_dump(mode="json"),
    }
    return sha256(_canonical_json(payload)).hexdigest()


def chunk_set_identifier_from_body(
    *,
    document_version_id: str,
    canonical_content_hash: str,
    strategy: ChunkStrategyIdentity,
    chunks: tuple[Chunk, ...],
    relationships: tuple[ChunkRelationship, ...],
    quality: ChunkSetQuality,
    embedding_state: ChunkEmbeddingState,
    evaluation_status: ChunkEvaluationStatus,
) -> str:
    body_hash = chunk_set_body_hash(
        document_version_id=document_version_id,
        canonical_content_hash=canonical_content_hash,
        strategy=strategy,
        chunks=chunks,
        relationships=relationships,
        quality=quality,
        embedding_state=embedding_state,
        evaluation_status=evaluation_status,
    )
    return f"chunkset:{body_hash}"


def measure_chunk_set_quality(
    chunks: tuple[Chunk, ...],
    *,
    oversized_token_limit: int = 1800,
    undersized_token_limit: int = 50,
    table_chunk_count: int = 0,
    section_complete_count: int = 0,
) -> ChunkSetQuality:
    if not chunks:
        raise ValueError("quality requires at least one chunk")
    token_counts = tuple(chunk.token_count for chunk in chunks)
    oversized = sum(1 for count in token_counts if count > oversized_token_limit)
    undersized = sum(1 for count in token_counts if count < undersized_token_limit)
    total = len(chunks)
    return ChunkSetQuality(
        chunk_count=total,
        mean_token_count=sum(token_counts) / total,
        max_token_count=max(token_counts),
        min_token_count=min(token_counts),
        oversized_rate=oversized / total,
        undersized_rate=undersized / total,
        table_split_rate=(table_chunk_count / total) if total else 0.0,
        section_path_completeness=(section_complete_count / total) if total else 0.0,
    )


def build_chunk_set(
    *,
    document_version_id: str,
    canonical_content_hash: str,
    strategy: ChunkStrategyIdentity,
    chunks: tuple[Chunk, ...],
    relationships: tuple[ChunkRelationship, ...] = (),
    quality: ChunkSetQuality | None = None,
    evaluation_status: ChunkEvaluationStatus = ChunkEvaluationStatus.UNEVALUATED,
) -> ChunkSet:
    if strategy.family.value not in IMPLEMENTED_CHUNK_FAMILIES:
        raise ValueError("chunk strategy family is not implemented in Phase 2C")
    resolved_quality = quality or measure_chunk_set_quality(chunks)
    chunk_set_id = chunk_set_identifier_from_body(
        document_version_id=document_version_id,
        canonical_content_hash=canonical_content_hash,
        strategy=strategy,
        chunks=chunks,
        relationships=relationships,
        quality=resolved_quality,
        embedding_state=ChunkEmbeddingState.NONE,
        evaluation_status=evaluation_status,
    )
    return ChunkSet(
        chunk_set_id=chunk_set_id,
        document_version_id=document_version_id,
        canonical_content_hash=canonical_content_hash,
        strategy=strategy,
        chunks=chunks,
        relationships=relationships,
        quality=resolved_quality,
        embedding_state=ChunkEmbeddingState.NONE,
        evaluation_status=evaluation_status,
    )


def build_chunk(
    *,
    chunk_set_key_value: str,
    ordinal: int,
    source_element_ids: tuple[str, ...],
    text: str,
    token_count: int,
    page_numbers: tuple[int, ...],
    contextual_prefix: str | None = None,
    metadata: dict[str, str] | None = None,
) -> Chunk:
    text_hash = sha256_text(text)
    return Chunk(
        chunk_id=chunk_identifier(
            chunk_set_key=chunk_set_key_value,
            ordinal=ordinal,
            source_element_ids=source_element_ids,
            text_hash=text_hash,
        ),
        ordinal=ordinal,
        source_element_ids=source_element_ids,
        text=text,
        text_hash=text_hash,
        contextual_prefix=contextual_prefix,
        token_count=token_count,
        page_numbers=page_numbers,
        metadata=metadata or {},
    )


def _canonical_json(value: object) -> bytes:
    return dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _require_text(value: str, *, field_name: str) -> None:
    if normalize("NFC", value) != value:
        raise ValueError(f"{field_name} must use Unicode NFC")
    if any(
        category(character).startswith("C") and character not in _ALLOWED_TEXT_CONTROLS
        for character in value
    ):
        raise ValueError(f"{field_name} contains a forbidden control character")


__all__ = [
    "IMPLEMENTED_CHUNK_FAMILIES",
    "Chunk",
    "ChunkEmbeddingState",
    "ChunkEvaluationStatus",
    "ChunkRelationship",
    "ChunkRelationshipKind",
    "ChunkSet",
    "ChunkSetManifest",
    "ChunkSetManifestDraft",
    "ChunkSetQuality",
    "ChunkStrategyFamily",
    "ChunkStrategyIdentity",
    "build_chunk",
    "build_chunk_set",
    "chunk_identifier",
    "chunk_set_body_hash",
    "chunk_set_identifier_from_body",
    "chunk_set_key",
    "measure_chunk_set_quality",
]
