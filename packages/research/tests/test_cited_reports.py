"""Assertion, citation, and report gate tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ComponentRank,
    CoverageCell,
    CoverageStatus,
    DataCutoffManifest,
    EvidencePacket,
    FindingCompletionStatus,
    FusedEvidenceItem,
    RetrievalDataPlane,
    ReviewAction,
    SpecialistFinding,
    SpecialistType,
    data_cutoff_manifest_hash,
    evidence_packet_id,
    retrieval_run_id,
    specialist_finding_id,
)
from rsi_atlas_research import (
    AssertionBuilder,
    CitationBinder,
    ReportGate,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
INDEX_VERSION_ID = UUID("00000000-0000-4000-8000-0000000000cc")
QUERY_ID = UUID("00000000-0000-4000-8000-0000000000aa")
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


def _packet() -> EvidencePacket:
    cutoff_hash = data_cutoff_manifest_hash(
        effective_as_of=NOW,
        document_cutoff=NOW,
        publication_ids=(PUBLICATION_ID,),
        index_version_ids=(INDEX_VERSION_ID,),
        staleness_findings=(),
    )
    cutoff = DataCutoffManifest(
        effective_as_of=NOW,
        document_cutoff=NOW,
        publication_ids=(PUBLICATION_ID,),
        index_version_ids=(INDEX_VERSION_ID,),
        staleness_findings=(),
        manifest_hash=cutoff_hash,
    )
    plan_hash = "f" * 64
    run_id = retrieval_run_id(query_id=QUERY_ID, plan_hash=plan_hash, cutoff_hash=cutoff_hash)
    item = FusedEvidenceItem(
        chunk_id=CHUNK_ID,
        document_version_id=DOCUMENT_VERSION,
        chunk_set_id=CHUNK_SET_ID,
        publication_id=PUBLICATION_ID,
        index_version_id=INDEX_VERSION_ID,
        fusion_score=0.5,
        fusion_rank=1,
        reliability_score=0.8,
        component_ranks=(
            ComponentRank(data_plane=RetrievalDataPlane.LEXICAL, rank=1, raw_score=1.0),
        ),
        excerpt_hash=EXCERPT_HASH,
        text_preview="Token unlocks begin in 2027.",
    )
    return EvidencePacket(
        packet_id=evidence_packet_id(
            run_id=run_id,
            plan_hash=plan_hash,
            cutoff_hash=cutoff_hash,
            items=(item,),
        ),
        run_id=run_id,
        query_id=QUERY_ID,
        plan_hash=plan_hash,
        cutoff=cutoff,
        items=(item,),
        coverage=(
            CoverageCell(
                requirement_id="primary_document_evidence",
                status=CoverageStatus.SATISFIED,
                detail="ok",
            ),
        ),
        recorded_at=NOW,
    )


def test_assertion_citation_report_and_review_pipeline() -> None:
    packet = _packet()
    task_id = "task:" + ("1" * 64)
    finding = SpecialistFinding(
        finding_id=specialist_finding_id(
            task_id=task_id,
            answer="Token unlocks begin in 2027.",
            completion_status=FindingCompletionStatus.SUPPORTED,
            supporting_chunk_ids=(CHUNK_ID,),
        ),
        task_id=task_id,
        specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
        answer="Token unlocks begin in 2027.",
        supporting_chunk_ids=(CHUNK_ID,),
        completion_status=FindingCompletionStatus.SUPPORTED,
        confidence=0.9,
        recorded_at=NOW,
    )
    assertion = AssertionBuilder().from_finding(run_id=packet.run_id, finding=finding)
    assert assertion is not None
    citations = CitationBinder().bind_assertion(assertion=assertion, packet=packet)
    assert len(citations) == 1
    draft = ReportGate().draft(
        context=_context(),
        run_id=packet.run_id,
        title="Unlock note",
        assertions=(assertion,),
        citations=citations,
        prose="Token unlocks begin in 2027.",
        now=NOW,
    )
    assert draft.report_id.startswith("report:")
    decision = ReportGate().review(
        context=_context(),
        report=draft,
        action=ReviewAction.APPROVE,
        rationale="Citations resolve to source excerpts.",
        now=NOW,
    )
    assert decision.action is ReviewAction.APPROVE
