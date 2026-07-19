"""Development and OSS production-local embedding adapters."""

from rsi_atlas_ingestion.embedding.deterministic import (
    DEVELOPMENT_EMBEDDING_MODEL,
    DeterministicEmbedder,
    EmbeddingError,
)
from rsi_atlas_ingestion.embedding.offline_onnx import (
    OfflineArtifactUnavailable,
    OfflineOnnxEmbedder,
)
from rsi_atlas_ingestion.embedding.resolve import Embedder, resolve_embedder
from rsi_atlas_ingestion.embedding.token_hash import OSS_TOKEN_HASH_MODEL, TokenHashEmbedder

__all__ = [
    "DEVELOPMENT_EMBEDDING_MODEL",
    "OSS_TOKEN_HASH_MODEL",
    "DeterministicEmbedder",
    "Embedder",
    "EmbeddingError",
    "OfflineArtifactUnavailable",
    "OfflineOnnxEmbedder",
    "TokenHashEmbedder",
    "resolve_embedder",
]
