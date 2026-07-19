"""Strict Phase 3 retrieval contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ComponentRank,
    CoverageCell,
    CoverageStatus,
    DataCutoffManifest,
    EvidenceCandidate,
    EvidenceItemKind,
    EvidencePacket,
    FusedEvidenceItem,
    QueryFamily,
    ResearchQuery,
    RetrievalAbstention,
    RetrievalDataPlane,
    RetrievalPlan,
    RetrievalStep,
    data_cutoff_manifest_hash,
    evidence_candidate_id,
    evidence_packet_id,
    retrieval_plan_hash,
    retrieval_run_id,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
QUERY_ID = UUID("00000000-0000-4000-8000-0000000000aa")
PLAN_ID = UUID("00000000-0000-4000-8000-0000000000bb")
INDEX_VERSION_ID = UUID("00000000-0000-4000-8000-0000000000cc")
DOCUMENT_VERSION = "canonical:" + ("a" * 64)
CHUNK_SET_ID = "chunkset:" + ("b" * 64)
CHUNK_ID = "chunk:" + ("c" * 64)
PUBLICATION_ID = "publication:" + ("d" * 64)
EXCERPT_HASH = "e" * 64
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


def _cutoff() -> DataCutoffManifest:
    publication_ids = (PUBLICATION_ID,)
    index_version_ids = (INDEX_VERSION_ID,)
    return DataCutoffManifest(
        effective_as_of=NOW,
        document_cutoff=NOW,
        publication_ids=publication_ids,
        index_version_ids=index_version_ids,
        staleness_findings=(),
        manifest_hash=data_cutoff_manifest_hash(
            effective_as_of=NOW,
            document_cutoff=NOW,
            publication_ids=publication_ids,
            index_version_ids=index_version_ids,
            staleness_findings=(),
        ),
    )


def test_research_query_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        ResearchQuery(
            context=_context(),
            query_id=QUERY_ID,
            text="   ",
            document_version_ids=(DOCUMENT_VERSION,),
            chunk_set_ids=(CHUNK_SET_ID,),
            as_of=NOW,
            query_family=QueryFamily.NARRATIVE_EXPLANATION,
            latency_budget_ms=1_000,
            context_budget_tokens=1_024,
        )


def test_retrieval_step_blocks_chain_snapshot_plane() -> None:
    with pytest.raises(ValidationError, match="blocked"):
        RetrievalStep(
            step_id="chain_step",
            data_plane=RetrievalDataPlane.CHAIN_SNAPSHOT,
            retriever="chain_snapshot_v1",
            query_text="supply",
            top_k=10,
            required=True,
            expected_evidence="chain state",
        )


def test_retrieval_plan_hash_is_deterministic() -> None:
    step = RetrievalStep(
        step_id="lexical_step",
        data_plane=RetrievalDataPlane.LEXICAL,
        retriever="pg_fts_v1",
        query_text="token unlock",
        top_k=10,
        required=True,
        expected_evidence="unlock schedule prose",
    )
    plan_hash = retrieval_plan_hash(
        query_id=QUERY_ID,
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        steps=(step,),
    )
    plan = RetrievalPlan(
        plan_id=PLAN_ID,
        query_id=QUERY_ID,
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        steps=(step,),
        plan_hash=plan_hash,
    )
    assert plan.plan_hash == plan_hash


def test_evidence_candidate_id_must_match() -> None:
    candidate_id = evidence_candidate_id(
        chunk_id=CHUNK_ID,
        data_plane=RetrievalDataPlane.DENSE_DOCUMENT,
        index_version_id=INDEX_VERSION_ID,
        rank=1,
    )
    candidate = EvidenceCandidate(
        candidate_id=candidate_id,
        chunk_id=CHUNK_ID,
        document_version_id=DOCUMENT_VERSION,
        chunk_set_id=CHUNK_SET_ID,
        publication_id=PUBLICATION_ID,
        index_version_id=INDEX_VERSION_ID,
        data_plane=RetrievalDataPlane.DENSE_DOCUMENT,
        raw_score=0.9,
        rank=1,
        reliability_score=0.8,
        excerpt_hash=EXCERPT_HASH,
        text_preview="unlock schedule",
    )
    assert candidate.candidate_id.startswith("candidate:")
    with pytest.raises(ValidationError, match="candidate_id"):
        EvidenceCandidate(
            candidate_id="candidate:" + ("0" * 64),
            chunk_id=CHUNK_ID,
            document_version_id=DOCUMENT_VERSION,
            chunk_set_id=CHUNK_SET_ID,
            publication_id=PUBLICATION_ID,
            index_version_id=INDEX_VERSION_ID,
            data_plane=RetrievalDataPlane.DENSE_DOCUMENT,
            raw_score=0.9,
            rank=1,
            reliability_score=0.8,
            excerpt_hash=EXCERPT_HASH,
            text_preview="unlock schedule",
        )


def test_evidence_packet_and_abstention() -> None:
    cutoff = _cutoff()
    run_id = retrieval_run_id(
        query_id=QUERY_ID,
        plan_hash="f" * 64,
        cutoff_hash=cutoff.manifest_hash,
    )
    item = FusedEvidenceItem(
        chunk_id=CHUNK_ID,
        document_version_id=DOCUMENT_VERSION,
        chunk_set_id=CHUNK_SET_ID,
        publication_id=PUBLICATION_ID,
        index_version_id=INDEX_VERSION_ID,
        fusion_score=0.5,
        fusion_rank=1,
        reliability_score=0.7,
        component_ranks=(
            ComponentRank(
                data_plane=RetrievalDataPlane.LEXICAL,
                rank=1,
                raw_score=1.0,
            ),
        ),
        excerpt_hash=EXCERPT_HASH,
        text_preview="unlock schedule",
    )
    packet_id = evidence_packet_id(
        run_id=run_id,
        plan_hash="f" * 64,
        cutoff_hash=cutoff.manifest_hash,
        items=(item,),
    )
    packet = EvidencePacket(
        packet_id=packet_id,
        run_id=run_id,
        query_id=QUERY_ID,
        plan_hash="f" * 64,
        cutoff=cutoff,
        items=(item,),
        coverage=(
            CoverageCell(
                requirement_id="primary_prose",
                status=CoverageStatus.SATISFIED,
                detail="lexical hit present",
            ),
        ),
        recorded_at=NOW,
    )
    assert packet.outcome.value == "packet"
    assert packet.items[0].item_kind is EvidenceItemKind.SOURCE_CONTENT

    abstention = RetrievalAbstention(
        run_id=run_id,
        query_id=QUERY_ID,
        plan_hash="f" * 64,
        cutoff=cutoff,
        coverage=(
            CoverageCell(
                requirement_id="primary_prose",
                status=CoverageStatus.MISSING,
                detail="no active publication hits",
            ),
        ),
        reason="insufficient evidence for material question",
        recorded_at=NOW,
    )
    assert abstention.outcome.value == "abstain"
