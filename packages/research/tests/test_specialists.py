"""Multi-specialist extractive orchestration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from rsi_atlas_contracts import (
    ComponentRank,
    CoverageCell,
    CoverageStatus,
    DataCutoffManifest,
    EvidencePacket,
    FusedEvidenceItem,
    RetrievalDataPlane,
    SpecialistTask,
    SpecialistType,
    data_cutoff_manifest_hash,
    evidence_packet_id,
    retrieval_run_id,
    specialist_task_id,
)
from rsi_atlas_research.specialists import ExtractiveSpecialist

INDEX_VERSION_ID = UUID("00000000-0000-4000-8000-0000000000cc")
DOCUMENT_VERSION = "canonical:" + ("a" * 64)
CHUNK_SET_ID = "chunkset:" + ("b" * 64)
CHUNK_ID = "chunk:" + ("c" * 64)
PUBLICATION_ID = "publication:" + ("d" * 64)
EXCERPT_HASH = "e" * 64
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
QUERY_ID = UUID("00000000-0000-4000-8000-0000000000aa")


def _packet(*, preview: str) -> EvidencePacket:
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
        text_preview=preview,
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


def test_tokenomics_specialist_finds_unlock() -> None:
    packet = _packet(
        preview="Token unlock and vesting schedule begins in 2027 for circulating supply."
    )
    task = SpecialistTask(
        task_id=specialist_task_id(
            run_id=packet.run_id,
            specialist_type=SpecialistType.TOKENOMICS,
            subquestion="What is the unlock schedule?",
        ),
        specialist_type=SpecialistType.TOKENOMICS,
        run_id=packet.run_id,
        packet_id=packet.packet_id,
        subquestion="What is the unlock schedule?",
        context_budget_tokens=512,
        repair_limit=1,
    )
    finding = ExtractiveSpecialist(SpecialistType.TOKENOMICS).run(task=task, packet=packet, now=NOW)
    assert finding.specialist_type is SpecialistType.TOKENOMICS
    assert finding.supporting_chunk_ids
