"""Development embedding adapters for Phase 2D index staging."""

from rsi_atlas_ingestion.embedding.deterministic import (
    DEVELOPMENT_EMBEDDING_MODEL,
    DeterministicEmbedder,
    EmbeddingError,
)

__all__ = [
    "DEVELOPMENT_EMBEDDING_MODEL",
    "DeterministicEmbedder",
    "EmbeddingError",
]
