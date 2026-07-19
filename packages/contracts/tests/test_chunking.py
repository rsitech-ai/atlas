"""Strict Phase 2C chunking contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts import (
    IMPLEMENTED_CHUNK_FAMILIES,
    ArtifactCommandContext,
    ArtifactDescriptor,
    ChunkEmbeddingState,
    ChunkEvaluationStatus,
    ChunkRelationship,
    ChunkRelationshipKind,
    ChunkSet,
    ChunkSetManifestDraft,
    ChunkStrategyFamily,
    ChunkStrategyIdentity,
    DocumentProcessingLifecycle,
    build_chunk,
    build_chunk_set,
    chunk_set_key,
    measure_chunk_set_quality,
    sha256_text,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
ACQUISITION_ID = UUID("00000000-0000-4000-8000-000000000005")
MANIFEST_ID = UUID("00000000-0000-4000-8000-00000000000a")
DOCUMENT_VERSION = "canonical:" + ("a" * 64)
CANONICAL_HASH = "b" * 64
CONFIG_HASH = "c" * 64
ELEMENT_A = "element:" + ("1" * 64)
ELEMENT_B = "element:" + ("2" * 64)
NOW = datetime(2026, 7, 19, 11, 0, tzinfo=UTC)


def _strategy(
    family: ChunkStrategyFamily = ChunkStrategyFamily.FIXED_TOKEN,
) -> ChunkStrategyIdentity:
    return ChunkStrategyIdentity(
        family=family,
        strategy_id=family.value,
        version="dev-1",
        configuration_hash=CONFIG_HASH,
    )


def _chunk_set(
    *,
    family: ChunkStrategyFamily = ChunkStrategyFamily.FIXED_TOKEN,
    text: str = "Bitcoin settles every ten minutes.",
) -> ChunkSet:
    strategy = _strategy(family)
    key = chunk_set_key(document_version_id=DOCUMENT_VERSION, strategy=strategy)
    chunk = build_chunk(
        chunk_set_key_value=key,
        ordinal=0,
        source_element_ids=(ELEMENT_A,),
        text=text,
        token_count=5,
        page_numbers=(1,),
    )
    return build_chunk_set(
        document_version_id=DOCUMENT_VERSION,
        canonical_content_hash=CANONICAL_HASH,
        strategy=strategy,
        chunks=(chunk,),
    )


def test_registry_lists_exactly_five_implemented_families() -> None:
    assert {
        "fixed_token",
        "recursive",
        "page_based",
        "parent_child",
        "table_aware",
    } == IMPLEMENTED_CHUNK_FAMILIES
    assert len(ChunkStrategyFamily) == 20


def test_lifecycle_includes_chunked_not_published() -> None:
    values = {state.value for state in DocumentProcessingLifecycle}
    assert "chunked" in values
    assert "published" not in values
    assert "searchable" not in values


def test_chunk_rejects_unknown_fields() -> None:
    strategy = _strategy()
    key = chunk_set_key(document_version_id=DOCUMENT_VERSION, strategy=strategy)
    chunk = build_chunk(
        chunk_set_key_value=key,
        ordinal=0,
        source_element_ids=(ELEMENT_A,),
        text="ok",
        token_count=1,
        page_numbers=(1,),
    )
    with pytest.raises(ValidationError):
        chunk.model_validate({**chunk.model_dump(mode="json"), "unexpected": True})


def test_chunk_rejects_text_hash_mismatch() -> None:
    strategy = _strategy()
    key = chunk_set_key(document_version_id=DOCUMENT_VERSION, strategy=strategy)
    chunk = build_chunk(
        chunk_set_key_value=key,
        ordinal=0,
        source_element_ids=(ELEMENT_A,),
        text="ok",
        token_count=1,
        page_numbers=(1,),
    )
    payload = chunk.model_dump(mode="json")
    payload["text_hash"] = "0" * 64
    with pytest.raises(ValidationError):
        type(chunk).model_validate(payload)


def test_chunk_rejects_duplicate_source_elements() -> None:
    strategy = _strategy()
    key = chunk_set_key(document_version_id=DOCUMENT_VERSION, strategy=strategy)
    with pytest.raises(ValidationError):
        build_chunk(
            chunk_set_key_value=key,
            ordinal=0,
            source_element_ids=(ELEMENT_A, ELEMENT_A),
            text="ok",
            token_count=1,
            page_numbers=(1,),
        )


def test_unimplemented_family_fails_closed() -> None:
    strategy = ChunkStrategyIdentity(
        family=ChunkStrategyFamily.LATE_CHUNKING,
        strategy_id="late_chunking",
        version="dev-1",
        configuration_hash=CONFIG_HASH,
    )
    key = chunk_set_key(document_version_id=DOCUMENT_VERSION, strategy=strategy)
    chunk = build_chunk(
        chunk_set_key_value=key,
        ordinal=0,
        source_element_ids=(ELEMENT_A,),
        text="ok",
        token_count=1,
        page_numbers=(1,),
    )
    with pytest.raises(ValueError, match="not implemented"):
        build_chunk_set(
            document_version_id=DOCUMENT_VERSION,
            canonical_content_hash=CANONICAL_HASH,
            strategy=strategy,
            chunks=(chunk,),
        )


def test_build_chunk_set_is_deterministic() -> None:
    first = _chunk_set()
    second = _chunk_set()
    assert first.chunk_set_id == second.chunk_set_id
    assert first.content_hash() == second.content_hash()
    assert first.canonical_json_bytes() == second.canonical_json_bytes()
    assert first.embedding_state is ChunkEmbeddingState.NONE


def test_relationship_must_reference_known_chunks() -> None:
    strategy = _strategy(ChunkStrategyFamily.PARENT_CHILD)
    key = chunk_set_key(document_version_id=DOCUMENT_VERSION, strategy=strategy)
    parent = build_chunk(
        chunk_set_key_value=key,
        ordinal=0,
        source_element_ids=(ELEMENT_A,),
        text="Section",
        token_count=1,
        page_numbers=(1,),
        metadata={"role": "parent"},
    )
    child = build_chunk(
        chunk_set_key_value=key,
        ordinal=1,
        source_element_ids=(ELEMENT_B,),
        text="Passage",
        token_count=1,
        page_numbers=(1,),
        metadata={"role": "child"},
    )
    with pytest.raises(ValidationError, match="unknown chunk"):
        build_chunk_set(
            document_version_id=DOCUMENT_VERSION,
            canonical_content_hash=CANONICAL_HASH,
            strategy=strategy,
            chunks=(parent, child),
            relationships=(
                ChunkRelationship(
                    kind=ChunkRelationshipKind.CHILD,
                    from_chunk_id=parent.chunk_id,
                    to_chunk_id="chunk:" + ("f" * 64),
                ),
            ),
        )


def test_quality_metrics_match_chunks() -> None:
    strategy = _strategy()
    key = chunk_set_key(document_version_id=DOCUMENT_VERSION, strategy=strategy)
    chunks = (
        build_chunk(
            chunk_set_key_value=key,
            ordinal=0,
            source_element_ids=(ELEMENT_A,),
            text="one",
            token_count=10,
            page_numbers=(1,),
        ),
        build_chunk(
            chunk_set_key_value=key,
            ordinal=1,
            source_element_ids=(ELEMENT_B,),
            text="two",
            token_count=30,
            page_numbers=(1, 2),
        ),
    )
    quality = measure_chunk_set_quality(chunks)
    assert quality.chunk_count == 2
    assert quality.min_token_count == 10
    assert quality.max_token_count == 30
    assert quality.mean_token_count == 20.0
    built = build_chunk_set(
        document_version_id=DOCUMENT_VERSION,
        canonical_content_hash=CANONICAL_HASH,
        strategy=strategy,
        chunks=chunks,
        quality=quality,
        evaluation_status=ChunkEvaluationStatus.INTRINSIC_PASS,
    )
    assert built.quality == quality


def test_manifest_binds_artifact_digest_to_chunk_set_bytes() -> None:
    chunk_set = _chunk_set()
    content_hash = chunk_set.content_hash()
    artifact = ArtifactDescriptor(
        artifact_id=f"sha256:{content_hash}",
        digest=content_hash,
        size_bytes=len(chunk_set.canonical_json_bytes()),
        media_type="application/vnd.rsi-atlas.chunk-set+json",
    )
    manifest = ChunkSetManifestDraft(
        manifest_id=MANIFEST_ID,
        context=ArtifactCommandContext(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            trace_id=TRACE_ID,
        ),
        acquisition_id=ACQUISITION_ID,
        document_version_id=DOCUMENT_VERSION,
        canonical_content_hash=CANONICAL_HASH,
        chunk_set=chunk_set,
        chunk_set_content_hash=content_hash,
        chunk_set_artifact=artifact,
        lifecycle=DocumentProcessingLifecycle.CHUNKED,
        recorded_at=NOW,
    )
    assert manifest.chunk_set_content_hash == sha256(chunk_set.canonical_json_bytes()).hexdigest()
    assert sha256_text(chunk_set.chunks[0].text) == chunk_set.chunks[0].text_hash


def test_manifest_rejects_wrong_media_type() -> None:
    chunk_set = _chunk_set()
    content_hash = chunk_set.content_hash()
    with pytest.raises(ValidationError, match="media type"):
        ChunkSetManifestDraft(
            manifest_id=MANIFEST_ID,
            context=ArtifactCommandContext(
                tenant_id=TENANT_ID,
                workspace_id=WORKSPACE_ID,
                actor_id=ACTOR_ID,
                trace_id=TRACE_ID,
            ),
            acquisition_id=ACQUISITION_ID,
            document_version_id=DOCUMENT_VERSION,
            canonical_content_hash=CANONICAL_HASH,
            chunk_set=chunk_set,
            chunk_set_content_hash=content_hash,
            chunk_set_artifact=ArtifactDescriptor(
                artifact_id=f"sha256:{content_hash}",
                digest=content_hash,
                size_bytes=len(chunk_set.canonical_json_bytes()),
                media_type="application/json",
            ),
            lifecycle=DocumentProcessingLifecycle.CHUNKED,
            recorded_at=NOW,
        )


def test_strategy_id_must_match_family() -> None:
    with pytest.raises(ValidationError):
        ChunkStrategyIdentity(
            family=ChunkStrategyFamily.RECURSIVE,
            strategy_id="fixed_token",
            version="dev-1",
            configuration_hash=CONFIG_HASH,
        )
