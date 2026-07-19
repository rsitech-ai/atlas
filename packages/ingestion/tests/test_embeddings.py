"""Development embedding adapter tests (deterministic hash→vector)."""

from __future__ import annotations

import math

import pytest
from rsi_atlas_contracts import (
    DEVELOPMENT_EMBEDDING_DIMENSIONS,
    EmbeddingPromotionClass,
    validate_vector,
)
from rsi_atlas_ingestion.embedding import (
    DEVELOPMENT_EMBEDDING_MODEL,
    DeterministicEmbedder,
    EmbeddingError,
)


def test_development_model_is_fixture_only() -> None:
    model = DEVELOPMENT_EMBEDDING_MODEL
    assert model.promotion_class is EmbeddingPromotionClass.DEVELOPMENT_FIXTURE
    assert model.dimensions == DEVELOPMENT_EMBEDDING_DIMENSIONS
    assert model.model_id.startswith("fixture_")


def test_identical_text_yields_identical_vector() -> None:
    embedder = DeterministicEmbedder()
    first = embedder.embed_text("Bitcoin settles every ten minutes.")
    second = embedder.embed_text("Bitcoin settles every ten minutes.")
    assert first == second
    validate_vector(first, dimensions=DEVELOPMENT_EMBEDDING_DIMENSIONS)
    norm = math.sqrt(sum(component * component for component in first))
    assert abs(norm - 1.0) < 1e-6


def test_different_text_yields_different_vector() -> None:
    embedder = DeterministicEmbedder()
    left = embedder.embed_text("Bitcoin")
    right = embedder.embed_text("Ethereum")
    assert left != right


def test_cache_hits_by_text_hash() -> None:
    embedder = DeterministicEmbedder()
    first = embedder.embed_text("cache me")
    second = embedder.embed_text("cache me")
    assert first is second or first == second
    assert embedder.cache_hits >= 1


def test_rejects_empty_text() -> None:
    embedder = DeterministicEmbedder()
    with pytest.raises(EmbeddingError, match="empty"):
        embedder.embed_text("")
    with pytest.raises(EmbeddingError, match="empty"):
        embedder.embed_text("   ")
