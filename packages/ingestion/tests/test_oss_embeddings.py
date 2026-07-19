"""OSS production-local embedding + lexical rerank tests."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from rsi_atlas_contracts import (
    ComponentRank,
    EmbeddingPromotionClass,
    EvidenceItemKind,
    FusedEvidenceItem,
    RetrievalDataPlane,
)
from rsi_atlas_ingestion.embedding import (
    DeterministicEmbedder,
    OfflineArtifactUnavailable,
    OfflineOnnxEmbedder,
    TokenHashEmbedder,
    resolve_embedder,
)
from rsi_atlas_retrieval.rerank import lexical_overlap_score, rerank_fused_lexical


def test_token_hash_embedder_is_candidate_and_deterministic() -> None:
    embedder = TokenHashEmbedder()
    assert embedder.model.promotion_class is EmbeddingPromotionClass.CANDIDATE
    assert embedder.model.model_id == "oss_token_hash_v1"
    a = embedder.embed_text("governance proposal quorum")
    b = embedder.embed_text("governance proposal quorum")
    assert a == b
    assert len(a) == 64


def test_resolve_embedder_defaults_to_fixture() -> None:
    embedder = resolve_embedder(prefer="fixture")
    assert isinstance(embedder, DeterministicEmbedder)


def test_resolve_onnx_fail_closed_without_artifact(tmp_path: Path) -> None:
    with pytest.raises(OfflineArtifactUnavailable):
        OfflineOnnxEmbedder(tmp_path / "missing")


def _item(*, chunk_hex: str, score: float, rank: int, preview: str) -> FusedEvidenceItem:
    return FusedEvidenceItem(
        chunk_id="chunk:" + chunk_hex,
        document_version_id="canonical:" + "b" * 64,
        chunk_set_id="chunkset:" + "c" * 64,
        publication_id="publication:" + "d" * 64,
        index_version_id=uuid4(),
        item_kind=EvidenceItemKind.SOURCE_CONTENT,
        fusion_score=score,
        fusion_rank=rank,
        reliability_score=0.5,
        component_ranks=(
            ComponentRank(
                data_plane=RetrievalDataPlane.LEXICAL,
                rank=rank,
                raw_score=score,
            ),
        ),
        excerpt_hash="e" * 64,
        text_preview=preview,
    )


def test_lexical_rerank_prefers_overlap() -> None:
    low = _item(
        chunk_hex="a" * 64,
        score=0.1,
        rank=2,
        preview="unrelated noise text",
    )
    high = _item(
        chunk_hex="f" * 64,
        score=0.05,
        rank=1,
        preview="bitcoin fee regime change proposal",
    )
    assert lexical_overlap_score(query="bitcoin fee regime", preview=high.text_preview) > 0
    reranked = rerank_fused_lexical(
        query="bitcoin fee regime",
        items=(low, high),
        final_k=2,
    )
    assert reranked[0].chunk_id == high.chunk_id
    assert reranked[0].fusion_rank == 1
