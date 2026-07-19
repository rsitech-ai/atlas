"""Hybrid retrieval over active Phase 2D publications."""

from rsi_atlas_retrieval.fusion import FUSION_CONFIGURATION_HASH, fuse_candidates_rrf
from rsi_atlas_retrieval.packet import HybridRetrievalService, RetrievalServiceError
from rsi_atlas_retrieval.rerank import RERANK_CONFIGURATION_HASH, rerank_fused_lexical
from rsi_atlas_retrieval.search import HybridCandidateGenerator

__all__ = [
    "FUSION_CONFIGURATION_HASH",
    "RERANK_CONFIGURATION_HASH",
    "HybridCandidateGenerator",
    "HybridRetrievalService",
    "RetrievalServiceError",
    "fuse_candidates_rrf",
    "rerank_fused_lexical",
]
