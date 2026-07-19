"""Document specialist and plan validation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from rsi_atlas_contracts import (
    ComponentRank,
    CoverageCell,
    CoverageStatus,
    DataCutoffManifest,
    EvidencePacket,
    FusedEvidenceItem,
    QueryFamily,
    RetrievalDataPlane,
    RetrievalPlan,
    RetrievalStep,
    SpecialistTask,
    SpecialistType,
    data_cutoff_manifest_hash,
    evidence_packet_id,
    retrieval_plan_hash,
    retrieval_run_id,
    specialist_task_id,
)
from rsi_atlas_research import (
    DocumentEvidenceSpecialist,
    PlanValidationError,
    validate_retrieval_plan,
)

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


def test_validate_plan_rejects_empty_required_steps() -> None:
    step = RetrievalStep(
        step_id="optional_only",
        data_plane=RetrievalDataPlane.LEXICAL,
        retriever="pg_fts_v1",
        query_text="token",
        top_k=10,
        required=False,
        expected_evidence="optional prose",
    )
    plan = RetrievalPlan(
        plan_id=uuid4(),
        query_id=QUERY_ID,
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        steps=(step,),
        plan_hash=retrieval_plan_hash(
            query_id=QUERY_ID,
            query_family=QueryFamily.NARRATIVE_EXPLANATION,
            steps=(step,),
        ),
    )
    with pytest.raises(PlanValidationError, match="required"):
        validate_retrieval_plan(plan)


def test_document_specialist_returns_supported_finding() -> None:
    packet = _packet(preview="Token unlock schedule begins in 2027 for Bitcoin research.")
    task_id = specialist_task_id(
        run_id=packet.run_id,
        specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
        subquestion="When does the unlock schedule begin?",
    )
    task = SpecialistTask(
        task_id=task_id,
        specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
        run_id=packet.run_id,
        packet_id=packet.packet_id,
        subquestion="When does the unlock schedule begin?",
        context_budget_tokens=512,
        repair_limit=1,
    )
    finding = DocumentEvidenceSpecialist().run(task=task, packet=packet, now=NOW)
    assert finding.supporting_chunk_ids == (CHUNK_ID,)
    assert finding.completion_status.value in {"supported", "partially_supported"}
