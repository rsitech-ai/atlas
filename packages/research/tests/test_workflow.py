"""Research workflow interrupt/resume tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    CitationBinding,
    CitationRole,
    ComponentRank,
    CoverageCell,
    CoverageStatus,
    DataCutoffManifest,
    EvidencePacket,
    FindingCompletionStatus,
    FusedEvidenceItem,
    QueryFamily,
    ReportDraft,
    ReportPublicationOutcome,
    ReportSection,
    ResearchAssertion,
    ResearchQuery,
    RetrievalAbstention,
    RetrievalDataPlane,
    ReviewAction,
    ReviewDecision,
    SpecialistFinding,
    SpecialistType,
    citation_binding_id,
    data_cutoff_manifest_hash,
    evidence_packet_id,
    report_draft_id,
    research_assertion_id,
    retrieval_run_id,
    specialist_finding_id,
    specialist_task_id,
)
from rsi_atlas_research.workflow import (
    InMemoryWorkflowStore,
    ResearchWorkflow,
    WorkflowAttempt,
    WorkflowCheckpoint,
    WorkflowInterrupted,
    WorkflowStep,
    workflow_id_for_query,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
QUERY_ID = UUID("00000000-0000-4000-8000-0000000000aa")
PUBLICATION_ID = "publication:" + ("a" * 64)
INDEX_VERSION_ID = UUID("00000000-0000-4000-8000-0000000000cc")
RUN_ID = "retrievalrun:" + ("c" * 64)
DOCUMENT_VERSION = "canonical:" + ("e" * 64)
CHUNK_SET_ID = "chunkset:" + ("f" * 64)
CHUNK_ID = "chunk:" + ("1" * 64)
EXCERPT_HASH = "2" * 64
DECISION_ID = UUID("00000000-0000-4000-8000-0000000000dd")


class _AbstainOrchestrator:
    def retrieve(self, *, query: ResearchQuery, now: datetime | None = None) -> RetrievalAbstention:
        stamped = now or NOW
        cutoff_hash = data_cutoff_manifest_hash(
            effective_as_of=stamped,
            document_cutoff=stamped,
            publication_ids=(PUBLICATION_ID,),
            index_version_ids=(INDEX_VERSION_ID,),
            staleness_findings=(),
        )
        cutoff = DataCutoffManifest(
            effective_as_of=stamped,
            document_cutoff=stamped,
            publication_ids=(PUBLICATION_ID,),
            index_version_ids=(INDEX_VERSION_ID,),
            staleness_findings=(),
            manifest_hash=cutoff_hash,
        )
        return RetrievalAbstention(
            run_id=RUN_ID,
            query_id=query.query_id,
            plan_hash="d" * 64,
            cutoff=cutoff,
            coverage=(
                CoverageCell(
                    requirement_id="primary_evidence",
                    status=CoverageStatus.MISSING,
                    detail="no hits",
                ),
            ),
            reason="insufficient evidence for material question",
            recorded_at=stamped,
        )


class _HappyOrchestrator:
    def retrieve(self, *, query: ResearchQuery, now: datetime | None = None) -> EvidencePacket:
        stamped = now or NOW
        cutoff_hash = data_cutoff_manifest_hash(
            effective_as_of=stamped,
            document_cutoff=stamped,
            publication_ids=(PUBLICATION_ID,),
            index_version_ids=(INDEX_VERSION_ID,),
            staleness_findings=(),
        )
        plan_hash = "d" * 64
        run_id = retrieval_run_id(
            query_id=query.query_id, plan_hash=plan_hash, cutoff_hash=cutoff_hash
        )
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
            text_preview="Fees changed.",
        )
        return EvidencePacket(
            packet_id=evidence_packet_id(
                run_id=run_id,
                plan_hash=plan_hash,
                cutoff_hash=cutoff_hash,
                items=(item,),
            ),
            run_id=run_id,
            query_id=query.query_id,
            plan_hash=plan_hash,
            cutoff=DataCutoffManifest(
                effective_as_of=stamped,
                document_cutoff=stamped,
                publication_ids=(PUBLICATION_ID,),
                index_version_ids=(INDEX_VERSION_ID,),
                staleness_findings=(),
                manifest_hash=cutoff_hash,
            ),
            items=(item,),
            coverage=(
                CoverageCell(
                    requirement_id="primary_document_evidence",
                    status=CoverageStatus.SATISFIED,
                    detail="ok",
                ),
            ),
            recorded_at=stamped,
        )

    def run_document_specialist(
        self,
        *,
        query: ResearchQuery,
        packet: EvidencePacket,
        subquestion: str | None = None,
        now: datetime | None = None,
    ) -> SpecialistFinding:
        del query, subquestion
        stamped = now or NOW
        task_id = specialist_task_id(
            run_id=packet.run_id,
            specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
            subquestion="fees",
        )
        return SpecialistFinding(
            finding_id=specialist_finding_id(
                task_id=task_id,
                answer=packet.items[0].text_preview,
                completion_status=FindingCompletionStatus.SUPPORTED,
                supporting_chunk_ids=(packet.items[0].chunk_id,),
            ),
            task_id=task_id,
            specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
            answer=packet.items[0].text_preview,
            supporting_chunk_ids=(packet.items[0].chunk_id,),
            completion_status=FindingCompletionStatus.SUPPORTED,
            confidence=0.9,
            recorded_at=stamped,
        )

    def draft_report(
        self,
        *,
        query: ResearchQuery,
        packet: EvidencePacket,
        finding: SpecialistFinding,
        title: str,
        now: datetime | None = None,
    ) -> ReportDraft:
        stamped = now or NOW
        assertion = ResearchAssertion(
            assertion_id=research_assertion_id(
                run_id=packet.run_id,
                finding_id=finding.finding_id,
                statement=finding.answer,
                supporting_chunk_ids=finding.supporting_chunk_ids,
            ),
            run_id=packet.run_id,
            finding_id=finding.finding_id,
            statement=finding.answer,
            supporting_chunk_ids=finding.supporting_chunk_ids,
            confidence=finding.confidence,
        )
        citation = CitationBinding(
            citation_id=citation_binding_id(
                assertion_id=assertion.assertion_id,
                chunk_id=finding.supporting_chunk_ids[0],
                role=CitationRole.DIRECT_SUPPORT,
                excerpt_hash=packet.items[0].excerpt_hash,
            ),
            assertion_id=assertion.assertion_id,
            chunk_id=finding.supporting_chunk_ids[0],
            role=CitationRole.DIRECT_SUPPORT,
            excerpt_hash=packet.items[0].excerpt_hash,
            locator="chunk:test",
        )
        return ReportDraft(
            report_id=report_draft_id(
                run_id=packet.run_id,
                title=title,
                version=1,
                assertions=(assertion,),
                citations=(citation,),
            ),
            run_id=packet.run_id,
            context=query.context,
            title=title,
            sections=(
                ReportSection(
                    section_id="findings",
                    title="Findings",
                    prose=finding.answer,
                    assertion_ids=(assertion.assertion_id,),
                ),
            ),
            assertions=(assertion,),
            citations=(citation,),
            outcome=ReportPublicationOutcome.AWAIT_ANALYST_REVIEW,
            version=1,
            recorded_at=stamped,
        )

    def review_report(
        self,
        *,
        query: ResearchQuery,
        report: ReportDraft,
        action: ReviewAction,
        rationale: str,
        now: datetime | None = None,
    ) -> ReviewDecision:
        del query
        return ReviewDecision(
            decision_id=DECISION_ID,
            report_id=report.report_id,
            context=report.context,
            action=action,
            rationale=rationale,
            recorded_at=now or NOW,
        )


def _query() -> ResearchQuery:
    ctx = ArtifactCommandContext(
        workspace_id=uuid4(),
        tenant_id=uuid4(),
        actor_id=uuid4(),
        trace_id=uuid4(),
    )
    return ResearchQuery(
        query_id=QUERY_ID,
        context=ctx,
        text="What changed in fee regime?",
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        subject_ids=("btc:fees",),
        document_version_ids=(DOCUMENT_VERSION,),
        chunk_set_ids=(CHUNK_SET_ID,),
        as_of=NOW,
        latency_budget_ms=5_000,
        context_budget_tokens=2048,
    )


def test_workflow_aborts_on_abstention() -> None:
    workflow = ResearchWorkflow(
        orchestrator=_AbstainOrchestrator(),  # type: ignore[arg-type]
        interrupt_after=None,
    )
    checkpoint = workflow.start(query=_query(), title="Fees")
    assert checkpoint.step is WorkflowStep.ABORTED
    assert checkpoint.run_id == RUN_ID


def test_workflow_store_roundtrip() -> None:
    store = InMemoryWorkflowStore()
    wf_id = workflow_id_for_query(query_id=QUERY_ID)
    checkpoint = WorkflowCheckpoint(
        workflow_id=wf_id,
        query_id=QUERY_ID,
        step=WorkflowStep.AWAITING_HUMAN,
        updated_at=NOW,
    )
    store.save(WorkflowAttempt(checkpoint=checkpoint, title="Fees"))
    loaded = store.get(wf_id)
    assert loaded is not None
    assert loaded.checkpoint == checkpoint
    assert loaded.title == "Fees"


def test_workflow_interrupt_resume_complete() -> None:
    store = InMemoryWorkflowStore()
    workflow = ResearchWorkflow(
        orchestrator=_HappyOrchestrator(),  # type: ignore[arg-type]
        store=store,
        interrupt_after=WorkflowStep.DRAFTED,
    )
    query = _query()
    try:
        workflow.start(query=query, title="Fees")
        raise AssertionError("expected interrupt")
    except WorkflowInterrupted as error:
        assert error.checkpoint.step is WorkflowStep.AWAITING_HUMAN
        assert error.checkpoint.report_id is not None
        report_id = error.checkpoint.report_id

    # Simulate process restart: new workflow instance, same durable store.
    resumed = ResearchWorkflow(
        orchestrator=_HappyOrchestrator(),  # type: ignore[arg-type]
        store=store,
        interrupt_after=WorkflowStep.DRAFTED,
    )
    decision = ReviewDecision(
        decision_id=DECISION_ID,
        report_id=report_id,
        context=query.context,
        action=ReviewAction.APPROVE,
        rationale="Citations resolve.",
        recorded_at=NOW,
    )
    checkpoint = resumed.resume(query=query, title="Fees", human_decision=decision)
    assert checkpoint.step is WorkflowStep.COMPLETED
