"""Select embedder: fixture (default), OSS token-hash, or fail-closed ONNX artifact."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from rsi_atlas_contracts import EmbeddingModelIdentity

from rsi_atlas_ingestion.embedding.deterministic import DeterministicEmbedder, EmbeddingError
from rsi_atlas_ingestion.embedding.offline_onnx import (
    OfflineArtifactUnavailable,
    OfflineOnnxEmbedder,
)
from rsi_atlas_ingestion.embedding.token_hash import TokenHashEmbedder


class Embedder(Protocol):
    @property
    def model(self) -> EmbeddingModelIdentity: ...

    @property
    def input_policy_hash(self) -> str: ...

    def embed_text(self, text: str) -> tuple[float, ...]: ...


def resolve_embedder(
    *,
    prefer: str | None = None,
    artifact_dir: Path | None = None,
) -> Embedder:
    """Resolve embedder from explicit prefer or env. Never downloads models.

    RSI_ATLAS_EMBEDDER=fixture|oss_token_hash|onnx
    RSI_ATLAS_EMBEDDING_ARTIFACT_DIR=/path/to/manifest+onnx
    """
    choice = (prefer or os.environ.get("RSI_ATLAS_EMBEDDER", "fixture")).strip().lower()
    if choice in {"fixture", "fixture_hash_v1", "deterministic"}:
        return DeterministicEmbedder()
    if choice in {"oss_token_hash", "oss_token_hash_v1", "token_hash"}:
        return TokenHashEmbedder()
    if choice in {"onnx", "offline_onnx"}:
        root = (
            artifact_dir
            or Path(os.environ.get("RSI_ATLAS_EMBEDDING_ARTIFACT_DIR", "")).expanduser()
        )
        if not str(root):
            raise OfflineArtifactUnavailable(
                "RSI_ATLAS_EMBEDDING_ARTIFACT_DIR required for onnx embedder"
            )
        return OfflineOnnxEmbedder(root)
    raise EmbeddingError(f"unknown embedder preference: {choice}")


__all__ = [
    "Embedder",
    "resolve_embedder",
]
