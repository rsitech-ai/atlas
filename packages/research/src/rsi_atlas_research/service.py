"""Application orchestration for retrieve → specialist → cited report."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from rsi_atlas_contracts import (
    EvidencePacket,
    ReportDraft,
    ResearchQuery,
    RetrievalAbstention,
    ReviewAction,
    ReviewDecision,
    SpecialistFinding,
    SpecialistTask,
    SpecialistType,
    specialist_task_id,
)
from rsi_atlas_retrieval import HybridRetrievalService

from rsi_atlas_research.assertions import AssertionBuilder
from rsi_atlas_research.citations import CitationBinder
from rsi_atlas_research.document_specialist import DocumentEvidenceSpecialist
from rsi_atlas_research.planner import validate_retrieval_plan
from rsi_atlas_research.reports import ReportGate


class ResearchStore(Protocol):
    def save_run(
        self, *, context: object, result: EvidencePacket | RetrievalAbstention
    ) -> None: ...

    def get_run(self, *, context: object, run_id: str) -> dict[str, object] | None: ...

    def save_report(self, *, context: object, report: ReportDraft) -> None: ...

    def get_report(self, *, context: object, report_id: str) -> dict[str, object] | None: ...

    def save_review(self, *, context: object, decision: ReviewDecision) -> None: ...


class ResearchOrchestrator:
    """Development research pipeline over hybrid retrieval."""

    def __init__(
        self,
        *,
        retrieval: HybridRetrievalService,
        store: ResearchStore | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._store = store
        self._specialist = DocumentEvidenceSpecialist()
        self._assertions = AssertionBuilder()
        self._citations = CitationBinder()
        self._reports = ReportGate()

    def retrieve(
        self, *, query: ResearchQuery, now: datetime | None = None
    ) -> EvidencePacket | RetrievalAbstention:
        plan = validate_retrieval_plan(self._retrieval.build_default_plan(query=query))
        result = self._retrieval.retrieve(query=query, plan=plan, now=now)
        if self._store is not None:
            self._store.save_run(context=query.context, result=result)
        return result

    def run_document_specialist(
        self,
        *,
        query: ResearchQuery,
        packet: EvidencePacket,
        subquestion: str | None = None,
        now: datetime | None = None,
    ) -> SpecialistFinding:
        question = subquestion or query.text
        task = SpecialistTask(
            task_id=specialist_task_id(
                run_id=packet.run_id,
                specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
                subquestion=question,
            ),
            specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
            run_id=packet.run_id,
            packet_id=packet.packet_id,
            subquestion=question,
            permitted_subjects=query.subject_ids,
            context_budget_tokens=min(query.context_budget_tokens, 4_096),
            repair_limit=1,
        )
        return self._specialist.run(task=task, packet=packet, now=now)

    def draft_report(
        self,
        *,
        query: ResearchQuery,
        packet: EvidencePacket,
        finding: SpecialistFinding,
        title: str,
        now: datetime | None = None,
    ) -> ReportDraft:
        assertion = self._assertions.from_finding(
            run_id=packet.run_id,
            finding=finding,
            subject_ids=query.subject_ids,
        )
        if assertion is None:
            raise ValueError("cannot draft report without a supported assertion")
        citations = self._citations.bind_assertion(assertion=assertion, packet=packet)
        report = self._reports.draft(
            context=query.context,
            run_id=packet.run_id,
            title=title,
            assertions=(assertion,),
            citations=citations,
            prose=finding.answer,
            now=now or datetime.now(UTC),
        )
        if self._store is not None:
            self._store.save_report(context=query.context, report=report)
        return report

    def review_report(
        self,
        *,
        query: ResearchQuery,
        report: ReportDraft,
        action: ReviewAction,
        rationale: str,
        now: datetime | None = None,
    ) -> ReviewDecision:
        decision = self._reports.review(
            context=query.context,
            report=report,
            action=action,
            rationale=rationale,
            now=now,
        )
        if self._store is not None:
            self._store.save_review(context=query.context, decision=decision)
        return decision
