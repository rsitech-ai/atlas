"""Unit tests for RRF fusion, coverage, and packet identity."""

from __future__ import annotations

from uuid import UUID

from rsi_atlas_contracts import (
    EvidenceCandidate,
    QueryFamily,
    RetrievalDataPlane,
    evidence_candidate_id,
)
from rsi_atlas_retrieval.coverage import evaluate_coverage, should_abstain
from rsi_atlas_retrieval.fusion import FUSION_CONFIGURATION_HASH, fuse_candidates_rrf

INDEX_VERSION_ID = UUID("00000000-0000-4000-8000-0000000000cc")
DOCUMENT_VERSION = "canonical:" + ("a" * 64)
CHUNK_SET_ID = "chunkset:" + ("b" * 64)
CHUNK_A = "chunk:" + ("c" * 64)
CHUNK_B = "chunk:" + ("d" * 64)
PUBLICATION_ID = "publication:" + ("e" * 64)
EXCERPT = "f" * 64


def _candidate(
    *,
    chunk_id: str,
    plane: RetrievalDataPlane,
    rank: int,
    score: float,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id=evidence_candidate_id(
            chunk_id=chunk_id,
            data_plane=plane,
            index_version_id=INDEX_VERSION_ID,
            rank=rank,
        ),
        chunk_id=chunk_id,
        document_version_id=DOCUMENT_VERSION,
        chunk_set_id=CHUNK_SET_ID,
        publication_id=PUBLICATION_ID,
        index_version_id=INDEX_VERSION_ID,
        data_plane=plane,
        raw_score=score,
        rank=rank,
        reliability_score=0.9,
        excerpt_hash=EXCERPT,
        text_preview="token unlock schedule",
    )


def test_rrf_fusion_is_deterministic_and_inspectable() -> None:
    dense = (
        _candidate(chunk_id=CHUNK_A, plane=RetrievalDataPlane.DENSE_DOCUMENT, rank=1, score=0.9),
        _candidate(chunk_id=CHUNK_B, plane=RetrievalDataPlane.DENSE_DOCUMENT, rank=2, score=0.5),
    )
    lexical = (
        _candidate(chunk_id=CHUNK_B, plane=RetrievalDataPlane.LEXICAL, rank=1, score=1.0),
        _candidate(chunk_id=CHUNK_A, plane=RetrievalDataPlane.LEXICAL, rank=2, score=0.4),
    )
    fused = fuse_candidates_rrf(
        candidates_by_plane={
            RetrievalDataPlane.DENSE_DOCUMENT: dense,
            RetrievalDataPlane.LEXICAL: lexical,
        },
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        final_k=10,
    )
    assert len(fused) == 2
    assert fused[0].fusion_rank == 1
    assert fused[1].fusion_rank == 2
    assert len(fused[0].component_ranks) == 2
    again = fuse_candidates_rrf(
        candidates_by_plane={
            RetrievalDataPlane.DENSE_DOCUMENT: dense,
            RetrievalDataPlane.LEXICAL: lexical,
        },
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        final_k=10,
    )
    assert [item.chunk_id for item in fused] == [item.chunk_id for item in again]
    assert FUSION_CONFIGURATION_HASH


def test_coverage_abstains_when_empty() -> None:
    coverage = evaluate_coverage(
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        items=(),
    )
    assert should_abstain(coverage)


def test_exact_lookup_requires_exact_component() -> None:
    dense_only = fuse_candidates_rrf(
        candidates_by_plane={
            RetrievalDataPlane.DENSE_DOCUMENT: (
                _candidate(
                    chunk_id=CHUNK_A,
                    plane=RetrievalDataPlane.DENSE_DOCUMENT,
                    rank=1,
                    score=0.8,
                ),
            )
        },
        query_family=QueryFamily.EXACT_LOOKUP,
        final_k=5,
    )
    coverage = evaluate_coverage(query_family=QueryFamily.EXACT_LOOKUP, items=dense_only)
    assert should_abstain(coverage)
