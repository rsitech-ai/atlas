"""Strict Phase 2D index/publication contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts import (
    DEVELOPMENT_EMBEDDING_DIMENSIONS,
    ArtifactCommandContext,
    ArtifactDescriptor,
    ChunkEmbedding,
    DocumentProcessingLifecycle,
    EmbeddingModelIdentity,
    EmbeddingPromotionClass,
    EmbeddingSet,
    RetrievalIndexBundle,
    RetrievalPublicationManifestDraft,
    embedding_set_identifier,
    publication_identifier,
    validate_vector,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
ACQUISITION_ID = UUID("00000000-0000-4000-8000-000000000005")
MANIFEST_ID = UUID("00000000-0000-4000-8000-00000000000b")
DOCUMENT_VERSION = "canonical:" + ("a" * 64)
CHUNK_SET_ID = "chunkset:" + ("d" * 64)
CHUNK_ID = "chunk:" + ("e" * 64)
CONFIG_HASH = "c" * 64
TEXT_HASH = "f" * 64
POLICY_HASH = "1" * 64
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


def _fixture_model(*, dimensions: int = 4) -> EmbeddingModelIdentity:
    return EmbeddingModelIdentity(
        model_id="fixture_hash_v1",
        version="dev-1",
        dimensions=dimensions,
        normalization="l2",
        configuration_hash=CONFIG_HASH,
        promotion_class=EmbeddingPromotionClass.DEVELOPMENT_FIXTURE,
    )


def _unit_vector(dimensions: int = 4) -> tuple[float, ...]:
    return (1.0, *tuple(0.0 for _ in range(dimensions - 1)))


def _embedding(*, model: EmbeddingModelIdentity) -> ChunkEmbedding:
    return ChunkEmbedding(
        chunk_id=CHUNK_ID,
        chunk_text_hash=TEXT_HASH,
        vector=_unit_vector(model.dimensions),
        input_policy_hash=POLICY_HASH,
        model=model,
    )


def _embedding_set(*, model: EmbeddingModelIdentity) -> EmbeddingSet:
    embeddings = (_embedding(model=model),)
    return EmbeddingSet(
        embedding_set_id=embedding_set_identifier(
            chunk_set_id=CHUNK_SET_ID,
            chunk_set_content_hash=CONFIG_HASH,
            model=model,
            embeddings=embeddings,
        ),
        chunk_set_id=CHUNK_SET_ID,
        chunk_set_content_hash=CONFIG_HASH,
        model=model,
        embeddings=embeddings,
    )


def _bundle() -> RetrievalIndexBundle:
    return RetrievalIndexBundle(
        dense_cardinality=1,
        lexical_cardinality=1,
        exact_identifier_cardinality=0,
        dense_content_hash="2" * 64,
        lexical_content_hash="3" * 64,
        exact_content_hash="4" * 64,
    )


def test_development_embedding_dimensions_constant() -> None:
    assert DEVELOPMENT_EMBEDDING_DIMENSIONS == 64


def test_fixture_model_cannot_claim_production() -> None:
    with pytest.raises(ValidationError):
        EmbeddingModelIdentity(
            model_id="fixture_hash_v1",
            version="dev-1",
            dimensions=8,
            normalization="l2",
            configuration_hash=CONFIG_HASH,
            promotion_class=EmbeddingPromotionClass.PRODUCTION,
        )


def test_validate_vector_rejects_zero_and_nan() -> None:
    with pytest.raises(ValueError, match="non-zero"):
        validate_vector((0.0, 0.0), dimensions=2)
    with pytest.raises(ValueError, match="finite"):
        validate_vector((float("nan"), 1.0), dimensions=2)
    with pytest.raises(ValueError, match="dimensions"):
        validate_vector((1.0,), dimensions=2)


def test_index_validated_manifest_is_non_searchable() -> None:
    model = _fixture_model()
    embedding_set = _embedding_set(model=model)
    bundle = _bundle()
    dense = ArtifactDescriptor(
        artifact_id="sha256:" + ("1" * 64),
        digest="1" * 64,
        size_bytes=32,
        media_type="application/vnd.rsi-atlas.dense-index+json",
    )
    lexical = ArtifactDescriptor(
        artifact_id="sha256:" + ("2" * 64),
        digest="2" * 64,
        size_bytes=16,
        media_type="application/vnd.rsi-atlas.lexical-index+json",
    )
    publication_id = publication_identifier(
        document_version_id=DOCUMENT_VERSION,
        chunk_set_id=CHUNK_SET_ID,
        embedding_set_id=embedding_set.embedding_set_id,
        index_bundle=bundle,
    )
    draft = RetrievalPublicationManifestDraft(
        manifest_id=MANIFEST_ID,
        publication_id=publication_id,
        context=_context(),
        acquisition_id=ACQUISITION_ID,
        document_version_id=DOCUMENT_VERSION,
        chunk_set_id=CHUNK_SET_ID,
        embedding_set=embedding_set,
        index_bundle=bundle,
        dense_index_artifact=dense,
        lexical_index_artifact=lexical,
        chunk_count=1,
        lifecycle=DocumentProcessingLifecycle.INDEX_VALIDATED,
        searchable=False,
        recorded_at=NOW,
    )
    assert draft.searchable is False
    assert draft.lifecycle is DocumentProcessingLifecycle.INDEX_VALIDATED


def test_published_lifecycle_requires_searchable_true() -> None:
    model = _fixture_model()
    embedding_set = _embedding_set(model=model)
    bundle = _bundle()
    dense = ArtifactDescriptor(
        artifact_id="sha256:" + ("1" * 64),
        digest="1" * 64,
        size_bytes=32,
        media_type="application/vnd.rsi-atlas.dense-index+json",
    )
    lexical = ArtifactDescriptor(
        artifact_id="sha256:" + ("2" * 64),
        digest="2" * 64,
        size_bytes=16,
        media_type="application/vnd.rsi-atlas.lexical-index+json",
    )
    publication_id = publication_identifier(
        document_version_id=DOCUMENT_VERSION,
        chunk_set_id=CHUNK_SET_ID,
        embedding_set_id=embedding_set.embedding_set_id,
        index_bundle=bundle,
    )
    with pytest.raises(ValidationError):
        RetrievalPublicationManifestDraft(
            manifest_id=MANIFEST_ID,
            publication_id=publication_id,
            context=_context(),
            acquisition_id=ACQUISITION_ID,
            document_version_id=DOCUMENT_VERSION,
            chunk_set_id=CHUNK_SET_ID,
            embedding_set=embedding_set,
            index_bundle=bundle,
            dense_index_artifact=dense,
            lexical_index_artifact=lexical,
            chunk_count=1,
            lifecycle=DocumentProcessingLifecycle.PUBLISHED,
            searchable=False,
            recorded_at=NOW,
        )


def test_cardinality_must_match_chunk_count() -> None:
    model = _fixture_model()
    embedding_set = _embedding_set(model=model)
    bundle = RetrievalIndexBundle(
        dense_cardinality=2,
        lexical_cardinality=1,
        exact_identifier_cardinality=0,
        dense_content_hash="2" * 64,
        lexical_content_hash="3" * 64,
        exact_content_hash="4" * 64,
    )
    dense = ArtifactDescriptor(
        artifact_id="sha256:" + ("1" * 64),
        digest="1" * 64,
        size_bytes=32,
        media_type="application/vnd.rsi-atlas.dense-index+json",
    )
    lexical = ArtifactDescriptor(
        artifact_id="sha256:" + ("2" * 64),
        digest="2" * 64,
        size_bytes=16,
        media_type="application/vnd.rsi-atlas.lexical-index+json",
    )
    publication_id = publication_identifier(
        document_version_id=DOCUMENT_VERSION,
        chunk_set_id=CHUNK_SET_ID,
        embedding_set_id=embedding_set.embedding_set_id,
        index_bundle=bundle,
    )
    with pytest.raises(ValidationError):
        RetrievalPublicationManifestDraft(
            manifest_id=MANIFEST_ID,
            publication_id=publication_id,
            context=_context(),
            acquisition_id=ACQUISITION_ID,
            document_version_id=DOCUMENT_VERSION,
            chunk_set_id=CHUNK_SET_ID,
            embedding_set=embedding_set,
            index_bundle=bundle,
            dense_index_artifact=dense,
            lexical_index_artifact=lexical,
            chunk_count=1,
            lifecycle=DocumentProcessingLifecycle.INDEX_VALIDATED,
            searchable=False,
            recorded_at=NOW,
        )


def test_unknown_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        EmbeddingModelIdentity(
            model_id="fixture_hash_v1",
            version="dev-1",
            dimensions=8,
            normalization="l2",
            configuration_hash=CONFIG_HASH,
            promotion_class=EmbeddingPromotionClass.DEVELOPMENT_FIXTURE,
            extra="nope",  # type: ignore[call-arg]
        )
