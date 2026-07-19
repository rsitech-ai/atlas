"""Strict Phase 3 research / report contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    CitationBinding,
    CitationRole,
    FindingCompletionStatus,
    ReportDraft,
    ReportSection,
    ResearchAssertion,
    ReviewAction,
    ReviewDecision,
    SpecialistFinding,
    SpecialistTask,
    SpecialistType,
    citation_binding_id,
    report_draft_id,
    research_assertion_id,
    specialist_finding_id,
    specialist_task_id,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
DECISION_ID = UUID("00000000-0000-4000-8000-0000000000dd")
RUN_ID = "retrievalrun:" + ("a" * 64)
PACKET_ID = "evidencepacket:" + ("b" * 64)
CHUNK_ID = "chunk:" + ("c" * 64)
EXCERPT_HASH = "d" * 64
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


def test_specialist_task_blocks_tokenomics() -> None:
    with pytest.raises(ValidationError, match="blocked"):
        SpecialistTask(
            task_id=specialist_task_id(
                run_id=RUN_ID,
                specialist_type=SpecialistType.TOKENOMICS,
                subquestion="supply",
            ),
            specialist_type=SpecialistType.TOKENOMICS,
            run_id=RUN_ID,
            packet_id=PACKET_ID,
            subquestion="What is circulating supply?",
            context_budget_tokens=512,
            repair_limit=1,
        )


def test_supported_finding_requires_evidence() -> None:
    task_id = specialist_task_id(
        run_id=RUN_ID,
        specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
        subquestion="unlock",
    )
    with pytest.raises(ValidationError, match="supporting evidence"):
        SpecialistFinding(
            finding_id=specialist_finding_id(
                task_id=task_id,
                answer="Unlocks begin in 2027.",
                completion_status=FindingCompletionStatus.SUPPORTED,
                supporting_chunk_ids=(),
            ),
            task_id=task_id,
            specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
            answer="Unlocks begin in 2027.",
            supporting_chunk_ids=(),
            completion_status=FindingCompletionStatus.SUPPORTED,
            confidence=0.9,
            recorded_at=NOW,
        )


def test_report_draft_requires_direct_support_citation() -> None:
    task_id = specialist_task_id(
        run_id=RUN_ID,
        specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
        subquestion="unlock",
    )
    finding_id = specialist_finding_id(
        task_id=task_id,
        answer="Unlocks begin in 2027.",
        completion_status=FindingCompletionStatus.SUPPORTED,
        supporting_chunk_ids=(CHUNK_ID,),
    )
    assertion = ResearchAssertion(
        assertion_id=research_assertion_id(
            run_id=RUN_ID,
            finding_id=finding_id,
            statement="Token unlocks begin in 2027.",
            supporting_chunk_ids=(CHUNK_ID,),
        ),
        run_id=RUN_ID,
        finding_id=finding_id,
        statement="Token unlocks begin in 2027.",
        supporting_chunk_ids=(CHUNK_ID,),
        confidence=0.8,
    )
    citation = CitationBinding(
        citation_id=citation_binding_id(
            assertion_id=assertion.assertion_id,
            chunk_id=CHUNK_ID,
            role=CitationRole.DIRECT_SUPPORT,
            excerpt_hash=EXCERPT_HASH,
        ),
        assertion_id=assertion.assertion_id,
        chunk_id=CHUNK_ID,
        role=CitationRole.DIRECT_SUPPORT,
        excerpt_hash=EXCERPT_HASH,
        locator="chunk:ordinal:0",
    )
    report_id = report_draft_id(
        run_id=RUN_ID,
        title="Unlock note",
        version=1,
        assertions=(assertion,),
        citations=(citation,),
    )
    draft = ReportDraft(
        report_id=report_id,
        run_id=RUN_ID,
        context=_context(),
        title="Unlock note",
        sections=(
            ReportSection(
                section_id="findings",
                title="Findings",
                prose="Token unlocks begin in 2027.",
                assertion_ids=(assertion.assertion_id,),
            ),
        ),
        assertions=(assertion,),
        citations=(citation,),
        version=1,
        recorded_at=NOW,
    )
    assert draft.report_id.startswith("report:")

    with pytest.raises(ValidationError, match="direct_support"):
        ReportDraft(
            report_id=report_id,
            run_id=RUN_ID,
            context=_context(),
            title="Unlock note",
            sections=(
                ReportSection(
                    section_id="findings",
                    title="Findings",
                    prose="Token unlocks begin in 2027.",
                    assertion_ids=(assertion.assertion_id,),
                ),
            ),
            assertions=(assertion,),
            citations=(
                CitationBinding(
                    citation_id=citation_binding_id(
                        assertion_id=assertion.assertion_id,
                        chunk_id=CHUNK_ID,
                        role=CitationRole.BACKGROUND,
                        excerpt_hash=EXCERPT_HASH,
                    ),
                    assertion_id=assertion.assertion_id,
                    chunk_id=CHUNK_ID,
                    role=CitationRole.BACKGROUND,
                    excerpt_hash=EXCERPT_HASH,
                    locator="chunk:ordinal:0",
                ),
            ),
            version=1,
            recorded_at=NOW,
        )


def test_review_decision_is_immutable_record() -> None:
    decision = ReviewDecision(
        decision_id=DECISION_ID,
        report_id="report:" + ("f" * 64),
        context=_context(),
        action=ReviewAction.REQUEST_MORE_EVIDENCE,
        rationale="Need independent unlock table confirmation.",
        recorded_at=NOW,
    )
    assert decision.action is ReviewAction.REQUEST_MORE_EVIDENCE
